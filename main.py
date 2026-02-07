import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

LINE_TOKEN = (os.environ.get("LINE_TOKEN") or "").strip()
MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

# ==============================
# 今日のレース一覧を取得（見やすく整形）
# ==============================
def _short_race_title(raw: str) -> str:
    """
    例:
    '予想【2026年】豊前Sの指数予想2月7日(土)...' -> '豊前S'
    '予想【2026年】東京新聞杯(G3)のデータ・指数競馬予想...' -> '東京新聞杯(G3)'
    """
    s = (raw or "").strip()

    # 先頭の「予想」を消す
    if s.startswith("予想"):
        s = s[len("予想"):].strip()

    # '【2026年】' などの [] 部分を消す（最初の '】' まで）
    if "】" in s:
        s = s.split("】", 1)[1].strip()

    # 'のデータ...' 'の指数予想...' など後ろを削る（最初の 'の' で切る）
    if "の" in s:
        s = s.split("の", 1)[0].strip()

    return s


def get_today_races(limit=12):
    url = "https://umasen.com/expect/"
    res = requests.get(url, timeout=10)

    if res.status_code != 200:
        return None

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    races = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        text = a.get_text(strip=True)

        if "/expect/" not in href:
            continue

        # 例: https://umasen.com/expect/tokyosinbunhai2026/
        # 例: /expect/tokyosinbunhai2026/
        slug = href.rstrip("/").split("/")[-1]
        if slug in ["expect", ""] or len(slug) < 5:
            continue

        if slug in seen:
            continue
        seen.add(slug)

        short = _short_race_title(text)
        if not short:
            short = slug

        races.append((short, slug))

        if len(races) >= limit:
            break

    return races


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
            results.append(
                f"{m} {ban.get_text(strip=True)} {name.get_text(strip=True)}"
            )

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
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post(url, headers=headers, json=payload, timeout=10)


# ==============================
# Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json(silent=True) or {}
    events = body.get("events", [])

    # Verify用（eventsがないPOSTでも200で返す）
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

        if not reply_token:
            continue

        # 今日のレース一覧
        if text in ["今日のレース", "本日のレース", "今日の一覧", "一覧"]:
            races = get_today_races()
            if not races:
                reply_line(reply_token, "レース一覧を取得できませんでした。")
                continue

            msg = "【ウマセン 今日のレース一覧】\n\n"
            for name, slug in races:
                msg += f"・【2026年】{name} → {slug}\n"
            msg += "\n※英数字（→の右側）をそのまま送ると予想印が見られます"

            reply_line(reply_token, msg)
            continue

        # 通常：レース印取得（入力はスラッグ想定）
        marks = get_umasen_marks(text)

        if not marks:
            reply_line(reply_token, f"【ウマセン予想】\n{text}\n\n※予想印が取得できませんでした")
        else:
            reply_line(reply_token, f"【ウマセン予想】\n{text}\n\n" + "\n".join(marks))

    return "OK", 200


# ==============================
# Render起動設定
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
