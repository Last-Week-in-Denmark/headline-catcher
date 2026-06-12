import time
from datetime import datetime, timedelta

from streamlit_app import get_cached_feed_entries


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
