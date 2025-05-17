from flask import Flask, render_template, request
import feedparser
from newspaper import Article
from difflib import SequenceMatcher

app = Flask(__name__)

RSS_FEED_URL = "https://rss.app/feeds/_wiboBlEdvNBsV9vh.xml"

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

    feed = feedparser.parse(RSS_FEED_URL)
    for item in feed.entries:
        title = item.get("title", "").strip()
        link = item.get("link", "").strip()
        if not title or not link:
            continue
        if any(similar(title, s["title"]) > 0.9 for s in seen):
            continue
        summary = fetch_article_text(link)
        if summary:
            seen.append({"title": title})
            entries.append({
                "title": title,
                "link": link,
                "source": "Media Feed",
                "published": item.get("published", "No date"),
                "summary": summary
            })

    entries.sort(key=lambda x: x["published"], reverse=True)
    return render_template("index.html", entries=entries)