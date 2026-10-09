import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from rapidfuzz import fuzz, process
from rapidocr import RapidOCR

from cover import fetch_cover

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
DRY_RUN = os.getenv("DRY_RUN") == "1"  # prints the message instead of sending it

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

MATCH_THRESHOLD = 0.80    # strong cover match
PARTIAL_THRESHOLD = 0.50  # partial cover match (counts only inside the midnight batch)
MAX_ITEMS = 10
TITLE_LIMIT = 90
WINDOW_HOURS_BEFORE_MIDNIGHT = 0  # batch starts at 12:00 the midnight 
WINDOW_HOURS_AFTER_MIDNIGHT = 4   # batch ends at 04:00 today


def parse_date(text):
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_feed_page(link):
    response = requests.get(link, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    items = []
    for item in (channel.findall("item") if channel is not None else []):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if title and url:
            items.append({"title": title, "link": url,
                          "published": parse_date(item.findtext("pubDate"))})
    return items


def read_feed():
    items, seen = [], set()
    for page in range(1, 4):  # pages 2 and 3 are a guess; the log shows if they work
        link = PUNCH_OFFICIAL_RSS if page == 1 else f"{PUNCH_OFFICIAL_RSS}?page={page}"
        try:
            batch = fetch_feed_page(link)
        except Exception as error:
            if page == 1:
                raise
            print(f"Feed page {page} not available ({error}).")
            break
        new = [i for i in batch if i["link"] not in seen]
        seen.update(i["link"] for i in new)
        items += new
        print(f"Feed page {page}: {len(new)} new stories")
        if not new:
            break
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


def in_midnight_batch(item):
    published = item["published"]
    if not published:
        return False
    midnight = datetime.now(NIGERIA).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(hours=WINDOW_HOURS_BEFORE_MIDNIGHT)
    end = midnight + timedelta(hours=WINDOW_HOURS_AFTER_MIDNIGHT)
    return start <= published.astimezone(NIGERIA) <= end


def when(item):
    published = item["published"]
    return published.astimezone(NIGERIA).strftime("%d %b %H:%M") if published else "unknown"


def choose_items(feed, cover_pieces):
    cover_words = set(words_of(" ".join(cover_pieces)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    rows = []
    for position, item in enumerate(feed):
        rows.append({
            "item": item,
            "position": position,
            "score": coverage(item["title"], cover_words) if cover_words else 0.0,
            "batch": in_midnight_batch(item),
        })

    def tier(row):
        if row["score"] >= MATCH_THRESHOLD:
            return 1
        if row["batch"] and row["score"] >= PARTIAL_THRESHOLD:
            return 2
        if row["batch"]:
            return 3
        published = row["item"]["published"]
        return 4 if (published is None or published > cutoff) else 9

    in_batch = [r for r in rows if r["batch"]]
    print(f"\nStories in the midnight batch: {len(in_batch)} of {len(rows)}")
    print("Best cover matches (score | published Nigerian time | in batch | title):")
    for row in sorted(rows, key=lambda r: -r["score"])[:15]:
        print(f"  {row['score']:.2f} | {when(row['item'])} | "
              f"{'yes' if row['batch'] else 'no '} | {row['item']['title'][:80]}")

    ranked = sorted((r for r in rows if tier(r) < 9),
                    key=lambda r: (tier(r), -r["score"], r["position"]))[:MAX_ITEMS]
    print("\nChosen stories (tier | score | published | title):")
    for row in ranked:
        print(f"  {tier(row)} | {row['score']:.2f} | {when(row['item'])} | {row['item']['title'][:80]}")
    return [row["item"] for row in ranked]


def shorten_title(title):
    title = re.sub(r"\s*[-|–]\s*Punch.*$", "", title.strip(), flags=re.I)
    if len(title) <= TITLE_LIMIT:
        return title
    cut = title[:TITLE_LIMIT].rsplit(" ", 1)[0].rstrip(",;:-– ")
    return cut + "…"


def tidy_links(items):
    """Shorten each link with is.gd. If it fails, keep the original link."""
    links = []
    shortener_works = True
    for item in items:
        original = re.sub(r"[?&]utm_[^&]+", "", item["link"])
        short = original
        if shortener_works:
            try:
                response = requests.get("https://is.gd/create.php",
                                        params={"format": "simple", "url": original},
                                        headers=HEADERS, timeout=15)
                text = response.text.strip()
                if response.ok and text.startswith("http"):
                    short = text
                else:
                    print(f"Link shortener refused ({response.status_code}): {text[:80]}")
                    shortener_works = False
            except Exception as error:
                print(f"Link shortener failed: {error}")
                shortener_works = False
            time.sleep(1)
        links.append(short)
    return links


def build_message(items, links):
    today = datetime.now(NIGERIA).strftime("%A, %d %B %Y")
    blocks = [f"*Today's Biggest Headlines*\n_{today}_\n\nStories you shouldn't miss this morning:"]
    for number, (item, link) in enumerate(zip(items, links), 1):
        blocks.append(f"*{number}.* {shorten_title(item['title'])}\n{link}")
    blocks.append("_Source: The Punch · Brought by RAC-FUTO Editorial Team_")
    return "\n\n".join(blocks)


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
        print(f"Feed stories: {len(feed)}. Oldest: "
              f"{min(dates).astimezone(NIGERIA) if dates else 'unknown'}. "
              f"Newest: {max(dates).astimezone(NIGERIA) if dates else 'unknown'}.")
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
            print(f"Cover could not be read ({error}). Relying on the midnight batch.")
        chosen = choose_items(feed, cover_pieces)
        message = build_message(chosen, tidy_links(chosen))

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