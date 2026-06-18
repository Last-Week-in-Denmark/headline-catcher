import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# 1. Initialize the connection right here inside the module!
conn = st.connection("gsheets", type=GSheetsConnection)

def save_to_database(article_data, target_lang, clean_html_func):
    """Auto-saves or updates the article in Google Sheets."""
    try:
        my_sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet_link"]
        
        # Read the live sheet
        existing_data = conn.read(spreadsheet=my_sheet_url, worksheet="Sheet1", ttl=0)
        
        # --- THE FIX ---
        # Force pandas to fill all empty cells with an empty string ("") 
        # and treat every column as text so it doesn't guess they are numbers (float64)
        existing_data = existing_data.fillna("").astype(str)
        
        if 'article_id' not in existing_data.columns:
            existing_data = pd.DataFrame(columns=['article_id', 'timestamp', 'source', 'title', 'published_date', 'processing_tier', 'target_language', 'raw_rss_snippet', 'translated_text', 'ai_summary'])

        processing_tier = "1. Default"
        translated_text = ""
        ai_summary = ""
        
        if "analysis_result" in article_data:
            processing_tier = "3. Deep Analyze"
            ai_summary = article_data["analysis_result"]
        elif "translation_result" in article_data:
            processing_tier = "2. Translate RSS"
            translated_text = article_data["translation_result"]

        if article_data['link'] in existing_data['article_id'].values:
            row_idx = existing_data.index[existing_data['article_id'] == article_data['link']].tolist()[0]
            existing_data.at[row_idx, 'processing_tier'] = processing_tier
            existing_data.at[row_idx, 'target_language'] = target_lang
            
            if translated_text: existing_data.at[row_idx, 'translated_text'] = translated_text
            if ai_summary: existing_data.at[row_idx, 'ai_summary'] = ai_summary
                
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=existing_data)
            return "updated"
        else:
            new_row = pd.DataFrame([{
                "article_id": article_data['link'],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": article_data['source'],
                "title": article_data['title'],
                "published_date": article_data['published'],
                "processing_tier": processing_tier,
                "target_language": target_lang if processing_tier != "1. Default" else "Original",
                # Note: We pass the clean_html function in as an argument so we don't have circular imports
                "raw_rss_snippet": clean_html_func(article_data['rss_summary']),
                "translated_text": translated_text,
                "ai_summary": ai_summary
            }])
            
            updated_df = pd.concat([existing_data, new_row], ignore_index=True)
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=updated_df)
            
            return "saved"
            
    except Exception as e:
        error_str = str(e)
        if "403" in error_str or "API has not been used" in error_str or "Permission denied" in error_str:
            st.error("🚨 **Google Sheets Error:** Ensure the API is enabled and your bot is an Editor.")
        else:
            st.error(f"🚨 Save Error: {error_str}") 

def batch_save_new_articles(articles_list, clean_html_func):
    """Checks the database and bulk-saves any articles that aren't already cached."""
    try:
        my_sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet_link"]
        
        # Read the live sheet
        existing_data = conn.read(spreadsheet=my_sheet_url, worksheet="Sheet1", usecols=list(range(10)), ttl=0)
        
        # --- THE FIX ---
        # Force pandas to treat all blanks as text, not float64
        existing_data = existing_data.fillna("").astype(str)
        
        if 'article_id' not in existing_data.columns:
             existing_data['article_id'] = ""
             
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
                    "raw_rss_snippet": clean_html_func(art['rss_summary']),
                    "translated_text": "",
                    "ai_summary": ""
                })
        
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            updated_df = pd.concat([existing_data, new_df], ignore_index=True)
            conn.update(spreadsheet=my_sheet_url, worksheet="Sheet1", data=updated_df)
            
    except Exception as e:
        st.error(f"🚨 Batch Save Error: {e}")

def load_cached_articles(source_name, days_back):
    """Loads already cached articles from Google Sheets for the given source and days back."""
    try:
        my_sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet_link"]
        
        # Read the live sheet
        existing_data = conn.read(spreadsheet=my_sheet_url, worksheet="Sheet1", ttl=0)
        
        # Force pandas to treat all blanks as text, not float64
        existing_data = existing_data.fillna("").astype(str)
        
        if 'article_id' not in existing_data.columns:
            return []
            
        cutoff_date = datetime.now() - timedelta(days=days_back)
        cached_articles = []
        
        for _, row in existing_data.iterrows():
            row_source = row.get("source", "")
            if source_name != "All Feeds" and row_source != source_name:
                continue
                
            timestamp_str = row.get("timestamp", "")
            try:
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
                
            if dt < cutoff_date:
                continue
                
            # Reconstruct article dict
            art = {
                "link": row.get("article_id", ""),
                "source": row_source,
                "title": row.get("title", ""),
                "published": row.get("published_date", ""),
                "rss_summary": row.get("raw_rss_snippet", ""),
                "timestamp_dt": dt
            }
            
            # Load translation and analysis results if they exist
            translated_text = row.get("translated_text", "")
            ai_summary = row.get("ai_summary", "")
            
            if translated_text:
                art["translation_result"] = translated_text
            if ai_summary:
                art["analysis_result"] = ai_summary
                
            cached_articles.append(art)
            
        return cached_articles
    except Exception as e:
        st.error(f"🚨 Load Cache Error: {e}")
        return []