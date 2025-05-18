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
import openai

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Environment Variables
openai.api_key = os.getenv("OPENAI_API_KEY")
RSS_FEED = os.getenv("RSS_FEED")
WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

def call_openai_rewrite(text):
    try:
        prompt = (
            "Rewrite the following news article in third-person AP style. "
            "Make it no more than 300 words. Break into readable short paragraphs. "
            "Do not use first-person language. Do not reference the original article or source.\n\n"
            f"Article:\n{text.strip()}"
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=750,
            messages=[{"role": "user", "content": prompt}]
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"Failed to rewrite: {e}"

def rewrite_article(url, title):
    try:
        if "a timeline of" in title.lower():
            return None

        article = Article(url)
        article.download()
        article.parse()

        raw_text = article.text.strip()
        if not raw_text or len(raw_text.split()) < 100:
            return None

        return call_openai_rewrite(raw_text)

    except Exception as e:
        return f"Failed to fetch article: {e}"

def to_title_case(text):
    return re.sub(r"[A-Za-z]+('[A-Za-z]+)?",
                  lambda match: match.group(0)[0].upper() + match.group(0)[1:].lower(),
                  text)

@app.route('/')
def home():
    feed = feedparser.parse(RSS_FEED)
    stories = []
    seen_titles = set()
    now = datetime.utcnow()
    max_window = now - timedelta(hours=48)

    entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)

    for entry in entries:
        if len(stories) >= 10:
            break

        if hasattr(entry, 'published_parsed'):
            published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if published < max_window:
                continue

        if "a timeline of" in entry.title.lower() or "tmz.com" in entry.link:
            continue

        rewritten = rewrite_article(entry.link, entry.title)
        if not rewritten or "Failed" in rewritten:
            continue

        clean_title = to_title_case(entry.title.strip())
        slug = clean_title.lower()

        if slug in seen_titles:
            continue
        seen_titles.add(slug)

        source_link = f'<div class="source-link"><a href="{entry.link}" target="_blank">Original Source</a></div>'
        rewritten_with_source = rewritten + "\n\n" + source_link

        stories.append({
            'title': clean_title,
            'summary': rewritten_with_source,
            'link': f'/article?url={entry.link}&title={clean_title}'
        })

    return render_template('index.html', stories=stories)

@app.route('/article')
def article():
    url = request.args.get('url')
    title = request.args.get('title')
    rewritten = rewrite_article(url, title)

    add_citation = False
    if any(word in rewritten.lower() for word in ["interview", "said", "spoke with", "told", "discussed"]):
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

    # Strip internal-only lines
    content = re.sub(r'<div class="source-link">.*?</div>', '', content, flags=re.DOTALL)
    content = re.sub(r'\*As reported by.*?\*', '', content)

    wp_api = f"{WP_URL}/wp-json/wp/v2/posts"
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    data = {'title': title, 'content': content.strip(), 'status': 'draft'}

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