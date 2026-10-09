import base64
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from cover import fetch_cover

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-flash-latest"
DRY_RUN = os.getenv("DRY_RUN") == "1"  # prints the message instead of sending it

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

FEED_TIMES_ARE_LOCAL = True  # the feed prints Nigerian clock time but labels it +0000
WINDOW_START_HOUR = 0        # strictly 00:00 today, Nigerian time
WINDOW_END_HOUR = 4          # until 04:00 today
USE_WEBSITE_TITLE = False    # False: show each headline as printed on the cover
MIN_MATCHED = 3              # fewer matches than this and nothing is sent
MAX_ITEMS = 12


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_date(text):
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except Exception:
        return None
    if FEED_TIMES_ARE_LOCAL:
        return moment.replace(tzinfo=NIGERIA)  # keep the clock time as printed
    return moment


def fetch_feed_page(link):
    response = requests.get(link, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    stories = []
    for item in (channel.findall("item") if channel is not None else []):
        title = clean(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        if title and url:
            stories.append({"title": title, "link": url,
                            "summary": clean(item.findtext("description")),
                            "raw_date": item.findtext("pubDate"),
                            "published": parse_date(item.findtext("pubDate"))})
    return stories


def read_feed():
    stories = fetch_feed_page(PUNCH_OFFICIAL_RSS)
    if not stories:
        raise ValueError("news feed returned no stories")
    print(f"Feed stories: {len(stories)}")
    print(f"Raw dates in the feed (first, last): {stories[0]['raw_date']} | {stories[-1]['raw_date']}")
    return stories


def stories_in_window(feed):
    now = datetime.now(NIGERIA)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(hours=WINDOW_START_HOUR)
    end = midnight + timedelta(hours=WINDOW_END_HOUR)
    dates = [s["published"] for s in feed if s["published"]]
    print(f"Nigerian time now: {now:%d %b %H:%M}. Feed covers {min(dates):%d %b %H:%M} "
          f"to {max(dates):%d %b %H:%M}. Window: {start:%d %b %H:%M} to {end:%d %b %H:%M}.")
    chosen = [s for s in feed if s["published"] and start <= s["published"] <= end]
    chosen.sort(key=lambda s: s["published"])
    print(f"Stories inside the window: {len(chosen)}")
    return chosen


def gemini_models_hint():
    try:
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=30)
        names = [m["name"] for m in response.json().get("models", []) if "flash" in m["name"]]
        print("Models containing 'flash' that your key can see:", names)
        print("Set one as the GEMINI_MODEL value (without the 'models/' part).")
    except Exception as error:
        print(f"Could not list models: {error}")


def ask_gemini(image_bytes, candidates):
    listing = "\n".join(
        f"{n} | {c['published']:%H:%M} | {c['title']} | {c['summary'][:220]}"
        for n, c in enumerate(candidates, 1)
    )
    prompt = (
        "This image is today's front page of The Punch, a Nigerian newspaper.\n"
        "Step 1: list every news headline printed on the cover, in order of importance: "
        "the main headline first, then the sub-headlines under it, then the side stories "
        "and the strip at the top. Skip the newspaper name, advertisements, photo captions "
        "and page-number labels. Write each headline exactly as printed, as one line.\n"
        "Step 2: below are online stories, one per line as: number | time | title | summary. "
        "For each cover headline, give the number of the story that reports the same news "
        "event, or null if no story clearly does. Do not guess: a story on a related topic "
        "but a different event is null.\n"
        "Reply with JSON only: a list of objects with the keys \"headline\" (text), "
        "\"story\" (number or null) and \"reason\" (a few words).\n\n"
        f"Stories:\n{listing}"
    )
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inlineData": {"mimeType": "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode()}},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    link = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    for attempt in range(3):
        response = requests.post(link, headers={"x-goog-api-key": GEMINI_API_KEY},
                                 json=body, timeout=120)
        if response.status_code in (429, 500, 503) and attempt < 2:
            print(f"Gemini busy ({response.status_code}). Waiting 30 seconds.")
            time.sleep(30)
            continue
        break

    if not response.ok:
        print(f"Gemini refused: {response.status_code} {response.text[:400]}")
        gemini_models_hint()
        response.raise_for_status()

    parts = response.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if isinstance(result, dict):
        result = next((v for v in result.values() if isinstance(v, list)), [])
    return result


def pair_up(result, candidates):
    pairs, used = [], set()
    print("\nCover headlines and the story each was matched to:")
    for row in result[:MAX_ITEMS]:
        headline = clean(str(row.get("headline", "")))
        number = row.get("story")
        story = None
        if isinstance(number, int) and 1 <= number <= len(candidates):
            story = candidates[number - 1]
        link = story["link"] if story and number not in used else None
        if story:
            used.add(number)
        shown = f"story {number}: {story['title'][:60]}" if story else "no match"
        print(f"  {headline[:70]} -> {shown} [{row.get('reason', '')}]")
        if headline:
            title = story["title"] if (story and USE_WEBSITE_TITLE) else headline
            pairs.append((title, link))
    return pairs


def build_message(pairs):
    blocks = [
        "*Today's Biggest Headlines*\n\n"
        "Here are some of the news reports that you shouldn't miss this morning:\n"
    ]
    for number, (title, link) in enumerate(pairs, 1):
        blocks.append(f"*{number}. {title}*" + (f"\n🔗 {link}" if link else ""))
    footer = (
        "\n------------------------------\n"
        "*Source:* The Punch\n"
        " *Brought by:* RAC-FUTO Editorial Team"
    )
    return "\n\n".join(blocks) + footer


def green_post(endpoint, **kwargs):
    link = f"https://api.green-api.com/waInstance{ID_INSTANCE}/{endpoint}/{API_TOKEN}"
    response = requests.post(link, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def chat_identifier(raw):
    cleaned = raw.strip().replace("+", "").replace(" ", "")
    return cleaned if ("@g.us" in cleaned or "@c.us" in cleaned) else f"{cleaned}@c.us"


def deliver(message):
    failures = []
    for raw in (p for p in PHONE_NUMBERS.split(",") if p.strip()):
        chat = chat_identifier(raw)
        try:
            green_post("sendMessage", json={"chatId": chat, "message": message})
            print(f"Headlines delivered to {chat}")
        except Exception as error:
            failures.append(f"{chat}: {error}")
            print(f"FAILED for {chat}: {error}")
        time.sleep(3)
    return failures


def main():
    needed = [("GEMINI_API_KEY", GEMINI_API_KEY)]
    if not DRY_RUN:
        needed += [("GREEN_API_ID_INSTANCE", ID_INSTANCE), ("GREEN_API_TOKEN", API_TOKEN),
                   ("PHONE_NUMBER", PHONE_NUMBERS)]
    missing = [name for name, value in needed if not value]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    try:
        feed = read_feed()
        candidates = stories_in_window(feed)
        if not candidates:
            raise ValueError("no feed stories inside the 00:00 to 04:00 window "
                             "(the feed may not reach back that far)")
        cover = fetch_cover()
        print(f"Cover downloaded ({len(cover)} bytes). Asking Gemini ({GEMINI_MODEL})...")
        pairs = pair_up(ask_gemini(cover, candidates), candidates)
        matched = sum(1 for _, link in pairs if link)
        print(f"Cover headlines: {len(pairs)}. With a matching story: {matched}.")
        if matched < MIN_MATCHED:
            raise ValueError(f"only {matched} cover headlines matched a story; nothing sent")
    except Exception as error:
        print(f"NOT SENT: {error}")
        sys.exit(1)  # the team gets nothing; GitHub emails you instead

    message = build_message(pairs)
    print("\n===== MESSAGE =====\n" + message + "\n===================")

    if DRY_RUN:
        print("Dry run: nothing was sent.")
        return
    problems = deliver(message)
    if problems:
        print("PROBLEMS:", *problems, sep="\n- ")
        sys.exit(1)


if __name__ == "__main__":
    main()