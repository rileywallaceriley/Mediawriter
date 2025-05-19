from flask import Flask, render_template, request, redirect, session, flash, jsonify
from dotenv import load_dotenv
import os
import feedparser
import requests
from newspaper import Article
from datetime import datetime, timedelta
import time
import re
import openai

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
RSS_FEED = os.getenv("RSS_FEED")
WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# Rewrites article using OpenAI and returns title + rewritten body
def rewrite_with_openai(full_text, title):
    try:
        prompt = (
            "Rewrite the following news article in AP style. "
            "Create a punchy, professional headline that accurately reflects the story. "
            "Return your output in the following format:\n\n"
            "---\n"
            "TITLE: <Rewritten Title>\n"
            "---\n"
            "CONTENT:\n<Rewritten body here, under 300 words, in short readable paragraphs.>\n\n"
            "Include relevant quotes if present. Do not use first-person language or reference the original article."
            f"\n\nTitle: {title}\n\nBody:\n{full_text.strip()}"
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800,
            timeout=15
        )

        content = response.choices[0].message.content.strip()
        title_match = re.search(r'TITLE:\s*(.*)', content)
        body_match = re.search(r'CONTENT:\s*(.*)', content, re.DOTALL)
        new_title = title_match.group(1).strip() if title_match else title
        new_body = body_match.group(1).strip() if body_match else full_text
        return new_title, new_body

    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return title, f"Failed to rewrite: {e}"

def rewrite_article_from_url(url, original_title):
    try:
        article = Article(url)
        article.download()
        article.parse()
        raw_text = article.text.strip()

        if not raw_text or len(raw_text.split()) < 50:
            print(f"[SKIPPED - Too short] {url}")
            return original_title, None

        return rewrite_with_openai(raw_text, original_title)

    except Exception as e:
        print(f"[ERROR scraping] {url} — {e}")
        return original_title, None

# Fetches and rewrites N entries starting from offset
def get_rewritten_stories(offset=0, limit=5):
    feed = feedparser.parse(RSS_FEED)
    stories = []
    seen_titles = set()
    now = datetime.utcnow()
    max_window = now - timedelta(hours=48)

    entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)

    count = 0
    for i, entry in enumerate(entries[offset:], start=offset):
        if count >= limit:
            break

        if hasattr(entry, 'published_parsed'):
            published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if published < max_window:
                continue

        if "a timeline of" in entry.title.lower() or "tmz.com" in entry.link:
            continue

        original_title = entry.title.strip()
        slug = original_title.lower()

        if slug in seen_titles:
            continue
        seen_titles.add(slug)

        new_title, rewritten = rewrite_article_from_url(entry.link, original_title)
        if not rewritten:
            continue

        source_link = f'<div class="source-link"><a href="{entry.link}" target="_blank">Original Source</a></div>'
        rewritten_with_source = rewritten + "\n\n" + source_link

        stories.append({
            'title': new_title,
            'summary': rewritten_with_source,
            'link': f'/article?url={entry.link}&title={new_title}'
        })
        count += 1

    return stories

@app.route('/')
def home():
    stories = get_rewritten_stories(offset=0, limit=5)
    return render_template('index.html', stories=stories, initial_count=5)

@app.route('/load_more', methods=['POST'])
def load_more():
    offset = int(request.form.get('offset', 0))
    stories = get_rewritten_stories(offset=offset, limit=5)
    return jsonify(stories)

@app.route('/publish', methods=['POST'])
def publish():
    if not session.get('logged_in'):
        return redirect('/login')

    title = request.form.get('title')
    content = request.form.get('content')

    content = re.sub(r'<div class="source-link">.*?</div>', '', content, flags=re.DOTALL)
    content = re.sub(r'\*As reported by.*?\*', '', content)

    wp_api = f"{WP_URL}/wp-json/wp/v2/posts"
    auth = (WP_USERNAME, WP_APP_PASSWORD)
    data = {'title': title, 'content': content.strip(), 'status': 'draft'}

    res = requests.post(wp_api, auth=auth, json=data)
    return "Draft pushed to WordPress!" if res.status_code == 201 else f"Failed: {res.status_code} — {res.text}"

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