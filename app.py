from flask import Flask, render_template, request, redirect, session, flash
from dotenv import load_dotenv
import os
import feedparser
import requests
from newspaper import Article
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import re

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Load environment variables
RSS_FEED = os.getenv("RSS_FEED")
WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def rewrite_article(url, title):
    try:
        if "a timeline of" in title.lower():
            return None

        article = Article(url)
        article.download()
        article.parse()

        text = article.text.strip()
        if not text:
            return "Failed to extract article text."

        soup = BeautifulSoup(text, "html.parser")
        cleaned_text = soup.get_text()
        sentences = re.split(r'(?<=[.!?])\s+', cleaned_text.strip())

        paragraphs = []
        para = []
        word_count = 0
        max_words = 300

        for sentence in sentences:
            if "..." in sentence:
                continue  # remove awkward original transitions
            words_in_sentence = len(sentence.split())
            word_count += words_in_sentence
            para.append(sentence)

            if len(' '.join(para)) > 500 or len(para) >= 4:
                paragraphs.append(' '.join(para))
                para = []

            if word_count >= max_words:
                break

        if para and word_count < max_words:
            paragraphs.append(' '.join(para))

        formatted = '\n\n'.join(paragraphs)
        return formatted

    except Exception as e:
        return f"Failed to fetch article: {e}"

@app.route('/')
def home():
    feed = feedparser.parse(RSS_FEED)
    stories = []

    now = datetime.utcnow()
    cutoff = now - timedelta(days=1)
    tmz_count = 0

    for entry in feed.entries:
        if hasattr(entry, 'published_parsed'):
            published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if published < cutoff:
                continue

        if "a timeline of" in entry.title.lower():
            continue

        if "tmz.com" in entry.link:
            tmz_count += 1
            if tmz_count > 2:
                continue

        rewritten = rewrite_article(entry.link, entry.title)
        if not rewritten or "Failed" in rewritten:
            continue

        # Attribution for TMZ or likely interviews
        add_citation = False
        if "tmz.com" in entry.link:
            add_citation = True
        elif any(word in rewritten.lower() for word in ["interview", "said", "spoke with", "told", "discussed"]):
            add_citation = True

        if add_citation:
            domain_match = re.findall(r"https?://(?:www\.)?([^/]+)", entry.link)
            if domain_match:
                domain = domain_match[0].replace("www.", "")
                rewritten += f"\n\n*As reported by <a href=\"{entry.link}\">{domain}</a>.*"

        stories.append({
            'title': entry.title,
            'summary': rewritten,
            'link': f'/article?url={entry.link}&title={entry.title}'
        })

    return render_template('index.html', stories=stories)

@app.route('/article')
def article():
    url = request.args.get('url')
    title = request.args.get('title')
    rewritten = rewrite_article(url, title)

    # Internal-only citation for TMZ or interview content
    add_citation = False
    if "tmz.com" in url:
        add_citation = True
    elif any(word in rewritten.lower() for word in ["interview", "said", "spoke with", "told", "discussed"]):
        add_citation = True

    if add_citation:
        domain_match = re.findall(r"https?://(?:www\.)?([^/]+)", url)
        if domain_match:
            rewritten += f"\n\n*As reported by <a href=\"{url}\">{domain_match[0]}</a>.*"

    return render_template('article.html', title=title, content=rewritten)

@app.route('/publish', methods=['POST'])
def publish():
    if not session.get('logged_in'):
        return redirect('/login')

    title = request.form.get('title')
    content = request.form.get('content')

    wp_api = f"{WP_URL}/wp-json/wp/v2/posts"
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    data = {'title': title, 'content': content, 'status': 'draft'}

    res = requests.post(wp_api, auth=auth, json=data)
    if res.status_code == 201:
        return "Draft pushed to WordPress!"
    else:
        return f"Failed: {res.status_code} — {res.text}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        pw = request.form['password']
        if user == ADMIN_USERNAME and pw == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/')
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')