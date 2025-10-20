from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
import feedparser
import time
from newspaper import Article
from datetime import datetime, timedelta
import re
import traceback
import requests
from openai import OpenAI

# --- Setup ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=60
)

RSS_FEED = os.getenv("RSS_FEED")

# --- WordPress Configuration ---
WORDPRESS_URL = "https://aboveaveragehiphop.com/wp-json/wp/v2/posts"
WORDPRESS_USER = "EX-P"
WORDPRESS_APP_PASS = "hRW4 sfle QV9l wq4w NzJH 6nqR"


# --- Helper Function ---
def safe_rewrite_call(prompt):
    for attempt in range(2):  # Try once, then retry
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1000
            )
            result = response.choices[0].message.content.strip()

            if "TITLE:" in result and "CONTENT:" in result:
                return result

            print(f"[Attempt {attempt+1}] Malformed response:\n{result}")

        except Exception as e:
            print(f"[Attempt {attempt+1}] Rewrite call error: {e}")
            continue

    return None


# --- Routes ---

@app.route('/')
def home():
    feed = feedparser.parse(RSS_FEED)
    stories = []

    now = datetime.utcnow()
    window = now - timedelta(hours=72)

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
        if len(stories) >= 20:
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
            return jsonify({'error': 'Article too short to rewrite'}), 400

        prompt = (
            "Rewrite the article below using AP News style. Expand to 250 words minimum (ideally 300) using short paragraphs (no longer than 6 lines each). "
            "Preserve direct quotes or public statements if present. Avoid first-person language and don’t reference the original source. "
            "Only use facts from the article — no speculation or added context. \n\n"
            "FORMAT STRICTLY LIKE THIS:\n\n"
            "TITLE: [Your rewritten headline]\n\n"
            "CONTENT:\n[Your rewritten article in full paragraphs]\n\n"
            f"TITLE: {title}\n\nCONTENT:\n{full_text}"
        )

        result = safe_rewrite_call(prompt)
        if not result:
            return jsonify({'error': 'Malformed response — please retry'}), 500

        title_match = re.search(r'TITLE:\s*(.*)', result)
        body_match = re.search(r'CONTENT:\s*(.*)', result, re.DOTALL)

        if not title_match or not body_match:
            return jsonify({'error': 'Failed to parse AI response'}), 500

        return jsonify({
            'new_title': title_match.group(1).strip(),
            'new_body': body_match.group(1).strip()
        })

    except Exception as e:
        print("[Rewrite error]", e)
        print(traceback.format_exc())
        return jsonify({'error': 'Server error — try again later'}), 500


# --- NEW: Publish to WordPress ---
@app.route('/publish', methods=['POST'])
def publish_to_wordpress():
    try:
        title = request.form.get("title")
        content = request.form.get("content")

        if not title or not content:
            return render_template("article.html", title="Error", content="Missing title or content")

        payload = {
            "title": title,
            "content": content,
            "status": "draft"
        }

        response = requests.post(
            WORDPRESS_URL,
            json=payload,
            auth=(WORDPRESS_USER, WORDPRESS_APP_PASS)
        )

        if response.status_code == 201:
            post = response.json()
            return render_template(
                "article.html",
                title="Draft Posted!",
                content=f"✅ Draft created successfully on WordPress.<br><br><a href='{post['link']}' target='_blank'>View Draft</a>"
            )
        else:
            return render_template(
                "article.html",
                title="Error Posting to WordPress",
                content=f"❌ Failed to create draft:<br><br>{response.text}"
            )

    except Exception as e:
        print("[Publish error]", e)
        return render_template(
            "article.html",
            title="Server Error",
            content=f"An error occurred while posting to WordPress:<br>{e}"
        )


if __name__ == "__main__":
    app.run(debug=True)