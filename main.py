import html
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

FEED_TIMES_ARE_LOCAL = True  # the feed prints Nigerian clock time but labels it +0000
PRIORITY_START_HOUR = 0      # first choice: 00:00 ...
PRIORITY_END_HOUR = 1        # ... to 01:00 today
SECOND_END_HOUR = 4          # second choice: 01:00 to 04:00 today
MAX_ITEMS = 10


def parse_date(text):
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except Exception:
        return None
    if FEED_TIMES_ARE_LOCAL:
        return moment.replace(tzinfo=NIGERIA)  # keep the clock time as printed
    return moment.astimezone(NIGERIA)


def read_feed():
    response = requests.get(PUNCH_OFFICIAL_RSS, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    stories = []
    for item in (channel.findall("item") if channel is not None else []):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if title and link:
            stories.append({"title": title, "link": link,
                            "raw_date": item.findtext("pubDate"),
                            "published": parse_date(item.findtext("pubDate"))})
    if not stories:
        raise ValueError("news feed returned no stories")
    return stories


def pick_stories(feed):
    now = datetime.now(NIGERIA)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_start = midnight + timedelta(hours=PRIORITY_START_HOUR)
    first_end = midnight + timedelta(hours=PRIORITY_END_HOUR)
    second_end = midnight + timedelta(hours=SECOND_END_HOUR)

    dated = [s for s in feed if s["published"]]
    print(f"Nigerian time now: {now:%d %b %H:%M}. Raw dates, first and last: "
          f"{feed[0]['raw_date']} | {feed[-1]['raw_date']}")
    if dated:
        print(f"Feed covers {min(s['published'] for s in dated):%d %b %H:%M} to "
              f"{max(s['published'] for s in dated):%d %b %H:%M} ({len(feed)} stories).")

    tier1 = sorted((s for s in dated if first_start <= s["published"] < first_end),
                   key=lambda s: s["published"])
    tier2 = sorted((s for s in dated if first_end <= s["published"] <= second_end),
                   key=lambda s: s["published"])
    cutoff = now - timedelta(hours=24)
    tier3 = sorted((s for s in dated if s["published"] > cutoff),
                   key=lambda s: s["published"], reverse=True)

    print(f"Priority hour ({first_start:%H:%M} to {first_end:%H:%M}): {len(tier1)} stories. "
          f"Then until {second_end:%H:%M}: {len(tier2)} stories.")
    if not tier1:
        print("No stories from the priority hour: the feed may not reach back that far.")

    chosen, seen = [], set()
    for tier in (tier1, tier2, tier3):
        for story in tier:
            if story["link"] not in seen and len(chosen) < MAX_ITEMS:
                seen.add(story["link"])
                chosen.append(story)

    print("Chosen stories:")
    for story in chosen:
        print(f"  {story['published']:%H:%M} | {story['title'][:80]}")
    if not chosen:
        raise ValueError("no usable stories in the feed")
    return chosen


def build_message(stories):
    lines = [
        "*Today's Biggest Headlines*\n\n"
        "Here are some of the news reports that you shouldn't miss this morning:\n"
    ]
    for number, story in enumerate(stories, 1):
        lines.append(f"*{number}. {story['title']}*\n🔗 {story['link']}")

    footer = (
        "\n\n"
        "*Source:* The Punch\n"
        " *Brought by:* RAC-FUTO Editorial Team"
    )
    return "\n\n".join(lines) + footer


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
    missing = [name for name, value in [
        ("GREEN_API_ID_INSTANCE", ID_INSTANCE),
        ("GREEN_API_TOKEN", API_TOKEN),
        ("PHONE_NUMBER", PHONE_NUMBERS),
    ] if not value]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    problems = []
    try:
        message = build_message(pick_stories(read_feed()))
    except Exception as error:
        problems.append(f"headlines: {error}")
        message = ("Daily Update Notice\n\nThere was a technical problem fetching "
                   "this morning's headlines. We are looking into it.")

    problems += deliver(message)

    if problems:
        print("PROBLEMS:", *problems, sep="\n- ")
        sys.exit(1)


if __name__ == "__main__":
    main()