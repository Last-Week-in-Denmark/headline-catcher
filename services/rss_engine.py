import time
from datetime import datetime, timedelta
import feedparser
import streamlit as st

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
