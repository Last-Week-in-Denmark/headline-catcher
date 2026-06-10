import streamlit as st
import feedparser
from newspaper import Article
from openai import OpenAI

# ==========================================
# 1. TEAM PASSWORD PROTECTION LOGIC
# ==========================================
def check_password():
    """Returns `True` if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 Team News Digest Login")
        st.write("Please enter the team password to access the summarizer.")
        pwd = st.text_input("Password:", type="password")
        
        if pwd == st.secrets["TEAM_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        elif pwd:
            st.error("Incorrect password. Please try again.")
        return False
    return True

# Halt execution if the user is not logged in
if not check_password():
    st.stop()

# ==========================================
# 2. CORE FUNCTIONS
# ==========================================
# Initialize OpenAI client using Streamlit Secrets
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

@st.cache_data(show_spinner=False)
def fetch_rss_links(feed_url):
    """Fetches and parses the RSS feed."""
    feed = feedparser.parse(feed_url)
    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", "No date provided")
        })
    return articles

def extract_article_text(url):
    """Downloads and extracts clean text from an article URL."""
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        return ""

def generate_summary(article_text):
    """Passes the article text to OpenAI for summarization."""
    prompt = f"""
    You are an expert news editor. Analyze the following news article text.
    Provide a highly engaging, rewritten headline, followed by a 3-bullet point summary of the key facts.
    
    Article Text:
    {article_text}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**Error generating summary:** {e}"

# ==========================================
# 3. STREAMLIT USER INTERFACE
# ==========================================
st.title("📰 AI News Digest & Summarizer")
st.markdown("Fetch the latest articles from an RSS feed and generate AI summaries instantly.")

# User inputs
rss_url = st.text_input("Enter RSS Feed URL:", "https://feeds.feedburner.com/TechCrunch/")
num_articles = st.slider("Number of articles to summarize:", min_value=1, max_value=10, value=3)

if st.button("Fetch and Summarize", type="primary"):
    with st.spinner("Fetching RSS feed..."):
        articles = fetch_rss_links(rss_url)[:num_articles]
        
    if not articles:
        st.error("Could not find any articles.")
