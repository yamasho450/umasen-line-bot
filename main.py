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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36"
}

# ==============================
# ウマセン：一覧・印
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

    races, seen = [], set()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        raw = a.get_text(strip=True)

        if "/expect/" not in href:
            continue

        slug = href.rstrip("/").split("/")[-1]
        if slug in ["expect", ""] or len(slug) < 5:
            continue

        if slug in seen:
            continue
        seen.add(slug)

        name = _short_race_title(raw) or slug
        races.append((name, slug, raw))
        if len(races) >= limit:
            break

    return races

def get_umasen_marks(slug):
    url = f"https://umasen.com/expect/{slug}/"
    res = requests.get(url, headers=UA_HEADERS, timeout=10)
    if res.status_code != 200:
        return None

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    out = []
    for row in soup.select("table tr"):
        mark = row.select_one(".uma_mark")
        ban = row.select_one(".expect_uma_ban")
        name = row.select_one(".expect_uma_name")
        if not (mark and ban and name):
            continue
        m = mark.get_text(strip=True)
        if m in MARKS:
            out.append(f"{m} {ban.get_text(strip=True)} {name.get_text(strip=True)}")
    return out if out else None


# ==============================
# netkeiba：race_list_sub から race_id（重複防止）
# ==============================
PLACE_TO_ID = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
    "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
}

_netkeiba_cache = {}  # (yyyymmdd, place_id) -> {raceno: race_id}

def get_netkeiba_raceid_by_raceno(yyyymmdd: str, place_id: str):
    key = (yyyymmdd, place_id)
    if key in _netkeiba_cache:
        return _netkeiba_cache[key]

    url = (f"https://race.netkeiba.com/top/race_list_sub.html"
           f"?kaisai_date={yyyymmdd}&kaisai_place={place_id}")
    res = requests.get(url, headers=UA_HEADERS, timeout=10)
    mapping = {}
    if res.status_code != 200:
        _netkeiba_cache[key] = mapping
        return mapping

    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    # ★ 重要：テキストが「◯R」だけのリンクのみ採用（重複防止）
    for a in soup.select("a[href*='race_id=']"):
        text = a.get_text(strip=True)
        m = re.match(r"^(\d{1,2})R$", text)
        if not m:
            continue
        raceno = int(m.group(1))

        href = a.get("href") or ""
        try:
            q = urlparse(href).query
            rid = parse_qs(q).get("race_id", [None])[0]
        except Exception:
            continue
        if not rid:
            continue

        if raceno in mapping:
            continue
        mapping[raceno] = rid

    _netkeiba_cache[key] = mapping
    return mapping

def build_odds_url(yyyymmdd: str, place: str, raceno: int):
    place_id = PLACE_TO_ID.get(place)
    if not place_id or not raceno:
        return None
    mp = get_netkeiba_raceid_by_raceno(yyyymmdd, place_id)
    rid = mp.get(raceno)
    if not rid:
        return None
    return f"https://race.netkeiba.com/odds/index.html?race_id={rid}"


# ==============================
# LINE 返信
# ==============================
def reply_messages(reply_token, messages):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"replyToken": reply_token, "messages": messages}, timeout=10)

def quick_reply_home():
    return {"items": [
        {"type": "action", "action": {"type": "message", "label": "今日のレース", "text": "今日のレース"}},
        {"type": "action", "action": {"type": "message", "label": "レース情報へ", "text": "レース情報へ"}},
        {"type": "action", "action": {"type": "message", "label": "使い方", "text": "使い方"}},
    ]}

def send_help(reply_token):
    reply_messages(reply_token, [{
        "type": "text",
        "text": "【使い方】\n・今日のレース → ウマセン一覧\n・レース情報へ → netkeibaオッズ\n・スラッグ直送もOK",
        "quickReply": quick_reply_home()
    }])

def build_marks_flex(races):
    btns = []
    for name, slug, _ in races:
        btns.append({"type": "button", "style": "primary", "height": "sm",
                     "action": {"type": "postback", "label": name[:20], "data": f"race={slug}", "displayText": slug}})
    return {"type": "flex", "altText": "今日のレース",
            "contents": {"type": "bubble",
                         "body": {"type": "box", "layout": "vertical", "spacing": "md",
                                  "contents": [
                                      {"type": "text", "text": "今日のレース", "weight": "bold", "size": "lg"},
                                      {"type": "separator", "margin": "md"},
                                      {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md",
                                       "contents": btns}
                                  ]}}}

def send_today_races(reply_token):
    races = get_today_races()
    if not races:
        reply_messages(reply_token, [{"type": "text", "text": "取得失敗", "quickReply": quick_reply_home()}])
        return
    reply_messages(reply_token, [build_marks_flex(races),
                                 {"type": "text", "text": "※タップで印", "quickReply": quick_reply_home()}])

def send_marks(reply_token, slug):
    marks = get_umasen_marks(slug)
    if not marks:
        reply_messages(reply_token, [{"type": "text", "text": f"取得失敗：{slug}", "quickReply": quick_reply_home()}])
    else:
        reply_messages(reply_token, [{"type": "text",
                                      "text": f"【ウマセン予想】\n{slug}\n\n" + "\n".join(marks),
                                      "quickReply": quick_reply_home()}])

def build_odds_flex(items):
    rows = [{"type": "button", "style": "secondary", "height": "sm",
             "action": {"type": "uri", "label": t[:20], "uri": u}} for t, u in items]
    return {"type": "flex", "altText": "オッズ",
            "contents": {"type": "bubble",
                         "body": {"type": "box", "layout": "vertical", "spacing": "md",
                                  "contents": [
                                      {"type": "text", "text": "レース情報（netkeiba）", "weight": "bold", "size": "lg"},
                                      {"type": "separator", "margin": "md"},
                                      {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md",
                                       "contents": rows}
                                  ]}}}

def send_race_info_links(reply_token):
    races = get_today_races()
    if not races:
        reply_messages(reply_token, [{"type": "text", "text": "取得失敗", "quickReply": quick_reply_home()}])
        return

    jst = ZoneInfo("Asia/Tokyo")
    now = datetime.now(jst)

    items = []
    for name, _, raw in races:
        md = _extract_md(raw)
        yyyymmdd = f"{now.year:04d}{md[0]:02d}{md[1]:02d}" if md else now.strftime("%Y%m%d")
        place, raceno = _extract_place_and_raceno(raw)
        if not place or not raceno:
            continue
        url = build_odds_url(yyyymmdd, place, raceno)
        if url:
            items.append((f"{place}{raceno}R {name}", url))

    if not items:
        reply_messages(reply_token, [{"type": "text", "text": "リンク生成失敗", "quickReply": quick_reply_home()}])
        return

    reply_messages(reply_token, [build_odds_flex(items[:10]),
                                 {"type": "text", "text": "※外部サイトへ移動します", "quickReply": quick_reply_home()}])


# ==============================
# Webhook
# ==============================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json(silent=True) or {}
    for e in body.get("events", []):
        rt = e.get("replyToken")
        if not rt:
            continue

        if e.get("type") == "postback":
            data = (e.get("postback", {}) or {}).get("data", "")
            if data.startswith("race="):
                send_marks(rt, data.split("=", 1)[1].strip())
            else:
                send_help(rt)
            continue

        if e.get("type") == "message":
            msg = (e.get("message", {}) or {})
            if msg.get("type") != "text":
                send_help(rt); continue
            text = (msg.get("text") or "").strip()
            if text in ["今日のレース", "本日のレース", "一覧"]:
                send_today_races(rt)
            elif text in ["レース情報へ", "レース情報", "オッズへ"]:
                send_race_info_links(rt)
            elif text in ["使い方", "help", "ヘルプ"]:
                send_help(rt)
            else:
                send_marks(rt, text)
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
