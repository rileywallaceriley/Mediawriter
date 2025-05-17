from flask import Flask, render_template, request
import feedparser

app = Flask(__name__)

FEEDS = {
    "HipHopDX": "https://hiphopdx.com/feed",
    "HotNewHipHop": "https://www.hotnewhiphop.com/rss.xml",
    "Rap-Up": "https://www.rap-up.com/feed/",
    "AllHipHop": "https://allhiphop.com/feed/"
}

@app.route('/')
def index():
    source = request.args.get("source")
    entries = []

    for name, url in FEEDS.items():
        if source and source != name:
            continue
        feed = feedparser.parse(url)
        for entry in feed.entries:
            entries.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.get("published", "No date"),
                "source": name
            })

    entries.sort(key=lambda x: x["published"], reverse=True)
    return render_template("index.html", entries=entries, sources=FEEDS.keys(), selected=source)
