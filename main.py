import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_TOKEN")

# ==============================
# ウマセン予想印を取得
# ==============================
def get_umasen_marks(race_name):
    url = f"https://umasen.com/expect/{race_name}/"
    res = requests.get(url, timeout=10)
    res.encoding = res.apparent_encoding

    if res.status_code != 200:
        return None

    soup = BeautifulSoup(res.text, "html.parser")
    results = []

    for row in soup.select("table tr"):
        mark = row.select_one(".uma_mark")
        ban = row.select_one(".expect_uma_ban")
        name = row.select_one(".expect_uma_name")

        if mark and ban and name:
            m = mark.get_text(strip=True)
            if m in ["◎", "〇", "▲", "△", "★", "☆"]:
                results.append(
                    f"{m} {ban.get_text(strip=True)} {name.get_text(strip=True)}"
                )

    return results


# ==============================
# LINE Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.json

    try:
        event = body["events"][0]
        reply_token = event["replyToken"]
        user_text = event["message"]["text"].strip()
    except Exception:
        abort(400)

    marks = get_umasen_marks(user_text)

    if not marks:
        reply_text = f"【ウマセン予想】\n{user_text}\n\n※予想印が取得できませんでした"
    else:
        reply_text = f"【ウマセン予想】\n{user_text}\n\n" + "\n".join(marks)

    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": reply_text}
        ]
    }

    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers=headers,
        json=payload
    )

    return "OK", 200


if __name__ == "__main__":
    app.run()
