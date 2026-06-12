import streamlit as st
import feedparser
from newspaper import Article
from openai import OpenAI
import os
import json
import re
import time
from datetime import datetime, timedelta
import traceback

import pandas as pd
from streamlit_gsheets import GSheetsConnection

# Internal Imports

from services.databases import save_to_database, batch_save_new_articles
from services.utils import clean_html, get_source_abbreviation

# ==========================================
# ENVIRONMENT & CONFIGURATION
# ==========================================
# Determine environment (dev/prod/tr). 
# DESIGN CHOICE: Loading configs dynamically allows the app to be easily 
# translated or repurposed for other teams without changing the core Python code.
current_env = os.environ.get("ENV", "dev")
current_env = "tr" # Forced override for Turkish setup

config_file = f"config.{current_env}.json"
with open(config_file, "r") as f:
    config = json.load(f)

# 1. Default to Turkish if the user hasn't picked yet
#if "app_lang" not in st.session_state:
    #st.session_state.app_lang = "en"
st.session_state.app_lang = "tr"

# 2. Cache the loading of the dictionary so it's lightning fast
@st.cache_data
def load_translations(lang_code):
    with open(f"locales/{lang_code}.json", "r", encoding="utf-8") as f:
        return json.load(f)

# 3. Create the standard t() helper function
def t(key):
    translations = load_translations(st.session_state.app_lang)
    return translations.get(key, f"Missing translation: {key}")

# ==========================================
# 1. TEAM PASSWORD PROTECTION LOGIC
# ==========================================
def check_password():
    """
    Validates user access against the password stored in Streamlit Secrets.
    
    Input: None.
    Output: (bool) - True if authenticated, False otherwise.
    
    DESIGN CHOICE: Uses `st.session_state` so the user doesn't have to 
    re-type the password every time they click a button and trigger a page rerun.
    """
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title(config['LOCALIZATION_PASSWORD_SCREEN'])
        st.write(config['LOCALIZATION_PASSWORD_SCREEN_PROMPT'])
        pwd = st.text_input("Password:", type="password")
        
        if pwd == st.secrets["TEAM_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun() # Refresh page to show the main app
        elif pwd:
            st.error(config['LOCALIZATION_PASSWORD_SCREEN_INCORRECT_PASSWORD'])
        return False
    return True

if not check_password():
    st.stop() # Halts all script execution if not logged in


# ==========================================
# 2. CORE FUNCTIONS & DATABASE
# ==========================================

# Initialize global connections
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(show_spinner=False, ttl=1800)
def get_cached_feed_entries(feed_url):
    """
    Downloads raw RSS XML and converts it to basic Python dictionaries.
    
    Input: feed_url (str) - URL of the RSS feed.
    Output: list - Cleaned dictionary entries.
    
    DESIGN CHOICE: This is wrapped in `@st.cache_data(ttl=1800)` (30 mins) so we don't
    constantly ping and get IP-banned by news websites when the user interacts with the UI.
    We return basic dictionaries because complex feedparser objects cannot be cached.
    """
    feed = feedparser.parse(feed_url)
    entries = []
    for entry in feed.entries:
        entries.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", "No date provided"),
            "summary": entry.get("summary", "No standard RSS summary available."),
            "published_parsed": getattr(entry, 'published_parsed', None)
        })
    return entries

def fetch_rss_links(feed_url, source_name, days_back):
    """
    Filters cached RSS entries based on the user's date slider.
    
    Input: 
      - feed_url (str)
      - source_name (str): Name of the source (e.g., TechCrunch).
      - days_back (int): Dynamic value from the UI slider.
    Output: list - Filtered articles.
    """
    entries = get_cached_feed_entries(feed_url) 
    articles = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    for entry in entries:
        dt = None
        if entry["published_parsed"]:
            dt = datetime.fromtimestamp(time.mktime(entry["published_parsed"]))
            
        # Skip articles older than our dynamic cutoff date
        if dt and dt < cutoff_date:
            continue 
            
        articles.append({
            "title": entry["title"],
            "link": entry["link"],
            "source": source_name,
            "published": entry["published"],
            "rss_summary": entry["summary"]
        })
    return articles

def extract_article_text(url):
    """
    Uses the Newspaper3k library to scrape the full article body text.
    
    Input: url (str)
    Output: (str) - Full scraped text, or empty string if scraping fails/blocked.
    """
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception:
        return ""

def process_with_ai(text, task_type, target_lang):
    """
    Passes text to OpenAI GPT-4o-mini with specific system instructions.
    
    Input:
      - text (str): The raw summary or scraped full body text.
      - task_type (str): "translate_only" or "deep_analyze".
      - target_lang (str): User's selected output language.
    Output: (str) - AI generated text.
    """
    if task_type == "translate_only":
        system_instruction = f"You are a professional translator. Translate the following text into {target_lang}. Do not summarize, just translate accurately."
    else: 
        system_instruction = f"You are an expert news editor. Analyze the article text. Provide a highly engaging headline, followed by a 3-bullet point summary of the key facts. Write the entire response in {target_lang}."

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text}
            ],
            temperature=0.3 # Low temperature for factual consistency
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**AI Error:** {e}"


# ==========================================
# 3. STREAMLIT USER INTERFACE
# ==========================================

# --- MAIN UI ---
st.title(t("app_title"))


# --- SIDEBAR ---
# Map the pretty display names to the file codes
lang_options = {"English": "en", "Türkçe": "tr", "Dansk": "da"}

# When this changes, it automatically updates st.session_state.app_lang
selected_display_lang = st.sidebar.selectbox(
    "🌍 App Language:", 
    options=list(lang_options.keys()),
    # Find the index of the current active language to set the default
    index=list(lang_options.values()).index(st.session_state.app_lang)
)

# Update the system state if they clicked a new language
st.session_state.app_lang = lang_options[selected_display_lang]

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Settings")
    
    feed_options = list(config.get("FEEDS", {}).keys())
    feed_options.insert(0, "All Feeds") 
    
    selected_feed_name = st.selectbox("Select News Channel:", options=feed_options)
    
    st.divider()
    st.subheader("Date & Volume Filter")
    days_back = st.slider("Include news from the last X days:", min_value=1, max_value=30, value=7)
    num_articles = st.slider("Max articles to fetch per channel:", 1, 10, 3)
    
    st.divider()
    st.subheader("Target Language")
    target_language = st.selectbox("Translate to:", ["Turkish", "Danish", "English"])

    st.divider()
    st.subheader(f"Google Sheets Linki: {config.get('GOOGLE_SHEET_URL', 'Not configured')}")
    st.divider()
    st.subheader("Eklenecek Özellikler (Gelecekte):")
    st.divider()
    st.subheader("İlave Feed Ekleme")
    st.divider()
    st.subheader("Haber Masasında Eklenecek Özellikler")
    st.divider()
    st.subheader("Word'e Aktarma")
    st.divider()
    st.subheader("Kategori İşaretleme")
    st.divider()
    st.subheader("Sosyal Medyadan Okuma")
    st.divider()

# Initialize session state for articles so they don't vanish on button clicks
if "articles" not in st.session_state:
    st.session_state.articles = []

# Fetch Button
if st.button(t("btn_fetch"), type="primary"):
    fetched_articles = []
    
    # Spinner
    with st.spinner(f"{t("msg_translating")}"):
        if selected_feed_name == "All Feeds":
            for name, url in config.get("FEEDS", {}).items():
                fetched_articles.extend(fetch_rss_links(url, name, days_back)[:num_articles])
        else:
            url = config["FEEDS"][selected_feed_name]
            fetched_articles = fetch_rss_links(url, selected_feed_name, days_back)[:num_articles]
        
    if not fetched_articles:
        st.warning(f"Could not find any articles from the last {days_back} days. Try increasing the date range!")
    else:
        st.session_state.articles = fetched_articles
        
        # Trigger background batch caching
        with st.spinner("Caching new articles to database..."):
            batch_save_new_articles(fetched_articles)


# --- GRID DISPLAY LOGIC ---
if st.session_state.articles:
    st.divider()
    
    total_articles = len(st.session_state.articles)
    st.markdown(f"### 📰 Total Links Fetched: **{total_articles}**")
    st.write("") 
    
    # DESIGN CHOICE: Creating a responsive 2-column grid.
    # We step through the articles array 2 items at a time.
    for i in range(0, len(st.session_state.articles), 2):
        cols = st.columns(2)
        
        for j in range(2):
            if i + j < len(st.session_state.articles):
                idx = i + j
                art = st.session_state.articles[idx]
                
                with cols[j]:
                    with st.container(border=True):
                        st.caption(f"📢 Source: **{art['source']}**")
                        st.subheader(art['title'])
                        st.caption(f"📅 {art['published']}")
                        
                        # Generate a clean 20-word preview of the raw RSS data
                        clean_summary = clean_html(art['rss_summary'])
                        snippet_words = clean_summary.split()[:20]
                        snippet = " ".join(snippet_words) + ("..." if len(snippet_words) >= 20 else "")
                        st.write(f"*{snippet}*")
                        
                        # --- AI ACTION BUTTONS ---
                        btn_col1, btn_col2 = st.columns(2)
                        
                        if btn_col1.button("🌐 Çevir", key=f"trans_{idx}"):
                            with st.spinner("Çeviriliyor ve kaydediliyor..."):
                                art['translation_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                                save_to_database(art, target_language) # Auto-save trigger
                        
                        if btn_col2.button("👀 Metni Analiz Et", key=f"analyze_{idx}"):
                            with st.spinner("Siteye erişiliyor ve kaydediliyor..."):
                                raw_text = extract_article_text(art['link'])
                                if len(raw_text) > 300:
                                    art['analysis_result'] = process_with_ai(raw_text, "deep_analyze", target_language)
                                else:
                                    st.warning("⚠️ Could not extract full text. Translating summary instead.")
                                    art['analysis_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                                save_to_database(art, target_language) # Auto-save trigger

                        # Display results if they exist in the dictionary
                        if "translation_result" in art:
                            st.success(f"**Başlık Çevirisi ({target_language}):**\n\n{art['translation_result']}")
                        if "analysis_result" in art:
                            st.info(f"**Metin Analizi ({target_language}):**\n\n{art['analysis_result']}")

                        # --- TRUE RICH-TEXT COPY BUTTON ---
                        # DESIGN CHOICE: Streamlit's native copy functionality only copies plain text.
                        # We use a custom st.iframe block injecting HTML/Javascript to force the 
                        # browser's clipboard to copy this as Rich Text (allowing hyperlinks to remain active).
                        st.write("") 
                        
                        # Prioritize the most advanced text generation available
                        if "analysis_result" in art:
                            best_text = art["analysis_result"]
                        elif "translation_result" in art:
                            best_text = art["translation_result"]
                        else:
                            best_text = clean_summary
                        
                        abbr = art['source']
                        formatted_text = best_text.replace('\n', '<br>')
                        
                        # Build HTML string injected into the JS
                        full_html = f"<strong>{art['title']}</strong><br><br>{formatted_text}<br><br><a href='{art['link']}'>{abbr}</a>"
                        safe_html = full_html.replace("'", "\\'")
                        
                        copy_html = f"""
                        <div style="margin-top: 5px;">
                            <button id="copy-btn-{idx}" style="
                                width: 100%;
                                background-color: #2b2b36;
                                color: #ffffff;
                                border: 1px solid #4b4b5c;
                                padding: 8px;
                                border-radius: 6px;
                                cursor: pointer;
                                font-family: sans-serif;
                                font-size: 14px;
                                font-weight: bold;
                                transition: background-color 0.2s;
                            ">📋 COPY RENDERED HTML</button>
                            <p id="msg-{idx}" style="display:none; color:#00cc44; font-size:12px; margin-top:6px; text-align:center; font-family:sans-serif;">✅ Copied as Rich Text!</p>
                        </div>
                        
                        <script>
                        document.getElementById("copy-btn-{idx}").addEventListener("click", function() {{
                            const htmlContent = '{safe_html}';
                            const div = document.createElement("div");
                            div.innerHTML = htmlContent;
                            div.style.position = "absolute";
                            div.style.left = "-9999px";
                            document.body.appendChild(div);
                            
                            const range = document.createRange();
                            range.selectNodeContents(div);
                            const sel = window.getSelection();
                            sel.removeAllRanges();
                            sel.addRange(range);
                            
                            document.execCommand("copy");
                            
                            document.body.removeChild(div);
                            const msg = document.getElementById("msg-{idx}");
                            msg.style.display = "block";
                            setTimeout(() => msg.style.display = "none", 2500);
                        }});
                        </script>
                        """
                        st.iframe(copy_html, height=75)