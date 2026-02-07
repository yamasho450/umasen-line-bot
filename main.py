import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

LINE_TOKEN = (os.environ.get("LINE_TOKEN") or "").strip()
MARKS = ["◎", "〇", "▲", "△", "★", "☆"]

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

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

def _extract_md(raw: str):
    m = re.search(r"(\d{1,2})月(\d{1,2})日", raw or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))

def _extract_place_and_raceno(raw: str):
    # 例: "2月8日(日 ) 東京11R ..." / "2月7日(土) 京都11R ..."
    place = None
    for p in ["東京", "京都", "小倉", "中山", "阪神", "中京", "新潟", "福島", "函館", "札幌"]:
        if p in (raw or ""):
            place = p
            break
    m = re.search(r"(\d{1,2})R", raw or "")
    raceno = int(m.group(1)) if m else None
    return place, raceno

def get_today_races(limit=10):
    url = "https://umasen.com/expect/"
    res = requests.get(url, headers=UA_HEADERS, timeout=10)
    if res.status_code != 200:
        return None

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    races = []
    seen = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        raw_text = a.get_text(strip=True)

        if "/expect/" not in href:
            continue

        slug = href.rstrip("/").split("/")[-1]
        if slug in ["expect", ""] or len(slug) < 5:
            continue

        if slug in seen:
            continue
        seen.add(slug)

        name = _short_race_title(raw_text) or slug
        races.append((name, slug, raw_text))

        if len(races) >= limit:
            break

    return races

def get_umasen_marks(race_slug):
    url = f"https://umasen.com/expect/{race_slug}/"
    res = requests.get(url, headers=UA_HEADERS, timeout=10)
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
# netkeiba: race_list_sub から race_id を拾う（安定版）
# ==============================
PLACE_TO_ID = {
    "札幌": "01",
    "函館": "02",
    "福島": "03",
    "新潟": "04",
    "東京": "05",
    "中山": "06",
    "中京": "07",
    "京都": "08",
    "阪神": "09",
    "小倉": "10",
}

_netkeiba_cache = {}  # (yyyymmdd, place_id) -> {raceno:int: race_id}

def get_netkeiba_raceid_by_raceno(yyyymmdd: str, place_id: str):
    key = (yyyymmdd, place_id)
    if key in _netkeiba_cache:
        return _netkeiba_cache[key]

    # race_list_sub はHTMLにリンクが載ることが多く、requestsでも拾いやすい
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={yyyymmdd}&kaisai_place={place_id}"
    res = requests.get(url, headers=UA_HEADERS, timeout=10)
    if res.status_code != 200:
        _netkeiba_cache[key] = {}
        return _netkeiba_cache[key]

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    mapping = {}
    for a in soup.select("a[href*='race_id=']"):
        href = a.get("href") or ""
        text = a.get_text(strip=True)

        # テキスト側から "11R" を拾う
        m = re.search(r"(\d{1,2})R", text)
        if not m:
            continue
        raceno = int(m.group(1))

        # href から race_id を拾う
        try:
            q = urlparse(href).query
            rid = parse_qs(q).get("race_id", [None])[0]
        except Exception:
            rid = None
        if not rid:
            continue

        # 最初に見つかったものを採用
        mapping.setdefault(raceno, rid)

    _netkeiba_cache[key] = mapping
    return mapping

def build_odds_url(yyyymmdd: str, place: str, raceno: int):
    place_id = PLACE_TO_ID.get(place)
    if not place_id or not raceno:
        return None

    m = get_netkeiba_raceid_by_raceno(yyyymmdd, place_id)
    rid = m.get(raceno)
    if not rid:
        return None

    return f"https://race.netkeiba.com/odds/index.html?race_id={rid}"


# ==============================
# LINE返信ユーティリティ
# ==============================
def reply_messages(reply_token, messages):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"replyToken": reply_token, "messages": messages}
    requests.post(url, headers=headers, json=payload, timeout=10)

def quick_reply_home():
    return {
        "items": [
            {"type": "action", "action": {"type": "message", "label": "今日のレース", "text": "今日のレース"}},
            {"type": "action", "action": {"type": "message", "label": "レース情報へ", "text": "レース情報へ"}},
            {"type": "action", "action": {"type": "message", "label": "使い方", "text": "使い方"}},
        ]
    }

def send_help(reply_token):
    text = (
        "【使い方】\n"
        "・「今日のレース」→ ウマセン一覧（タップで印）\n"
        "・「レース情報へ」→ netkeibaのオッズリンク一覧（タップで外部へ）\n"
        "・スラッグ（例：tokyosinbunhai2026）を直接送ってもOK"
    )
    reply_messages(reply_token, [{
        "type": "text", "text": text, "quickReply": quick_reply_home()
    }])

def build_races_flex_for_marks(races):
    buttons = []
    for name, slug, _raw in races:
        buttons.append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "action": {"type": "postback", "label": name[:20], "data": f"race={slug}", "displayText": slug}
        })
    return {
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
                    {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md", "contents": buttons},
                ]
            }
        }
    }

def send_today_races(reply_token):
    races = get_today_races(limit=10)
    if not races:
        reply_messages(reply_token, [{
            "type": "text",
            "text": "レース一覧を取得できませんでした。",
            "quickReply": quick_reply_home()
        }])
        return
    flex = build_races_flex_for_marks(races)
    reply_messages(reply_token, [
        flex,
        {"type": "text", "text": "※一覧に無い場合は、スラッグ（例：tokyosinbunhai2026）を直接送ってもOK", "quickReply": quick_reply_home()}
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

def build_odds_links_flex(items):
    rows = []
    for title, url in items:
        rows.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {"type": "uri", "label": title[:20], "uri": url}
        })
    return {
        "type": "flex",
        "altText": "netkeiba オッズリンク",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": "レース情報（netkeiba）", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": "タップでオッズへ", "size": "sm", "color": "#666666"},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md", "contents": rows},
                ]
            }
        }
    }

def send_race_info_links(reply_token):
    races = get_today_races(limit=10)
    if not races:
        reply_messages(reply_token, [{
            "type": "text",
            "text": "レース一覧を取得できませんでした。",
            "quickReply": quick_reply_home()
        }])
        return

    jst = ZoneInfo("Asia/Tokyo")
    now = datetime.now(jst)

    items = []
    for name, _slug, raw in races:
        md = _extract_md(raw)
        if md:
            m, d = md
            yyyymmdd = f"{now.year:04d}{m:02d}{d:02d}"
        else:
            yyyymmdd = now.strftime("%Y%m%d")

        place, raceno = _extract_place_and_raceno(raw)
        if not place or not raceno:
            continue

        odds_url = build_odds_url(yyyymmdd, place, raceno)
        if odds_url:
            items.append((f"{place}{raceno}R {name}", odds_url))

    if not items:
        reply_messages(reply_token, [{
            "type": "text",
            "text": "netkeiba側のリンク生成に失敗しました（開催日/競馬場/レース番号の一致が取れない可能性）。",
            "quickReply": quick_reply_home()
        }])
        return

    flex = build_odds_links_flex(items[:10])
    reply_messages(reply_token, [
        flex,
        {"type": "text", "text": "※リンクが無いレースはnetkeiba側で未掲載/取得失敗の可能性があります。", "quickReply": quick_reply_home()}
    ])


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

        if etype == "postback":
            data = (event.get("postback", {}) or {}).get("data", "")
            if data == "action=today":
                send_today_races(reply_token); continue
            if data == "action=help":
                send_help(reply_token); continue
            if data.startswith("race="):
                slug = data.split("=", 1)[1].strip()
                send_marks(reply_token, slug); continue
            send_help(reply_token); continue

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
                send_today_races(reply_token); continue
            if text in ["レース情報へ", "レース情報", "オッズへ"]:
                send_race_info_links(reply_token); continue
            if text in ["使い方", "help", "ヘルプ"]:
                send_help(reply_token); continue

            send_marks(reply_token, text)
            continue

        send_help(reply_token)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
