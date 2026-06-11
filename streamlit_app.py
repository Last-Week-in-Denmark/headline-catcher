import streamlit as st
import feedparser
from newspaper import Article
from openai import OpenAI
import os
import json
import re

# --- ENVIRONMENT & CONFIGURATION ---
current_env = os.environ.get("ENV", "dev")
# Explicit override for Turkish settings matching your snippet
current_env = "tr"

config_file = f"config.{current_env}.json"
with open(config_file, "r") as f:
    config = json.load(f)

# --- UTILS ---
def clean_html(raw_html):
    """Removes HTML tags from text for clean snippets."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

# ==========================================
# 1. TEAM PASSWORD PROTECTION LOGIC
# ==========================================
def check_password():
    """Returns `True` if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title(config['LOCALIZATION_PASSWORD_SCREEN'])
        st.write(config['LOCALIZATION_PASSWORD_SCREEN_PROMPT'])
        pwd = st.text_input("Password:", type="password")
        
        if pwd == st.secrets["TEAM_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        elif pwd:
            st.error(config['LOCALIZATION_PASSWORD_SCREEN_INCORRECT_PASSWORD'])
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. CORE FUNCTIONS
# ==========================================
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

@st.cache_data(show_spinner=False)
def fetch_rss_links(feed_url, source_name):
    """Fetches RSS feed and appends the source name to each item."""
    feed = feedparser.parse(feed_url)
    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "source": source_name,
            "published": entry.get("published", "No date provided"),
            "rss_summary": entry.get("summary", "No standard RSS summary available.")
        })
    return articles

def extract_article_text(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception:
        return ""

def process_with_ai(text, task_type, target_lang):
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
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**AI Error:** {e}"

# ==========================================
# 3. STREAMLIT USER INTERFACE
# ==========================================
st.title(config['LOCALIZATION_SUMMARY_SCREEN_TITLE'])

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Settings")
    
    feed_options = list(config.get("FEEDS", {}).keys())
    feed_options.insert(0, "All Feeds") 
    
    selected_feed_name = st.selectbox("Select News Channel:", options=feed_options)
    num_articles = st.slider("Articles to fetch per channel:", 1, 10, 3)
    
    st.divider()
    st.subheader("Target Language")
    # We keep the language selector so the buttons know what language to translate into
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

# --- SESSION STATE INITIALIZATION ---
# This is crucial: it remembers the articles so they don't disappear when a button is clicked
if "articles" not in st.session_state:
    st.session_state.articles = []

# Main Fetch Button
if st.button("Fetch News", type="primary"):
    fetched_articles = []
    
    with st.spinner("Fetching RSS feeds..."):
        if selected_feed_name == "All Feeds":
            for name, url in config.get("FEEDS", {}).items():
                fetched_articles.extend(fetch_rss_links(url, name)[:num_articles])
        else:
            url = config["FEEDS"][selected_feed_name]
            fetched_articles = fetch_rss_links(url, selected_feed_name)[:num_articles]
        
    if not fetched_articles:
        st.error("Could not find any articles. Check your config file or internet connection.")
    else:
        # Save the fetched articles into memory
        st.session_state.articles = fetched_articles


# --- GRID DISPLAY LOGIC ---
if st.session_state.articles:
    st.divider()
    
    # Loop through articles in chunks of 2 to create rows
    for i in range(0, len(st.session_state.articles), 2):
        cols = st.columns(2)
        
        for j in range(2):
            if i + j < len(st.session_state.articles):
                idx = i + j
                art = st.session_state.articles[idx] # Pointing directly to the session_state item
                
                with cols[j]:
                    with st.container(border=True):
                        st.caption(f"📢 Source: **{art['source']}**")
                        st.subheader(f"{idx+1}. {art['title']}")
                        st.caption(f"📅 {art['published']} | 🔗 [Read Original]({art['link']})")
                        
                        clean_summary = clean_html(art['rss_summary'])
                        snippet_words = clean_summary.split()[:20]
                        snippet = " ".join(snippet_words) + ("..." if len(snippet_words) >= 20 else "")
                        
                        st.write(f"*{snippet}*")
                        
                        # Create a mini-grid for the action buttons side-by-side
                        btn_col1, btn_col2 = st.columns(2)
                        
                        # --- ACTION 1: TRANSLATE SNIPPET ---
                        if btn_col1.button("🌐 Translate", key=f"trans_{idx}"):
                            with st.spinner("Translating..."):
                                art['translation_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                        
                        # --- ACTION 2: DEEP ANALYZE ---
                        if btn_col2.button("🧠 Deep Analyze", key=f"analyze_{idx}"):
                            with st.spinner("Analyzing site..."):
                                raw_text = extract_article_text(art['link'])
                                if len(raw_text) > 300:
                                    art['analysis_result'] = process_with_ai(raw_text, "deep_analyze", target_language)
                                else:
                                    st.warning("⚠️ Could not extract full text. Translating summary instead.")
                                    art['analysis_result'] = process_with_ai(clean_summary, "translate_only", target_language)

                        # --- DISPLAY RESULTS (Persisted from session_state) ---
                        if "translation_result" in art:
                            st.success(f"**Translated ({target_language}):**\n\n{art['translation_result']}")
                            
                        if "analysis_result" in art:
                            st.info(f"**AI Analysis ({target_language}):**\n\n{art['analysis_result']}")

    
