from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
import feedparser
import time
from newspaper import Article
from datetime import datetime, timedelta
import re
import traceback
from openai import OpenAI

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60
)

RSS_FEED = os.getenv("RSS_FEED")

@app.route('/')
def home():
    feed = feedparser.parse(RSS_FEED)
    stories = []

    now = datetime.utcnow()
    window = now - timedelta(hours=48)

    for entry in feed.entries:
        if hasattr(entry, 'published_parsed'):
            pub = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            if pub < window:
                continue
        if "a timeline of" in entry.title.lower() or "tmz.com" in entry.link:
            continue
        stories.append({
            'title': entry.title,
            'link': entry.link
        })
        if len(stories) >= 10:
            break

    return render_template('index.html', stories=stories)

@app.route('/rewrite', methods=['POST'])
def rewrite():
    try:
        url = request.json.get('url')
        title = request.json.get('title')

        article = Article(url)
        article.download()
        article.parse()
        full_text = article.text.strip()

        if len(full_text.split()) < 50:
            return jsonify({'error': 'Article too short'}), 400

        prompt = (
            "Rewrite this article in AP news style. Expand to 250–300 words if possible, using short, readable paragraphs (no longer than 6 lines each). "
            "Preserve any direct quotes or public statements. Do not use first-person language or mention the original source. "
            "Do not speculate or add new information. Focus on clear who/what/when/where/why facts from the original. "
            "Format your response strictly like this:\n\n"
            "---\nTITLE: <Rewritten Title>\n---\nCONTENT:\n<Rewritten Body>\n\n"
            f"Title: {title}\n\nContent:\n{full_text}"
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000
        )

        result = response.choices[0].message.content.strip()
        title_match = re.search(r'TITLE:\s*(.*)', result)
        body_match = re.search(r'CONTENT:\s*(.*)', result, re.DOTALL)

        if not title_match or not body_match:
            return jsonify({'error': 'Malformed rewrite'}), 500

        return jsonify({
            'new_title': title_match.group(1).strip(),
            'new_body': body_match.group(1).strip()
        })

    except Exception as e:
        print("[Rewrite error]", e)
        print(traceback.format_exc())
        return jsonify({'error': 'Server error'}), 500