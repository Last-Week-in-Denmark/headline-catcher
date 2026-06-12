import re
from newspaper import Article

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
