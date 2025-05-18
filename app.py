from flask import Flask, render_template, request, redirect, session, flash
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

def rewrite_with_openai(full_text, title):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": f"""Rewrite this news article in AP style.
Rewrite the title as a punchy, professional headline.
Return your output in the following format:

---
TITLE: <Rewritten Title>
---
CONTENT:
<Rewritten body here, under 300 words, in short readable paragraphs.>

Do not reference the original article or use first-person language.

Title: {title}
Body:
{full_text.strip()}
"""
                }
            ],
            temperature=0.7,
            max_tokens=800
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

    return render_template('index.html', stories=stories)

@app.route('/article')
def article():
    url = request.args.get('url')
    title = request.args.get('title')
    new_title, rewritten = rewrite_article_from_url(url, title)

    if not rewritten:
        rewritten = "Failed to load article."

    add_citation = False
    if any(word in rewritten.lower() for word in ["interview", "said", "spoke with", "told", "discussed"]):
        add_citation = True

    if add_citation:
        domain_match = re.findall(r"https?://(?:www\.)?([^/]+)", url)
        if domain_match:
            rewritten += f"\n\n*As reported by <a href=\"{url}\">{domain_match[0]}</a>.*"

    return render_template('article.html', title=new_title, content=rewritten)

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