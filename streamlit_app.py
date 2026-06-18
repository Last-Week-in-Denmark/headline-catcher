import streamlit as st
import os
import json
import traceback

# Internal Imports
from services.databases import save_to_database, batch_save_new_articles, load_cached_articles
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
    t("lbl_app_lang"), 
    options=list(lang_options.keys()),
    index=list(lang_options.values()).index(st.session_state.app_lang)
)
st.session_state.app_lang = lang_options[selected_display_lang]

with st.sidebar:
    st.header(t("lbl_settings"))
    
    feed_options = list(config.get("FEEDS", {}).keys())
    feed_options.insert(0, "All Feeds") 
    
    selected_feed_name = st.selectbox(t("lbl_select_channel"), options=feed_options)
    
    st.divider()
    st.subheader(t("lbl_date_volume_filter"))
    days_back = st.slider(t("lbl_days_back"), min_value=1, max_value=30, value=7)
    num_articles = st.select_slider(
        t("lbl_max_articles"),
        options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, "ALL"],
        value=3
    )
    
    st.divider()
    target_language = st.selectbox(t("lbl_translate_to"), ["Turkish", "Danish", "English"])
    
    st.divider()
    gsheet_url = st.secrets.get("connections", {}).get("gsheets", {}).get("spreadsheet_link", 'Not configured') 
    st.write(f"{t('lbl_gsheet_url')} {gsheet_url}")
    st.divider()
    st.subheader(t("lbl_future_features"))
    st.divider()
    st.subheader(t("lbl_ai_credits"))
    st.divider()
    st.subheader(t("lbl_cache_speedup"))
    st.divider()
    st.subheader(t("lbl_fill_missing_translations"))
    st.divider()
    st.subheader(t("lbl_add_more_feeds"))
    st.divider()
    st.subheader(t("lbl_alt_frontend"))
    st.divider()
    st.subheader(t("lbl_newsroom_features"))
    st.divider()
    st.subheader(t("lbl_export_word"))
    st.divider()
    st.subheader(t("lbl_tag_categories"))
    st.divider()
    st.subheader(t("lbl_read_social_media"))
    st.divider()

if "articles" not in st.session_state:
    st.session_state.articles = []

# Fetch Button
if st.button(t("btn_fetch"), type="primary"):
    fetched_articles = []
    
    with st.spinner(t("msg_loading_cached")):
        # 1. Load already cached articles from Google Sheets
        cached_articles = load_cached_articles(selected_feed_name, days_back)
        
    with st.spinner(t("msg_translating")):
        # 2. Now fetch live RSS feeds
        rss_articles = []
        if selected_feed_name == "All Feeds":
            for name, url in config.get("FEEDS", {}).items():
                feed_articles = fetch_rss_links(url, name, days_back)
                if num_articles == "ALL":
                    rss_articles.extend(feed_articles)
                else:
                    rss_articles.extend(feed_articles[:num_articles])
        else:
            url = config["FEEDS"][selected_feed_name]
            feed_articles = fetch_rss_links(url, selected_feed_name, days_back)
            if num_articles == "ALL":
                rss_articles = feed_articles
            else:
                rss_articles = feed_articles[:num_articles]
                
        # 3. Merge: Start with cached articles (which have results)
        merged_articles = list(cached_articles)
        merged_links = {art['link'] for art in merged_articles}
        
        # Add new articles from RSS that aren't in the cache yet
        new_rss_articles = []
        for art in rss_articles:
            if art['link'] not in merged_links:
                # Assign a timestamp datetime of now for correct sorting
                from datetime import datetime
                art["timestamp_dt"] = datetime.now()
                merged_articles.append(art)
                merged_links.add(art['link'])
                new_rss_articles.append(art)
                
        # 4. Sort all merged articles by timestamp descending so newest are first
        from datetime import datetime
        merged_articles.sort(key=lambda x: x.get("timestamp_dt", datetime.min), reverse=True)
        
        # 5. Respect the num_articles limit per source if it is not "ALL"
        if num_articles != "ALL":
            source_counts = {}
            filtered_merged = []
            for art in merged_articles:
                src = art['source']
                count = source_counts.get(src, 0)
                if count < num_articles:
                    filtered_merged.append(art)
                    source_counts[src] = count + 1
            merged_articles = filtered_merged
            
        fetched_articles = merged_articles
        
    if not fetched_articles:
        st.warning(t("msg_no_articles").format(days_back=days_back))
    else:
        st.session_state.articles = fetched_articles
        
        if new_rss_articles:
            with st.spinner(t("msg_caching_new")):
                batch_save_new_articles(new_rss_articles, clean_html)

# --- GRID DISPLAY LOGIC ---
if st.session_state.articles:
    st.divider()
    
    total_articles = len(st.session_state.articles)
    st.markdown(f"### {t('lbl_total_links')} **{total_articles}**")
    st.write("") 
    
    for i in range(0, len(st.session_state.articles), 2):
        cols = st.columns(2)
        
        for j in range(2):
            if i + j < len(st.session_state.articles):
                idx = i + j
                art = st.session_state.articles[idx]
                
                with cols[j]:
                    with st.container(border=True):
                        st.caption(f"{t('lbl_source')} **{art['source']}**")
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
                                    st.warning(t("msg_no_full_text"))
                                    art['analysis_result'] = process_with_ai(clean_summary, "translate_only", target_language)
                                save_to_database(art, target_language, clean_html) 
 
                        if "translation_result" in art:
                            st.success(f"**{t('lbl_translated_result')} ({target_language}):**\n\n{art['translation_result']}")
                        if "analysis_result" in art:
                            st.info(f"**{t('lbl_analysis_result')} ({target_language}):**\n\n{art['analysis_result']}")
 
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
                            ">{t('btn_copy_html')}</button>
                            <p id="msg-{idx}" style="display:none; color:#00cc44; font-size:12px; margin-top:6px; text-align:center; font-family:sans-serif;">{t('lbl_copied')}</p>
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