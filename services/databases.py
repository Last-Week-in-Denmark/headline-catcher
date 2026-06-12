import streamlit as st
import pandas as pd
from datetime import datetime
from utils import clean_html
from gsheetsdb import connect

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
