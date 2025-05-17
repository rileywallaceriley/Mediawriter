from flask import Flask, render_template, request
import feedparser
from newspaper import Article
from difflib import SequenceMatcher

app = Flask(__name__)

# Your custom RSS.app feeds — consistent and clean
FEEDS = {
    "HipHopDX": "https://rss.app/feeds/eCqHOU",
    "HotNewHipHop": "https://rss.app/feeds/djGy2mHPHkT91LkJ",
    "AllHipHop": "https://rss.app/feeds/w8ZsiGlEvR3bZ1Yp",
    "Rap-Up": "https://rss.app/feeds/HxkB0zOj3RM1fXLh"
}

def fetch_article_text(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text[:500] + "..." if len(article.text) > 500 else article.text
    except Exception as e:
        print(f"Failed to parse {url}: {e}")
        return ""

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

@app.route("/")
def index():
    entries = []
    seen = []

    for name, url in FEEDS.items():
        feed = feedparser.parse(url)
        for item in feed.entries:
            title = item.get("title", "").strip()
            link = item.get("link", "").strip()
            if not title or not link:
                continue
            # Deduplicate based on similar titles
            if any(similar(title, s["title"]) > 0.9 for s in seen):
                continue
            summary = fetch_article_text(link)
            if summary:
                seen.append({"title": title})
                entries.append({
                    "title": title,
                    "link": link,
                    "source": name,
                    "published": item.get("published", "No date"),
                    "summary": summary
                })

    entries.sort(key=lambda x: x["published"], reverse=True)
    return render_template("index.html", entries=entries)