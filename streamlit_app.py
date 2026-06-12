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
# UTILITY FUNCTIONS
# ==========================================
def clean_html(raw_html):
    """
    Strips raw HTML tags from a text string.
    
    Input: raw_html (str) - The raw summary text from the RSS feed.
    Output: cleantext (str) - Pure text safe for Streamlit rendering.
    """
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def get_source_abbreviation(name):
    """
    Creates a compact 3-4 letter abbreviation for a news source.
    
    Input: name (str) - Full name of the news source (e.g., "TechCrunch").
    Output: (str) - Abbreviation (e.g., "TEC" or "TC").
    """
    words = [w for w in re.split(r'\W+', name) if w]
    if len(words) == 1:
        return name[:3].upper()
    return "".join([w[0].upper() for w in words])[:4]


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

def save_to_database(article_data, target_lang):
    """
    Upserts (Updates or Inserts) a single article into Google Sheets.
    Triggered silently in the background when an AI processing button is clicked.
    
    Input: 
      - article_data (dict): The specific article dictionary being processed.
      - target_lang (str): The language selected in the sidebar.
    Output: (str) - "updated", "saved", or "error".
    """
    try:
        my_sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet_link"]
        
        # DESIGN CHOICE: ttl=0 bypasses Streamlit's built-in memory cache.
        # This is critical so we don't accidentally overwrite new data with stale data.
        existing_data = conn.read(spreadsheet=my_sheet_url, worksheet="Sheet1", ttl=0)
        
        # Safeguard: If the sheet is brand new/blank, manually create headers
        if 'article_id' not in existing_data.columns:
            existing_data = pd.DataFrame(columns=['article_id', 'timestamp', 'source', 'title', 'published_date', 'processing_tier', 'target_language', 'raw_rss_snippet', 'translated_text', 'ai_summary'])

        # Determine how deep the AI processed the text
        processing_tier = "1. Default"
        translated_text = ""
        ai_summary = ""
        
        if "analysis_result" in article_data:
            processing_tier = "3. Deep Analyze"
            ai_summary = article_data["analysis_result"]
        elif "translation_result" in article_data:
            processing_tier = "2. Translate RSS"
            translated_text = article_data["translation_result"]

        # DESIGN CHOICE: UPSERT LOGIC
        # Instead of creating duplicates, we find the existing row via the URL ('article_id')
        # and simply update the translation/summary columns.
        if article_data['link'] in existing_data['article_id'].values:
            row_idx = existing_data.index[existing_data['article_id'] == article_data['link']].tolist()[0]
            existing_data.at[row_idx, 'processing_tier'] = processing_tier
            existing_data.at[row_idx, 'target_language'] = target_lang
            
            if translated_text: existing_data.at[row_idx, 'translated_text'] = translated_text
            if ai_summary: existing_data.at[row_idx, 'ai_summary'] = ai_summary
                
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=existing_data)
            return "updated"
            
        else:
            # Fallback: Create a new row if it somehow wasn't cached during fetch
            new_row = pd.DataFrame([{
                "article_id": article_data['link'],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": article_data['source'],
                "title": article_data['title'],
                "published_date": article_data['published'],
                "processing_tier": processing_tier,
                "target_language": target_lang if processing_tier != "1. Default" else "Original",
                "raw_rss_snippet": clean_html(article_data['rss_summary']),
                "translated_text": translated_text,
                "ai_summary": ai_summary
            }])
            
            updated_df = pd.concat([existing_data, new_row], ignore_index=True)
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=updated_df)
            return "saved"
            
    except Exception as e:
        # User-friendly error handling for common API issues
        error_str = str(e)
        if "403" in error_str or "API has not been used" in error_str or "Permission denied" in error_str:
            st.error("🚨 **Google Sheets Error:** Ensure the **Google Sheets API** is enabled in your Google Cloud Console, and that your bot's email is invited as an **Editor** to the spreadsheet. https://console.developers.google.com/apis/api/sheets.googleapis.com/overview")
            return "error"
        else:
            st.error(f"🚨 Save Error: {error_str}") 
            return "error"

def batch_save_new_articles(articles_list):
    """
    Bulk-saves an array of fetched articles into Google Sheets instantly.
    Triggered once during the main 'Fetch News' routine.
    
    Input: articles_list (list) - List of article dictionaries.
    Output: None.
    
    DESIGN CHOICE: Doing this in bulk prevents hitting Google API rate limits. 
    It acts as our historical "cache" so we never lose tracked links.
    """
    try:
        my_sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet_link"]
        existing_data = conn.read(spreadsheet=my_sheet_url, worksheet="Sheet1", usecols=list(range(10)), ttl=0)
        
        if 'article_id' not in existing_data.columns:
             existing_data['article_id'] = ""
             
        # Using a python set() makes checking for duplicates lightning fast
        existing_urls = set(existing_data['article_id'].dropna().values)
        
        new_rows = []
        for art in articles_list:
            if art['link'] not in existing_urls:
                new_rows.append({
                    "article_id": art['link'],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": art['source'],
                    "title": art['title'],
                    "published_date": art['published'],
                    "processing_tier": "1. Default",
                    "target_language": "Original",
                    "raw_rss_snippet": clean_html(art['rss_summary']),
                    "translated_text": "",
                    "ai_summary": ""
                })
        
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            updated_df = pd.concat([existing_data, new_df], ignore_index=True)
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=updated_df)
            
    except Exception as e:
        error_str = str(e)
        if "403" in error_str or "API has not been used" in error_str or "Permission denied" in error_str:
            st.error("🚨 **Google Sheets Error:** Ensure the **Google Sheets API** is enabled in your Google Cloud Console, and that your bot's email is invited as an **Editor** to the spreadsheet. https://console.developers.google.com/apis/api/sheets.googleapis.com/overview")
            return "error"
        else:
            st.error(f"🚨 Save Error: {error_str}") 
            return "error"

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

# Instead of st.button("Fetch News")
if st.button(t("btn_fetch"), type="primary"):
    pass

# Instead of st.spinner("Çeviriliyor...")
with st.spinner(t("msg_translating")):
    pass

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
    st.subheader("Eklenecek Özellikler (Gelecekte):")
    st.divider()
    st.subheader("Google Sheets'e Aktarma")
    st.divider()
    st.subheader("Word'e Aktarma")
    st.divider()
    st.subheader("Kategori İşaretleme")
    st.divider()
    st.subheader("İlave Feed Ekleme")
    st.divider()
    st.subheader("Dil / Lokalizasyon")
    st.divider()
    st.subheader("Sosyal Medyadan Okuma")

# Initialize session state for articles so they don't vanish on button clicks
if "articles" not in st.session_state:
    st.session_state.articles = []

# Main Fetch Workflow
if st.button("Fetch News", type="primary"):
    fetched_articles = []
    
    with st.spinner(f"Fetching RSS feeds from the last {days_back} days..."):
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