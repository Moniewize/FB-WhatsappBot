import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from rapidfuzz import fuzz, process
from rapidocr import RapidOCR

from cover import fetch_cover

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
DRY_RUN = os.getenv("DRY_RUN") == "1"  # prints the message instead of sending it

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
MATCH_THRESHOLD = 0.80  # share of a title's distinctive letters found on the cover
MAX_ITEMS = 10


def parse_date(text):
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def read_feed():
    response = requests.get(PUNCH_OFFICIAL_RSS, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    items = []
    for item in (channel.findall("item") if channel is not None else []):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            items.append({"title": title, "link": link,
                          "published": parse_date(item.findtext("pubDate"))})
    if not items:
        raise ValueError("news feed returned no items")
    return items


def read_cover_text(image_bytes):
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        handle.write(image_bytes)
        path = handle.name
    try:
        result = RapidOCR()(path)
    finally:
        os.remove(path)
    return list(result.txts) if result is not None and result.txts else []


def words_of(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def coverage(title, cover_words):
    """Share of the title's distinctive letters whose words appear on the cover."""
    words = [w for w in words_of(title) if len(w) >= 4]
    if len(words) < 3:
        return 0.0
    total = matched = 0
    for word in words:
        total += len(word)
        if word in cover_words or process.extractOne(
                word, cover_words, scorer=fuzz.ratio, score_cutoff=85):
            matched += len(word)
    return matched / total


def choose_items(feed, cover_pieces):
    cover_words = set(words_of(" ".join(cover_pieces)))
    scored = sorted(((coverage(i["title"], cover_words), n, i) for n, i in enumerate(feed)),
                    key=lambda row: (-row[0], row[1]))

    print("\nBest-scoring feed stories (cover match, 1.00 = every word found):")
    for score, _, item in scored[:15]:
        print(f"  {score:.2f}  {item['title'][:90]}")

    chosen = [i for score, _, i in scored if score >= MATCH_THRESHOLD][:MAX_ITEMS]
    print(f"\nStories matched to the cover: {len(chosen)}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for item in feed:  # fill remaining slots with the newest stories
        if len(chosen) >= MAX_ITEMS:
            break
        if item not in chosen and (item["published"] is None or item["published"] > cutoff):
            chosen.append(item)
    return chosen[:MAX_ITEMS]


def build_message(items):
    lines = ["Today's Biggest Headlines\n\n"
             "Here are some of the news reports that you shouldn't miss this morning:\n"]
    for number, item in enumerate(items, 1):
        lines.append(f"{number}. {item['title']} === {item['link']}")
    footer = ("\n\n \n"
              "*Source:* The Punch\n"
              "*Brought by*: RAC-FUTO Editorial Team")
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
    if not DRY_RUN:
        missing = [n for n, v in [("GREEN_API_ID_INSTANCE", ID_INSTANCE),
                                  ("GREEN_API_TOKEN", API_TOKEN),
                                  ("PHONE_NUMBER", PHONE_NUMBERS)] if not v]
        if missing:
            print(f"Missing environment variables: {', '.join(missing)}")
            sys.exit(1)

    problems = []
    try:
        feed = read_feed()
        dates = [i["published"] for i in feed if i["published"]]
        print(f"Feed stories: {len(feed)}. Oldest: {min(dates) if dates else 'unknown'}. "
              f"Newest: {max(dates) if dates else 'unknown'}.")
    except Exception as error:
        problems.append(f"headlines: {error}")
        feed = None

    if feed is None:
        message = ("Daily Update Notice\n\nThere was a technical problem fetching "
                   "this morning's headlines. We are looking into it.")
    else:
        cover_pieces = []
        try:
            cover_pieces = read_cover_text(fetch_cover())
            print(f"Text pieces read from the cover: {len(cover_pieces)}")
            print("First 60:", cover_pieces[:60])
        except Exception as error:
            print(f"Cover could not be read ({error}). Using the newest stories only.")
        message = build_message(choose_items(feed, cover_pieces))

    print("\n===== MESSAGE =====\n" + message + "\n===================")

    if DRY_RUN:
        print("Dry run: nothing was sent.")
    else:
        problems += deliver(message)

    if problems:
        print("PROBLEMS:", *problems, sep="\n- ")
        sys.exit(1)


if __name__ == "__main__":
    main()