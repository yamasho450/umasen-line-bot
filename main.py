import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_TOKEN")
MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

def get_umasen_marks(race_name):
    url = f"https://umasen.com/expect/{race_name}/"
    res = requests.get(url, timeout=10)
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
        m = mark.get_text(strip=True)
        if m in MARKS:
            results.append(f"{m} {ban.get_text(strip=True)} {name.get_text(strip=True)}")
    return results if results else None

def reply_line(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    print("LINE reply status:", r.status_code, "body:", r.text)  # ★ 返信の結果ログ

@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json(silent=True) or {}
    print("INCOMING BODY:", body)  # ★ 受信イベントをログ

    events = body.get("events", [])
    if not events:
        return "OK", 200

    for event in events:
        print("EVENT:", event)  # ★ 1イベントずつログ
        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        reply_token = event.get("replyToken")
        text = (message.get("text") or "").strip()

        # 念のため：tokenやtextがなければ通知
        if not reply_token:
            print("NO replyToken")
            continue
        if not text:
            reply_line(reply_token, "レース名（例：tokyosinbunhai2026）を送ってね。")
            continue

        marks = get_umasen_marks(text)
        if not marks:
            reply_line(reply_token, f"【ウマセン予想】\n{text}\n\n※予想印が取得できませんでした")
        else:
            reply_line(reply_token, f"【ウマセン予想】\n{text}\n\n" + "\n".join(marks))

    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
