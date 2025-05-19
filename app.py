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
import traceback

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
RSS_FEED = os.getenv("RSS_FEED")

def rewrite_with_openai(full_text, title):
    try:
        prompt = (
            "Rewrite this article in AP news style with short, readable paragraphs (max 6 lines). "
            "Preserve any direct quotes or public statements. Do not use first-person language or mention the original source. "
            "Format your response strictly like this:\n\n"
            "---\nTITLE: <Rewritten Title>\n---\nCONTENT:\n<Rewritten Body>\n\n"
            f"Title: {title}\n\nContent:\n{full_text.strip()}"
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=900
        )

        result = response.choices[0].message.content.strip()

        # Defensive parsing
        if "TITLE:" not in result or "CONTENT:" not in result:
            print("[OpenAI format error] Missing TITLE or CONTENT marker.")
            print(result)
            return title, None

        title_match = re.search(r'TITLE:\s*(.*)', result)
        body_match = re.search(r'CONTENT:\s*(.*)', result, re.DOTALL)

        if not title_match or not body_match:
            print("[OpenAI parse error] Could not extract title or content.")
            print(result)
            return title, None

        return title_match.group(1).strip(), body_match.group(1).strip()

    except Exception as e:
        print(f"[OpenAI exception] {e}")
        print(traceback.format_exc())
        return title, None

def rewrite_article(entry):
    try:
        article = Article(entry.link)
        article.download()
        article.parse()
        text = article.text.strip()

        if len(text.split()) < 50:
            print(f"Skipped (too short): {entry.link}")
            return None

        new_title, new_summary = rewrite_with_openai(text, entry.title)
        if not new_summary:
            return None

        return {
            "title": new_title,
            "summary": new_summary + f'\n\n<div class="source-link"><a href="{entry.link}" target="_blank">Original Source</a></div>'
        }
    except Exception as e:
        print(f"Article parse failed: {e}")
        print(traceback.format_exc())
        return None

def get_feed_entries(offset=0, limit=5):
    feed = feedparser.parse(RSS_FEED)
    now = datetime.utcnow()
    window = now - timedelta(hours=48)
    valid_entries = []

    for entry in feed.entries:
        if hasattr(entry, 'published_parsed'):
            pub = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if pub < window:
                continue
        if "a timeline of" in entry.title.lower() or "tmz.com" in entry.link:
            continue
        valid_entries.append(entry)

    results = []
    count = 0
    for entry in valid_entries[offset:]:
        try:
            story = rewrite_article(entry)
            if story:
                results.append(story)
                count += 1
            if count >= limit:
                break
        except Exception as e:
            print(f"Error rewriting entry: {e}")
            print(traceback.format_exc())

    return results

@app.route('/')
def home():
    stories = get_feed_entries(offset=0, limit=5)
    return render_template('index.html', stories=stories, initial_count=5)

@app.route('/load_more', methods=['POST'])
def load_more():
    offset = int(request.form.get("offset", 0))
    stories = get_feed_entries(offset=offset, limit=5)
    return jsonify(stories)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == os.getenv("ADMIN_USERNAME") and request.form['password'] == os.getenv("ADMIN_PASSWORD"):
            session['logged_in'] = True
            return redirect('/')
        flash('Invalid login')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')