import html
import io
import json
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

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

FEED_TIMES_ARE_LOCAL = True  # the feed prints Nigerian clock time but labels it +0000
MAX_ITEMS = 10               # headlines in the message
PRIORITY_MINUTES = 30        # filler stories: first those posted 00:00 to 00:30 ...
FILL_UNTIL_HOUR = 4          # ... then those posted until 04:00
MIN_COVERAGE = 0.70          # share of a story title's words that must appear on the cover
MIN_WORDS = 3                # a title needs at least this many distinctive words
MIN_MATCHED = 1              # fewer cover matches than this and nothing is sent
SMALL_TEXT_CUTOFF = 0.4      # ignore cover text smaller than 40% of the typical size
LINK_MARK = "==="            # shown before each link

ROUNDUP = re.compile(r"recap|top stories|roundup|headlines|newspaper review", re.I)
AD_SIGNS = ("www.", ".ng", ".com", "@", "licensed", "age 18", "play for", "bet on",
            "download", "terms apply")
SHORTHAND = {
    "s'west": "south west", "s'east": "south east", "s'south": "south south",
    "n'west": "north west", "n'east": "north east", "n'central": "north central",
    "a'court": "appeal court", "s'court": "supreme court",
    "n'assembly": "national assembly", "fg": "federal government",
    "naf": "nigerian air force",
}
NOISE_WORDS = {
    "punch", "punchng", "newspaper", "newspapers", "widely", "read", "most", "year",
    "mobilepunch", "punchnewspapers", "page", "pages", "friday", "saturday", "sunday",
    "monday", "tuesday", "wednesday", "thursday", "october", "november", "december",
    "this", "that", "with", "from", "will", "have", "said", "says", "after", "over",
    "into", "about", "their", "them", "they", "been", "were", "what", "when", "where",
    "which", "also", "more", "than", "here", "there", "your", "just", "would", "could",
    "should", "still", "only", "some", "other",
}
TOKEN = re.compile(r"n\d[\d.,]*(?:bn|trn|m|b|k)?|[a-z]{4,}|\d[\d,]*\d")


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
                            "published": parse_date(item.findtext("pubDate"))})
    if not stories:
        raise ValueError("news feed returned no stories")
    return stories


def merge_collected(feed):
    """Adds the stories saved overnight by the collector (stories.json), if present."""
    try:
        with open("stories.json", encoding="utf-8") as handle:
            saved = json.load(handle)
    except Exception as error:
        print(f"No saved stories used ({error}).")
        return feed
    seen = {s["link"] for s in feed}
    added = 0
    for row in saved:
        if row["link"] in seen:
            continue
        try:
            published = datetime.fromisoformat(row["published"])
        except Exception:
            continue
        feed.append({"title": row["title"], "link": row["link"], "published": published})
        seen.add(row["link"])
        added += 1
    print(f"Saved stories added: {added} (saved file holds {len(saved)}).")
    return feed


def expand(text):
    text = text.lower().replace("’", "'")
    for short, full in SHORTHAND.items():
        text = re.sub(rf"\b{re.escape(short)}\b", full, text)
    return text


def words_in(text):
    found = []
    for token in TOKEN.findall(expand(text)):
        token = token.replace(",", "").rstrip(".")
        if token not in NOISE_WORDS and (token.isalpha() or len(token) >= 3):
            found.append(token)
    return found


def read_cover_lines():
    """Reads the cover twice (normal and colour-inverted) and returns its text lines."""
    from PIL import Image, ImageOps
    from rapidocr import RapidOCR
    from cover import fetch_cover

    picture = Image.open(io.BytesIO(fetch_cover())).convert("RGB")
    engine = RapidOCR()

    found, seen_text = [], set()
    for version in (picture, ImageOps.invert(picture)):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            version.save(handle, "JPEG", quality=92)
            path = handle.name
        try:
            result = engine(path)
        finally:
            os.remove(path)
        if result is None or result.txts is None or result.boxes is None:
            continue
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            text = text.strip()
            key = re.sub(r"[^a-z0-9]", "", text.lower())
            if score < 0.5 or len(key) < 3 or key in seen_text:
                continue
            seen_text.add(key)
            ys = [float(p[1]) for p in box]
            found.append({"h": max(ys) - min(ys), "text": text})
    if not found:
        return []

    median = sorted(f["h"] for f in found)[len(found) // 2]
    keep = [f for f in found
            if f["h"] >= SMALL_TEXT_CUTOFF * median
            and not any(sign in f["text"].lower() for sign in AD_SIGNS)]
    print(f"Cover text pieces read: {len(found)}. Kept {len(keep)}.")
    print("Cover lines kept:", [f["text"] for f in keep][:70])
    return keep


def match_cover(stories, lines):
    """Stories whose title words appear on the cover, biggest print first."""
    from rapidfuzz import fuzz, process

    cover_words, height_of = set(), {}
    for line in lines:
        for word in words_in(line["text"]):
            cover_words.add(word)
            height_of[word] = max(height_of.get(word, 0), line["h"])

    def find(word):
        if word in cover_words:
            return word
        if len(word) >= 6:
            best = process.extractOne(word, cover_words, scorer=fuzz.ratio, score_cutoff=88)
            if best:
                return best[0]
        return None

    rows = []
    for story in stories:
        if ROUNDUP.search(story["title"]):
            continue
        words = list(dict.fromkeys(words_in(story["title"])))
        if len(words) < MIN_WORDS:
            continue
        hits = {w: find(w) for w in words}
        coverage = sum(len(w) for w, h in hits.items() if h) / sum(len(w) for w in words)
        size = max((height_of[h] for h in hits.values() if h), default=0)
        rows.append({"story": story, "coverage": coverage, "size": size})

    print("\nBest cover matches (share of title found | story):")
    for row in sorted(rows, key=lambda r: -r["coverage"])[:15]:
        print(f"  {row['coverage']:.2f} | {row['story']['title'][:80]}")

    accepted = [r for r in rows if r["coverage"] >= MIN_COVERAGE]
    accepted.sort(key=lambda r: -r["size"])
    return [r["story"] for r in accepted][:MAX_ITEMS]


def pick_stories(feed):
    now = datetime.now(NIGERIA)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    priority_end = midnight + timedelta(minutes=PRIORITY_MINUTES)
    fill_end = midnight + timedelta(hours=FILL_UNTIL_HOUR)

    dated = [s for s in feed if s["published"]]
    if dated:
        print(f"Nigerian time now: {now:%d %b %H:%M}. Stories available cover "
              f"{min(s['published'] for s in dated):%d %b %H:%M} to "
              f"{max(s['published'] for s in dated):%d %b %H:%M} ({len(feed)} stories).")

    matched = []
    try:
        matched = match_cover(feed, read_cover_lines())
    except Exception as error:
        print(f"Cover matching failed: {error}")
    print(f"\nStories matched to the cover: {len(matched)}")
    if len(matched) < MIN_MATCHED:
        raise ValueError(f"only {len(matched)} stories matched the cover; nothing sent")

    usable = [s for s in dated if not ROUNDUP.search(s["title"])]
    tier1 = sorted((s for s in usable if midnight <= s["published"] < priority_end),
                   key=lambda s: s["published"])
    tier2 = sorted((s for s in usable if priority_end <= s["published"] <= fill_end),
                   key=lambda s: s["published"])
    tier3 = sorted((s for s in usable if s["published"] > now - timedelta(hours=24)),
                   key=lambda s: s["published"], reverse=True)

    chosen, seen = [], set()
    for tier in (matched, tier1, tier2, tier3):
        for story in tier:
            if story["link"] not in seen and len(chosen) < MAX_ITEMS:
                seen.add(story["link"])
                chosen.append(story)
    print(f"From the cover: {len(matched)}. Filled from the midnight window and newest: "
          f"{len(chosen) - len(matched)}.")
    return chosen


def shorten(link, state):
    for name, endpoint in (("is.gd", "https://is.gd/create.php"),
                           ("v.gd", "https://v.gd/create.php")):
        if not state[name]:
            continue
        for _ in range(2):
            try:
                response = requests.get(endpoint, params={"format": "simple", "url": link},
                                        headers=HEADERS, timeout=15)
                text = response.text.strip()
                if response.ok and text.startswith("http"):
                    time.sleep(1)
                    return text, name
                print(f"{name} refused: {text[:80]}")
            except Exception as error:
                print(f"{name} failed: {error}")
            time.sleep(2)
        state[name] = False
    return link, "full link"


def tidy_links(stories):
    state = {"is.gd": True, "v.gd": True}
    links, methods = [], {}
    for story in stories:
        original = re.sub(r"[?&]utm_[^&]+", "", story["link"])
        link, method = shorten(original, state)
        methods[method] = methods.get(method, 0) + 1
        links.append(link)
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
    missing = [name for name, value in [
        ("GREEN_API_ID_INSTANCE", ID_INSTANCE),
        ("GREEN_API_TOKEN", API_TOKEN),
        ("PHONE_NUMBER", PHONE_NUMBERS),
    ] if not value]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    try:
        stories = pick_stories(merge_collected(read_feed()))
        message = build_message(stories, tidy_links(stories))
    except Exception as error:
        print(f"NOT SENT: {error}")
        sys.exit(1)  # the team gets nothing; GitHub emails you instead

    print("\n===== MESSAGE =====\n" + message + "\n===================")
    problems = deliver(message)
    if problems:
        print("PROBLEMS:", *problems, sep="\n- ")
        sys.exit(1)


if __name__ == "__main__":
    main()