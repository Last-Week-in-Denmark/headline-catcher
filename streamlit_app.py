
import streamlit as st
import streamlit.components.v1 as components
import feedparser
from newspaper import Article
from openai import OpenAI
import os
import json
import re
import time
from datetime import datetime, timedelta

# --- ENVIRONMENT & CONFIGURATION ---
current_env = os.environ.get("ENV", "dev")
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

def get_source_abbreviation(name):
    """Generates a short abbreviation for the news source (e.g., 'BBC World News' -> 'BWN')."""
    words = [w for w in re.split(r'\W+', name) if w]
    if len(words) == 1:
        return name[:3].upper()
    return "".join([w[0].upper() for w in words])[:4]

# ==========================================
# 1. TEAM PASSWORD PROTECTION LOGIC
# ==========================================
def check_password():
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

@st.cache_data(show_spinner=False, ttl=1800)
def get_cached_feed_entries(feed_url):
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
    entries = get_cached_feed_entries(feed_url) 
    articles = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    for entry in entries:
        dt = None
        if entry["published_parsed"]:
            dt = datetime.fromtimestamp(time.mktime(entry["published_parsed"]))
            
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

if "articles" not in st.session_state:
    st.session_state.articles = []

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


# --- GRID DISPLAY LOGIC ---
if st.session_state.articles:
    st.divider()
    
    total_articles = len(st.session_state.articles)
    st.markdown(f"### 📰 Total Links Fetched: **{total_articles}**")
    st.write("") 
    
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
                        
                        # Removed the inline link to make way for the big copy button
                        st.caption(f"📅 {art['published']}")
                        
                        clean_summary = clean_html(art['rss_summary'])
                        snippet_words = clean_summary.split()[:20]
                        snippet = " ".join(snippet_words) + ("..." if len(snippet_words) >= 20 else "")
                        
                        st.write(f"*{snippet}*")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        
                        if btn_col1.button("🌐 Çevir", key=f"trans_{idx}"):
                            with st.spinner("Çeviriliyor..."):
                                art['translation_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                        
                        if btn_col2.button("👀 Metni Analiz Et", key=f"analyze_{idx}"):
                            with st.spinner("Siteye erişiliyor..."):
                                raw_text = extract_article_text(art['link'])
                                if len(raw_text) > 300:
                                    art['analysis_result'] = process_with_ai(raw_text, "deep_analyze", target_language)
                                else:
                                    st.warning("⚠️ Could not extract full text. Translating summary instead.")
                                    art['analysis_result'] = process_with_ai(clean_summary, "translate_only", target_language)

                        if "translation_result" in art:
                            st.success(f"**Başlık Çevirisi ({target_language}):**\n\n{art['translation_result']}")
                            
                        if "analysis_result" in art:
                            st.info(f"**Metin Analizi () ({target_language}):**\n\n{art['analysis_result']}")

                        # --- RICH-TEXT COPY BUTTON ---
                        st.write("") 
                        
                        # 1. Determine the best available content
                        if "analysis_result" in art:
                            best_text = art["analysis_result"]
                        elif "translation_result" in art:
                            best_text = art["translation_result"]
                        else:
                            best_text = clean_summary
                        
                        # 2. Get the abbreviation and format the HTML
                        #abbr = get_source_abbreviation(art['source'])
                        abbr = art['source']
                        formatted_text = best_text.replace('\n', '<br>')
                        
                        # Use backslash to escape single quotes so it doesn't break the Javascript below
                        safe_html = f"{formatted_text}<br><br><a href='{art['link']}'>{(abbr)}</a>".replace("'", "\\'")
                        
                        # 3. Create a custom Javascript button to push Rich Text to the clipboard
                        copy_html = f"""
                        <div style="margin-top: 5px;">
                            <button id="copy-btn" style="
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
                            <p id="msg" style="display:none; color:#00cc44; font-size:12px; margin-top:6px; text-align:center; font-family:sans-serif;">✅ Copied as Rich Text!</p>
                        </div>
                        
                        <script>
                        document.getElementById("copy-btn").addEventListener("click", function() {{
                            const htmlContent = '{safe_html}';
                            
                            // Create a hidden div to render the HTML properly
                            const div = document.createElement("div");
                            div.innerHTML = htmlContent;
                            div.style.position = "absolute";
                            div.style.left = "-9999px";
                            document.body.appendChild(div);
                            
                            // Select the rendered text
                            const range = document.createRange();
                            range.selectNodeContents(div);
                            const sel = window.getSelection();
                            sel.removeAllRanges();
                            sel.addRange(range);
                            
                            // Execute browser copy command
                            document.execCommand("copy");
                            
                            // Cleanup and show success message
                            document.body.removeChild(div);
                            const msg = document.getElementById("msg");
                            msg.style.display = "block";
                            setTimeout(() => msg.style.display = "none", 2500);
                        }});
                        </script>
                        """
                        
                        # Render the custom button inside the Streamlit app
                        components.html(copy_html, height=75)