import html
import math
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

WINDOW_START_HOUR = 0        # strictly 00:00 today, Nigerian time
WINDOW_END_HOUR = 4          # until 04:00 today
MATCH_SCORE = 0.35           # share of a cover headline's weighted words found in a story
MIN_SHARED_WORDS = 2         # a match needs at least this many shared words
MIN_MATCHED = 3              # fewer matches than this and nothing is sent
MAX_ITEMS = 10
FILL_WITH_LATEST = False     # True: pad with the newest stories when matches are few
SHOW_COVER_TEXT = False      # True: show the headline as read from the cover


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


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
    stories = []
    for item in (channel.findall("item") if channel is not None else []):
        title = clean(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        if title and url:
            stories.append({"title": title, "link": url,
                            "summary": clean(item.findtext("description")),
                            "published": parse_date(item.findtext("pubDate"))})
    return stories


def read_feed():
    stories, seen = [], set()
    for page in range(1, 4):  # pages 2 and 3 are a guess; the log shows if they work
        link = PUNCH_OFFICIAL_RSS if page == 1 else f"{PUNCH_OFFICIAL_RSS}?page={page}"
        try:
            batch = fetch_feed_page(link)
        except Exception as error:
            if page == 1:
                raise
            print(f"Feed page {page} not available ({error}).")
            break
        new = [s for s in batch if s["link"] not in seen]
        seen.update(s["link"] for s in new)
        stories += new
        print(f"Feed page {page}: {len(new)} new stories")
        if not new:
            break
    if not stories:
        raise ValueError("news feed returned no stories")
    return stories


def stories_in_window(feed):
    midnight = datetime.now(NIGERIA).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(hours=WINDOW_START_HOUR)
    end = midnight + timedelta(hours=WINDOW_END_HOUR)
    dates = [s["published"].astimezone(NIGERIA) for s in feed if s["published"]]
    if dates:
        print(f"Feed covers {min(dates):%d %b %H:%M} to {max(dates):%d %b %H:%M} "
              f"({len(feed)} stories). Window: {start:%d %b %H:%M} to {end:%d %b %H:%M}.")
    chosen = [s for s in feed
              if s["published"] and start <= s["published"].astimezone(NIGERIA) <= end]
    chosen.sort(key=lambda s: s["published"])
    print(f"Stories inside the window: {len(chosen)}")
    return chosen


def read_cover_blocks(image_bytes):
    """Reads the cover and groups lines of similar size, stacked in one column, into headlines."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        handle.write(image_bytes)
        path = handle.name
    try:
        result = RapidOCR()(path)
    finally:
        os.remove(path)

    if result is None or result.txts is None or result.boxes is None:
        return []

    lines = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        if score < 0.5 or not text.strip():
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        lines.append({"text": text.strip(), "x0": min(xs), "x1": max(xs),
                      "y0": min(ys), "y1": max(ys)})
    lines.sort(key=lambda l: (l["y0"], l["x0"]))

    blocks = []
    for line in lines:
        height = line["y1"] - line["y0"]
        for block in blocks:
            overlap = min(line["x1"], block["x1"]) - max(line["x0"], block["x0"])
            narrow = min(line["x1"] - line["x0"], block["x1"] - block["x0"])
            gap = line["y0"] - block["y1"]
            ratio = height / block["height"] if block["height"] else 0
            if (narrow > 0 and overlap / narrow >= 0.5
                    and -0.5 * height <= gap <= 0.8 * max(height, block["height"])
                    and 0.6 <= ratio <= 1.6):
                block["parts"].append(line["text"])
                block.update(x0=line["x0"], x1=line["x1"], y1=line["y1"], height=height)
                break
        else:
            blocks.append({"parts": [line["text"]], "x0": line["x0"], "x1": line["x1"],
                           "y1": line["y1"], "height": height})
    return [" ".join(b["parts"]) for b in blocks]


def words(text):
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4]


def make_weight(story_sets):
    """Rare words count more than common ones."""
    total = len(story_sets)
    frequency = {}
    for story_words in story_sets:
        for word in story_words:
            frequency[word] = frequency.get(word, 0) + 1
    return lambda word: math.log((total + 1) / (frequency.get(word, 0) + 1)) + 0.3


def block_score(block_words, story_words, weight):
    total = sum(weight(w) for w in block_words)
    if total == 0:
        return 0.0, 0
    found = shared = 0
    for word in block_words:
        if word in story_words or (len(word) >= 6 and process.extractOne(
                word, story_words, scorer=fuzz.ratio, score_cutoff=88)):
            found += weight(word)
            shared += 1
    return found / total, shared


def pair_blocks(blocks, candidates):
    story_sets = [set(words(c["title"] + " " + c["summary"])) for c in candidates]
    weight = make_weight(story_sets)

    options = []
    print("\nCover headlines and their best stories (score, shared words):")
    for b, block in enumerate(blocks):
        block_words = set(words(block))
        if len(block_words) < 3:
            continue
        scored = []
        for s, story_words in enumerate(story_sets):
            score, shared = block_score(block_words, story_words, weight)
            scored.append((score, shared, s))
            if score >= MATCH_SCORE and shared >= MIN_SHARED_WORDS:
                options.append((score, b, s))
        print(f"- {block[:80]}")
        for score, shared, s in sorted(scored, reverse=True)[:3]:
            print(f"    {score:.2f} ({shared}) {candidates[s]['title'][:70]}")

    used_blocks, used_stories, pairs = set(), set(), []
    for score, b, s in sorted(options, reverse=True):
        if b in used_blocks or s in used_stories:
            continue
        used_blocks.add(b)
        used_stories.add(s)
        pairs.append((b, s))
    pairs.sort()  # cover order: main headline first
    return [(blocks[b], candidates[s]) for b, s in pairs][:MAX_ITEMS]


def build_message(items):
    lines = [
        "*Today's Biggest Headlines*\n\n"
        "Here are some of the news reports that you shouldn't miss this morning:\n"
    ]
    for number, item in enumerate(items, 1):
        lines.append(f"*{number}. {item['title']}*\n🔗 {item['link']}")

    footer = (
        "\n------------------------------\n"
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
    if not DRY_RUN:
        missing = [n for n, v in [("GREEN_API_ID_INSTANCE", ID_INSTANCE),
                                  ("GREEN_API_TOKEN", API_TOKEN),
                                  ("PHONE_NUMBER", PHONE_NUMBERS)] if not v]
        if missing:
            print(f"Missing environment variables: {', '.join(missing)}")
            sys.exit(1)

    try:
        feed = read_feed()
        blocks = read_cover_blocks(fetch_cover())
        print(f"\nHeadline blocks read from the cover: {len(blocks)}")
        for block in blocks:
            print("  *", block[:100])

        candidates = stories_in_window(feed)
        if not candidates:
            raise ValueError("no feed stories inside the 00:00 to 04:00 window "
                             "(the feed may not reach back that far)")

        matches = pair_blocks(blocks, candidates)
        print(f"\nCover headlines matched to stories: {len(matches)}")
        items = [{"title": block if SHOW_COVER_TEXT else story["title"], "link": story["link"]}
                 for block, story in matches]

        if len(items) < MIN_MATCHED:
            if not FILL_WITH_LATEST:
                raise ValueError(f"only {len(items)} cover headlines matched; nothing sent")
            print("Too few matches: padding with the newest stories.")
            have = {i["link"] for i in items}
            for story in feed:
                if len(items) >= MAX_ITEMS:
                    break
                if story["link"] not in have:
                    items.append({"title": story["title"], "link": story["link"]})
    except Exception as error:
        print(f"NOT SENT: {error}")
        sys.exit(1)  # the team gets nothing; GitHub emails you instead

    message = build_message(items)
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