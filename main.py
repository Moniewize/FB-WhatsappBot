import html
import io
import math
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

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

FEED_TIMES_ARE_LOCAL = True  # the feed prints Nigerian clock time but labels it +0000
PRIORITY_START_HOUR = 0      # first choice: 00:00 ...
PRIORITY_END_HOUR = 1        # ... to 01:00 today
SECOND_END_HOUR = 4          # second choice: 01:00 to 04:00 today
MAX_ITEMS = 10
LINK_MARK = "🔗"             # put "===" here if you prefer

MIN_SCORE = 3.5              # how strong a cover match must be
MIN_SHARED_WORDS = 2         # distinctive words a story must share with the cover
TITLE_BOOST = 1.5            # headline words count more than summary words
IGNORE_BOTTOM_SHARE = 0.20   # skip the bottom 20% of the cover (adverts)
SMALL_TEXT_CUTOFF = 0.6      # skip text smaller than 60% of the typical size (captions)

NOISE_WORDS = {
    "punch", "punchng", "newspaper", "newspapers", "widely", "read", "most", "year",
    "mobilepunch", "punchnewspapers", "page", "pages", "friday", "saturday", "sunday",
    "monday", "tuesday", "wednesday", "thursday", "october", "november", "december",
    "this", "that", "with", "from", "will", "have", "said", "says", "after", "over",
    "into", "about", "their", "them", "they", "been", "were", "what", "when", "where",
    "which", "also", "more", "than", "here", "there", "your", "just", "would", "could",
    "should", "still", "only", "some", "other",
}
TOKEN = re.compile(r"[a-z]{4,}|\d[\d,]*\d")


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
    return moment.astimezone(NIGERIA)


def read_feed():
    response = requests.get(PUNCH_OFFICIAL_RSS, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    stories = []
    for item in (channel.findall("item") if channel is not None else []):
        title = clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if title and link:
            stories.append({"title": title, "link": link,
                            "guid": (item.findtext("guid") or "").strip(),
                            "summary": clean(item.findtext("description")),
                            "raw_date": item.findtext("pubDate"),
                            "published": parse_date(item.findtext("pubDate"))})
    if not stories:
        raise ValueError("news feed returned no stories")
    return stories


def words_in(text):
    found = []
    for token in TOKEN.findall(text.lower()):
        token = token.replace(",", "")
        if token not in NOISE_WORDS and (token.isalpha() or len(token) >= 3):
            found.append(token)
    return found


def read_cover_lines():
    """Reads the cover and returns its headline-sized text lines, top to bottom."""
    from PIL import Image
    from rapidocr import RapidOCR
    from cover import fetch_cover

    image_bytes = fetch_cover()
    page_height = Image.open(io.BytesIO(image_bytes)).height
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        handle.write(image_bytes)
        path = handle.name
    try:
        result = RapidOCR()(path)
    finally:
        os.remove(path)
    if result is None or result.txts is None or result.boxes is None:
        return []

    found = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = text.strip()
        if score < 0.5 or not text:
            continue
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        found.append({"y": min(ys), "x": min(xs), "h": max(ys) - min(ys), "text": text})
    if not found:
        return []

    median = sorted(f["h"] for f in found)[len(found) // 2]
    keep = [f for f in found
            if f["h"] >= SMALL_TEXT_CUTOFF * median
            and f["y"] <= page_height * (1 - IGNORE_BOTTOM_SHARE)]
    keep.sort(key=lambda f: (f["y"], f["x"]))
    print(f"Cover text pieces read: {len(found)}. Kept {len(keep)} "
          f"(small print and the bottom {int(IGNORE_BOTTOM_SHARE * 100)}% ignored).")
    return [f["text"] for f in keep]


def match_cover(stories, cover_lines, bonus):
    """Finds the stories that report what is printed on the cover."""
    from rapidfuzz import fuzz, process

    cover_words, first_line = set(), {}
    for index, line in enumerate(cover_lines):
        for word in words_in(line):
            cover_words.add(word)
            first_line.setdefault(word, index)

    pool = []
    for story in stories:
        title_words = set(words_in(story["title"]))
        pool.append((title_words, title_words | set(words_in(story["summary"]))))

    frequency = {}
    for _, all_words in pool:
        for word in all_words:
            frequency[word] = frequency.get(word, 0) + 1
    total = len(stories)

    def weight(word, in_title):
        value = math.log((total + 1) / (frequency.get(word, 0) + 1))
        return value * (TITLE_BOOST if in_title else 1.0)

    rows = []
    for story, (title_words, all_words) in zip(stories, pool):
        matched = {}
        for word in all_words:
            hit = word in cover_words
            if not hit and len(word) >= 6:
                hit = bool(process.extractOne(word, cover_words, scorer=fuzz.ratio,
                                              score_cutoff=88))
            if hit:
                matched[word] = weight(word, word in title_words)
        rows.append({"story": story, "matched": matched, "score": sum(matched.values())})

    print("\nBest cover matches (score | shared words | story):")
    for row in sorted(rows, key=lambda r: -r["score"])[:15]:
        top = sorted(row["matched"], key=row["matched"].get, reverse=True)[:5]
        print(f"  {row['score']:5.1f} | {', '.join(top)} | {row['story']['title'][:70]}")

    accepted, claimed = [], set()
    for row in sorted(rows, key=lambda r: -(r["score"] + bonus(r["story"]))):
        fresh = {w: v for w, v in row["matched"].items() if w not in claimed}
        if len(fresh) >= MIN_SHARED_WORDS and sum(fresh.values()) >= MIN_SCORE:
            accepted.append(row)
            claimed.update(row["matched"])
        if len(accepted) >= MAX_ITEMS:
            break

    def position(row):
        best = max(row["matched"], key=row["matched"].get)
        return first_line.get(best, len(cover_lines))

    accepted.sort(key=position)
    print("\nStories matched to the cover (cover order):")
    for row in accepted:
        line = position(row)
        shown = cover_lines[line][:60] if line < len(cover_lines) else "(fuzzy match)"
        print(f"  {row['score']:5.1f} | cover: {shown} | story: {row['story']['title'][:60]}")
    return [row["story"] for row in accepted]


def pick_stories(feed):
    now = datetime.now(NIGERIA)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_start = midnight + timedelta(hours=PRIORITY_START_HOUR)
    first_end = midnight + timedelta(hours=PRIORITY_END_HOUR)
    second_end = midnight + timedelta(hours=SECOND_END_HOUR)

    dated = [s for s in feed if s["published"]]
    print(f"Nigerian time now: {now:%d %b %H:%M}. Raw dates, first and last: "
          f"{feed[0]['raw_date']} | {feed[-1]['raw_date']}")
    print(f"Sample address field from the feed: {feed[0]['guid']}")
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

    def bonus(story):
        published = story["published"]
        if not published:
            return 0.0
        if first_start <= published < first_end:
            return 1.0
        return 0.5 if first_end <= published <= second_end else 0.0

    matched = []
    try:
        lines = read_cover_lines()
        print("Cover lines kept:", lines[:70])
        matched = match_cover(feed, lines, bonus)
    except Exception as error:
        print(f"Cover matching skipped: {error}")
    print(f"Stories matched to the cover: {len(matched)}")

    chosen, seen = [], set()
    for tier in (matched, tier1, tier2, tier3):
        for story in tier:
            if story["link"] not in seen and len(chosen) < MAX_ITEMS:
                seen.add(story["link"])
                chosen.append(story)
    if not chosen:
        raise ValueError("no usable stories in the feed")
    return chosen


def shorten_with(endpoint, extra, original):
    try:
        response = requests.get(endpoint, params={**extra, "url": original},
                                headers=HEADERS, timeout=15)
        text = response.text.strip()
        if response.ok and text.startswith("http"):
            return text
        print(f"{endpoint} refused ({response.status_code}): {text[:80]}")
    except Exception as error:
        print(f"{endpoint} failed: {error}")
    return None


def tidy_links(stories):
    shorteners = [("is.gd", "https://is.gd/create.php", {"format": "simple"}),
                  ("TinyURL", "https://tinyurl.com/api-create.php", {})]
    working = {name: True for name, _, _ in shorteners}
    links, methods = [], {}
    for story in stories:
        original = re.sub(r"[?&]utm_[^&]+", "", story["link"])
        short, method = original, "full link"
        if re.fullmatch(r"https?://(?:www\.)?punchng\.com/\?p=\d+", story["guid"]):
            short, method = story["guid"], "Punch short address"
        else:
            for name, endpoint, extra in shorteners:
                if not working[name]:
                    continue
                result = shorten_with(endpoint, extra, original)
                if result:
                    short, method = result, name
                    time.sleep(1)
                    break
                working[name] = False
        methods[method] = methods.get(method, 0) + 1
        links.append(short)
    print("Link methods used:", methods)
    return links


def build_message(stories, links):
    lines = [
        "*Today's Biggest Headlines*\n\n"
        "Here are some of the news reports that you shouldn't miss this morning:\n"
    ]
    for number, (story, link) in enumerate(zip(stories, links), 1):
        lines.append(f"*{number}. {story['title']}*\n{LINK_MARK} {link}")

    footer = (
        "\n\n"
        "*Source:* The Punch\n"
        "*Brought by:* RAC-FUTO Editorial Team"
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
        stories = pick_stories(read_feed())
        message = build_message(stories, tidy_links(stories))
    except Exception as error:
        problems.append(f"headlines: {error}")
        message = ("Daily Update Notice\n\nThere was a technical problem fetching "
                   "this morning's headlines. We are looking into it.")

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