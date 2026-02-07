from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# Render の環境変数から取得
LINE_TOKEN = os.environ.get("LINE_TOKEN")

TARGET_MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

# ==============================
# ウマセン予想印を取得（←ここはほぼそのまま）
# ==============================

def get_umasen_marks(race_slug):
    url = f"https://umasen.com/expect/{race_slug}/"
    res = requests.get(url)

    if res.status_code != 200:
        return None

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    results = []

    for row in soup.select("table tr"):
        mark = row.select_one(".uma_mark")
        ban = row.select_one(".expect_uma_ban")
        name = row.select_one(".expect_uma_name")

        if not (mark and ban and name):
            continue

        mark_text = mark.get_text(strip=True)
        if mark_text not in TARGET_MARKS:
            continue

        ban_text = ban.get_text(strip=True)
        name_text = name.get_text(strip=True)

        results.append(f"{mark_text} {ban_text} {name_text}")

    return results if results else None

# ==============================
# LINEに返信
# ==============================

def reply_line(reply_token, message):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": message}
        ]
    }
    requests.post(url, headers=headers, json=payload)

# ==============================
# Webhook
# ==============================

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    for event in body.get("events", []):
        if event["type"] != "message":
            continue

        reply_token = event["replyToken"]
        race_slug = event["message"]["text"].strip()

        marks = get_umasen_marks(race_slug)

        if not marks:
            reply_line(
                reply_token,
                f"【ウマセン予想】\n{race_slug}\n\n※予想印が取得できませんでした"
            )
        else:
            reply_line(
                reply_token,
                f"【ウマセン予想】\n{race_slug}\n\n" + "\n".join(marks)
            )

    return "OK"

if __name__ == "__main__":
    app.run()
