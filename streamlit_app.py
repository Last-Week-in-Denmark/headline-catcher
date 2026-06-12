import streamlit as st
import os
import json
import traceback

# Internal Imports
from services.databases import save_to_database, batch_save_new_articles
from services.utils import clean_html, get_source_abbreviation, extract_article_text
from services.rss_engine import fetch_rss_links
from services.llms import process_with_ai

# ==========================================
# ENVIRONMENT & CONFIGURATION
# ==========================================
current_env = os.environ.get("ENV", "dev")
current_env = "tr" 

config_file = f"config.{current_env}.json"
with open(config_file, "r") as f:
    config = json.load(f)

# LOCALIZATION INITIALIZATION
if "app_lang" not in st.session_state:
    st.session_state.app_lang = "tr"

@st.cache_data
def load_translations(lang_code):
    with open(f"locales/{lang_code}.json", "r", encoding="utf-8") as f:
        return json.load(f)

def t(key):
    translations = load_translations(st.session_state.app_lang)
    return translations.get(key, f"Missing translation: {key}")

# ==========================================
# 1. TEAM PASSWORD PROTECTION LOGIC
# ==========================================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title(config.get('LOCALIZATION_PASSWORD_SCREEN', 'Login'))
        st.write(config.get('LOCALIZATION_PASSWORD_SCREEN_PROMPT', 'Enter Password'))
        pwd = st.text_input("Password:", type="password")
        
        if pwd == st.secrets["TEAM_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun() 
        elif pwd:
            st.error(config.get('LOCALIZATION_PASSWORD_SCREEN_INCORRECT_PASSWORD', 'Invalid'))
        return False
    return True

if not check_password():
    st.stop()


# ==========================================
# 2. STREAMLIT USER INTERFACE
# ==========================================
st.title(t("app_title"))

# --- SIDEBAR ---
lang_options = {"English": "en", "Türkçe": "tr", "Dansk": "da"}

selected_display_lang = st.sidebar.selectbox(
    "🌍 App Language:", 
    options=list(lang_options.keys()),
    index=list(lang_options.values()).index(st.session_state.app_lang)
)
st.session_state.app_lang = lang_options[selected_display_lang]

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
    target_language = st.selectbox("Translate to:", ["Turkish", "Danish", "English"])

    st.divider()
    gsheet_url = st.secrets.get("connections", {}).get("gsheets", {}).get("spreadsheet_link", 'Not configured') 
    st.write(f"Current Google Sheets URL: {gsheet_url}")
    st.divider()
    st.subheader("Eklenecek Özellikler (Gelecekte):")
    st.divider()
    st.subheader("AI kalan krediyi goster")
    st.divider()
    st.subheader("Cacheten okuyarak zaman kazandırma")
    st.divider()
    st.subheader("Eksik çevirileri tamamlama!")
    st.divider()
    st.subheader("İlave Feed Ekleme")
    st.divider()
    st.subheader("ST'ye alternatif frontend lokal deployment icin")
    st.divider()
    st.subheader("Haber Masasında Eklenecek Özellikler")
    st.divider()
    st.subheader("Word'e Aktarma")
    st.divider()
    st.subheader("Kategori İşaretleme")
    st.divider()
    st.subheader("Sosyal Medyadan Okuma")
    st.divider()

if "articles" not in st.session_state:
    st.session_state.articles = []

# Fetch Button
if st.button(t("btn_fetch"), type="primary"):
    fetched_articles = []
    
    with st.spinner(t("msg_translating")):
        if selected_feed_name == "All Feeds":
            for name, url in config.get("FEEDS", {}).items():
                fetched_articles.extend(fetch_rss_links(url, name, days_back)[:num_articles])
        else:
            url = config["FEEDS"][selected_feed_name]
            fetched_articles = fetch_rss_links(url, selected_feed_name, days_back)[:num_articles]
        
    if not fetched_articles:
        st.warning(f"Could not find any articles from the last {days_back} days.")
    else:
        st.session_state.articles = fetched_articles
        
        with st.spinner("Caching new articles to database..."):
            # Notice we pass clean_html into the function so the DB file can use it!
            batch_save_new_articles(fetched_articles, clean_html)

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
                        st.caption(f"📅 {art['published']}")
                        
                        clean_summary = clean_html(art['rss_summary'])
                        snippet_words = clean_summary.split()[:20]
                        snippet = " ".join(snippet_words) + ("..." if len(snippet_words) >= 20 else "")
                        st.write(f"*{snippet}*")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        
                        # Use localization for the buttons
                        if btn_col1.button(t("btn_translate"), key=f"trans_{idx}"):
                            with st.spinner(t("msg_translating")):
                                art['translation_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                                save_to_database(art, target_language, clean_html) 
                        
                        if btn_col2.button(t("btn_analyze"), key=f"analyze_{idx}"):
                            with st.spinner(t("msg_translating")):
                                raw_text = extract_article_text(art['link'])
                                if len(raw_text) > 300:
                                    art['analysis_result'] = process_with_ai(raw_text, "deep_analyze", target_language)
                                else:
                                    st.warning("⚠️ Could not extract full text. Translating summary instead.")
                                    art['analysis_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                                save_to_database(art, target_language, clean_html) 

                        if "translation_result" in art:
                            st.success(f"**Translated ({target_language}):**\n\n{art['translation_result']}")
                        if "analysis_result" in art:
                            st.info(f"**Analysis ({target_language}):**\n\n{art['analysis_result']}")

                        st.write("") 
                        
                        if "analysis_result" in art:
                            best_text = art["analysis_result"]
                        elif "translation_result" in art:
                            best_text = art["translation_result"]
                        else:
                            best_text = clean_summary
                        
                        abbr = art['source']
                        formatted_text = best_text.replace('\n', '<br>')
                        
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
                            <p id="msg-{idx}" style="display:none; color:#00cc44; font-size:12px; margin-top:6px; text-align:center; font-family:sans-serif;">✅ Copied!</p>
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