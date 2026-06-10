import streamlit as st
import feedparser
from newspaper import Article
from openai import OpenAI

import os
import json

# Check where the app is running
current_env = os.environ.get("ENV", "dev") # Defaults to 'dev' if not found
# Set to Turkish
current_env = "tr"

# Load the correct settings file
config_file = f"config.{current_env}.json"
with open(config_file, "r") as f:
    config = json.load(f)

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

# Halt execution if the user is not logged in
if not check_password():
    st.stop()

# ==========================================
# 2. CORE FUNCTIONS
# ==========================================
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

@st.cache_data(show_spinner=False)
def fetch_rss_links(feed_url):
    feed = feedparser.parse(feed_url)
    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", "No date provided"),
            # Capture the raw RSS summary for Tier 1 and 2
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
    """Handles both translation and summarization based on the selected tier."""
    if task_type == "translate_only":
        system_instruction = f"You are a professional translator. Translate the following text into {target_lang}. Do not summarize, just translate accurately."
    else: # deep_analyze
        system_instruction = f"You are an expert news editor. Analyze the article text. Provide a highly engaging headline, followed by a 3-bullet point summary of the key facts. Write the entire response in {target_lang}."

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text}
            ],
            temperature=0.3 # Lower temperature for more accurate translation
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**AI Error:** {e}"

# ==========================================
# 3. STREAMLIT USER INTERFACE
# ==========================================
st.title(config['LOCALIZATION_SUMMARY_SCREEN_TITLE'])

# Sidebar for settings keeps the UI clean
with st.sidebar:
    st.header("⚙️ Settings")
    rss_url = st.text_input("RSS Feed URL:", "https://feeds.feedburner.com/TechCrunch/")
    num_articles = st.slider("Articles to fetch:", 1, 10, 3)
    
    st.divider()
    st.subheader("Processing Level (Cost Control)")
    # The 3-way fallback logic
    processing_tier = st.radio(
        "Choose how to process the feed:",
        options=[
            "1. Default (Free, Raw RSS only)", 
            "2. Translate RSS (Low Cost)", 
            "3. Deep Analyze & Translate (Full Article)"
        ],
        index=0
    )
    
    # Only show language selector if an AI tier is chosen
    if "1. Default" not in processing_tier:
        target_language = st.selectbox("Target Language:", ["Spanish", "French", "German", "Japanese", "English"])
    else:
        target_language = None

# Main processing loop
if st.button("Fetch News", type="primary"):
    with st.spinner("Fetching RSS feed..."):
        articles = fetch_rss_links(rss_url)[:num_articles]
        
    if not articles:
        st.error("Could not find any articles. Check the URL.")
    else:
        for idx, art in enumerate(articles):
            st.subheader(f"{idx+1}. {art['title']}")
            st.caption(f"📅 {art['published']} | 🔗 [Original Article]({art['link']})")
            
            # --- TIER 1: Default (Free) ---
            if "1. Default" in processing_tier:
                st.info(f"**Raw RSS Content:**\n\n{art['rss_summary']}")
                
            # --- TIER 2: Translate RSS (Flag A) ---
            elif "2. Translate RSS" in processing_tier:
                with st.spinner("Translating RSS snippet..."):
                    translated_text = process_with_ai(art['rss_summary'], "translate_only", target_language)
                    st.success(f"**Translated ({target_language}):**\n\n{translated_text}")
                    
            # --- TIER 3: Deep Analyze (Flag B) ---
            elif "3. Deep Analyze" in processing_tier:
                with st.spinner("Extracting and analyzing full site content..."):
                    raw_text = extract_article_text(art['link'])
                    
                    if len(raw_text) > 300:
                        analysis = process_with_ai(raw_text, "deep_analyze", target_language)
                        st.success(f"**AI Analysis ({target_language}):**\n\n{analysis}")
                    else:
                        # Fallback if scraping fails (paywall, etc.)
                        st.warning("⚠️ Could not extract full text. Falling back to translating the RSS summary.")
                        fallback_text = process_with_ai(art['rss_summary'], "translate_only", target_language)
                        st.info(f"**Translated Summary:**\n\n{fallback_text}")
            
            st.divider()