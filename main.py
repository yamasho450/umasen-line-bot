import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

LINE_TOKEN = (os.environ.get("LINE_TOKEN") or "").strip()
MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

# ==============================
# ウマセン: レース一覧・印取得
# ==============================
def _short_race_title(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("予想"):
        s = s[len("予想"):].strip()
    if "】" in s:
        s = s.split("】", 1)[1].strip()
    if "の" in s:
        s = s.split("の", 1)[0].strip()
    return s

def get_today_races(limit=10):
    url = "https://umasen.com/expect/"
    res = requests.get(url, timeout=10)
    if res.status_code != 200:
        return None

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    races = []
    seen = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        text = a.get_text(strip=True)

        if "/expect/" not in href:
            continue

        slug = href.rstrip("/").split("/")[-1]
        if slug in ["expect", ""] or len(slug) < 5:
            continue

        if slug in seen:
            continue
        seen.add(slug)

        name = _short_race_title(text) or slug
        races.append((name, slug))

        if len(races) >= limit:
            break

    return races

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
# LINE 送信ユーティリティ
# ==============================
def reply_messages(reply_token, messages):
    """messages: LINEのmessages配列（text / flex など）"""
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"replyToken": reply_token, "messages": messages}
    requests.post(url, headers=headers, json=payload, timeout=10)

def quick_reply_home():
    """画面下にボタンを出す（入力不要）"""
    return {
        "items": [
            {
                "type": "action",
                "action": {"type": "postback", "label": "今日のレース", "data": "action=today"}
            },
            {
                "type": "action",
                "action": {"type": "postback", "label": "使い方", "data": "action=help"}
            }
        ]
    }

def send_help(reply_token):
    text = (
        "【使い方】\n"
        "・下のボタン「今日のレース」を押す\n"
        "・表示されたレースをタップ → 印が返ります\n\n"
        "※直接スラッグ（例：tokyosinbunhai2026）を送ってもOK"
    )
    reply_messages(reply_token, [{
        "type": "text",
        "text": text,
        "quickReply": quick_reply_home()
    }])

def build_races_flex(races):
    """
    Flex Message：レースをボタン化してタップで postback（race=slug）
    LINEの制限に合わせて 10件程度まで推奨
    """
    buttons = []
    for name, slug in races:
        buttons.append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": name[:20],     # ラベル長すぎ対策
                "data": f"race={slug}",
                "displayText": slug     # トーク画面にも何を押したか出る（任意）
            }
        })

    flex = {
        "type": "flex",
        "altText": "ウマセン 今日のレース一覧",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "ウマセン 今日のレース", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": "タップで印を取得", "size": "sm", "color": "#666666"},
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "margin": "md",
                        "contents": buttons
                    }
                ]
            }
        }
    }
    return flex

def send_today_races(reply_token):
    races = get_today_races(limit=10)
    if not races:
        reply_messages(reply_token, [{
            "type": "text",
            "text": "レース一覧を取得できませんでした。",
            "quickReply": quick_reply_home()
        }])
        return

    flex = build_races_flex(races)
    reply_messages(reply_token, [
        flex,
        {
            "type": "text",
            "text": "※一覧に無い場合は、スラッグ（例：tokyosinbunhai2026）を直接送ってもOK",
            "quickReply": quick_reply_home()
        }
    ])

def send_marks(reply_token, slug):
    marks = get_umasen_marks(slug)
    if not marks:
        reply_messages(reply_token, [{
            "type": "text",
            "text": f"【ウマセン予想】\n{slug}\n\n※予想印が取得できませんでした",
            "quickReply": quick_reply_home()
        }])
    else:
        reply_messages(reply_token, [{
            "type": "text",
            "text": f"【ウマセン予想】\n{slug}\n\n" + "\n".join(marks),
            "quickReply": quick_reply_home()
        }])


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
        reply_token = event.get("replyToken")
        if not reply_token:
            continue

        etype = event.get("type")

        # 1) ボタン（postback）を押したとき
        if etype == "postback":
            data = (event.get("postback", {}) or {}).get("data", "")
            if data == "action=today":
                send_today_races(reply_token)
                continue
            if data == "action=help":
                send_help(reply_token)
                continue
            if data.startswith("race="):
                slug = data.split("=", 1)[1].strip()
                send_marks(reply_token, slug)
                continue

            # 不明postback
            send_help(reply_token)
            continue

        # 2) 文字入力（テキスト）でも操作できるように残す
        if etype == "message":
            message = event.get("message", {}) or {}
            if message.get("type") != "text":
                reply_messages(reply_token, [{
                    "type": "text",
                    "text": "テキストで送ってね（例：tokyosinbunhai2026）",
                    "quickReply": quick_reply_home()
                }])
                continue

            text = (message.get("text") or "").strip()

            if text in ["今日のレース", "本日のレース", "一覧"]:
                send_today_races(reply_token)
                continue
            if text in ["使い方", "help", "ヘルプ"]:
                send_help(reply_token)
                continue

            # それ以外は「スラッグ」として扱う
            send_marks(reply_token, text)
            continue

        # その他イベント
        send_help(reply_token)

    return "OK", 200


# ==============================
# Render 起動設定
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

