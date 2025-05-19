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
        prompt = (
            "Rewrite this article in AP style with short, readable paragraphs (max 6 lines),"
            " and preserve any official quotes, public statements, or notable claims."
            " Do not use first-person language. Return in this format:\n\n"
            "---\nTITLE: <new title>\n---\nCONTENT:\n<rewritten content>\n"
            f"\n\nTitle: {title}\n\nBody:\n{full_text.strip()}"
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=900
        )
        output = response.choices[0].message.content
        title_match = re.search(r'TITLE:\s*(.*)', output)
        content_match = re.search(r'CONTENT:\s*(.*)', output, re.DOTALL)
        rewritten_title = title_match.group(1).strip() if title_match else title
        rewritten_body = content_match.group(1).strip() if content_match else full_text
        return rewritten_title, rewritten_body
    except Exception as e:
        return title, f"Rewrite failed: {e}"

def rewrite_article_from_url(url, original_title):
    try:
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        if len(text.split()) < 50:
            return original_title, None
        return rewrite_with_openai(text, original_title)
    except Exception:
        return original_title, None

def get_rewritten_stories(page=1, per_page=5):
    feed = feedparser.parse(RSS_FEED)
    entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
    now = datetime.utcnow()
    max_window = now - timedelta(hours=48)
    seen = set()
    stories = []
    offset = (page - 1) * per_page

    count = 0
    for i, entry in enumerate(entries):
        if count >= offset + per_page:
            break
        if hasattr(entry, 'published_parsed'):
            published = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if published < max_window:
                continue
        if "a timeline of" in entry.title.lower():
            continue
        if entry.title in seen:
            continue
        seen.add(entry.title)

        if count >= offset:
            new_title, rewritten = rewrite_article_from_url(entry.link, entry.title)
            if not rewritten:
                continue
            rewritten += f'\n\n<div class="source-link"><a href="{entry.link}" target="_blank">Original Source</a></div>'
            stories.append({
                "title": new_title,
                "summary": rewritten
            })
        count += 1

    has_next = (count > offset + per_page)
    return stories, has_next

@app.route('/')
def home():
    page = int(request.args.get("page", 1))
    stories, has_next = get_rewritten_stories(page=page)
    return render_template('index.html', stories=stories, page=page, has_next=has_next)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USERNAME and request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')