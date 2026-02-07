import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

LINE_TOKEN = (os.environ.get("LINE_TOKEN") or "").strip()
MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

# ==============================
# 今日のレース一覧を取得
# ==============================
def get_today_races():
    url = "https://umasen.com/expect/"
    res = requests.get(url, timeout=10)

    if res.status_code != 200:
        return None

    soup = BeautifulSoup(res.text, "html.parser")
    races = []

    # expectページのリンクを拾う
    for a in soup.select("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)

        if "/expect/" in href and text:
            slug = href.rstrip("/").split("/")[-1]

            # 変なリンク除外
            if slug in ["expect", ""] or len(slug) < 5:
                continue

            races.append((text, slug))

    # 重複除去
    unique = []
    seen = set()
    for name, slug in races:
        if slug not in seen:
            seen.add(slug)
            unique.append((name, slug))

    return unique[:10]  # 多すぎ防止


# ==============================
# ウマセン予想印を取得
# ==============================
def get_umasen_marks(race_slug):
    url = f"https://umasen.com/expect/{race_slug}/"
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


# ==============================
# LINE返信
# ==============================
def reply_line(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post(url, headers=headers, json=payload, timeout=10)


# ==============================
# Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json(silent=True) or {}
    events = body.get("events", [])

    if not events:
        return "OK", 200

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        reply_token = event.get("replyToken")
        text = (message.get("text") or "").strip()

        # 今日のレース一覧
        if text in ["今日のレース", "本日のレース"]:
            races = get_today_races()

            if not races:
                reply_line(reply_token, "レース一覧を取得できませんでした。")
                continue

            msg = "【ウマセン 今日のレース一覧】\n\n"
            for name, slug in races:
                msg += f"・{name} → {slug}\n"

            msg += "\n※英数字をそのまま送ると予想印が見られます"
            reply_line(reply_token, msg)
            continue

        # 通常：レース印取得
        marks = get_umasen_marks(text)

        if not marks:
            reply_line(
                reply_token,
                f"【ウマセン予想】\n{text}\n\n※予想印が取得できませんでした"
            )
        else:
            reply_line(
                reply_token,
                f"【ウマセン予想】\n{text}\n\n" + "\n".join(marks)
            )

    return "OK", 200


# ==============================
# Render起動設定
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
