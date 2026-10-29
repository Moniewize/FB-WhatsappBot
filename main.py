import html
import io
import json
import os
import re
import socket
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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Optional: the host shown as "apiUrl" in your Green API console instance settings
GREEN_API_URL = (os.getenv("GREEN_API_URL") or "").strip().rstrip("/")
GREEN_API_HOSTS = [h for h in dict.fromkeys([
    GREEN_API_URL,                 # your own host, if set
    "https://api.greenapi.com",    # Green API's universal host
    "https://api.green-api.com",   # the old host
]) if h]
GREEN_STATE = {"down": False}      # set once every host proved unreachable

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
COVER_ATTEMPTS = 6           # tries to get the cover ...
COVER_WAIT_SECONDS = 120     # ... with this pause between tries (about 12 minutes in total)

ROUNDUP = re.compile(r"\b(recap|top stories|roundup|headlines|newspaper review)\b", re.I)
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
MIN_BLOCK_COVERAGE = 0.60    # share of a cover headline's words that must appear in the story title
BLOCK_HEIGHT_RATIO = 0.6     # lines of one headline have a similar letter height ...
BLOCK_GAP = 0.8              # ... and sit closer together than this many letter heights
REPEAT_LIMIT = 0.5           # a filler story sharing this much of its words with a chosen story is a repeat
# a bullet sign at the start of a line marks the small lines under a main headline
BULLET = re.compile(r"^\s*(?:[•·●■▪◦]|o(?=[A-Z0-9\"“‘']))\s*")
REPEAT_IGNORE = {"federal", "government", "nigeria", "nigerian", "nigerians"}


def safe(text):
    """Hides secret tokens in anything that is printed."""
    text = str(text)
    for secret in (API_TOKEN, TELEGRAM_TOKEN):
        if secret:
            text = text.replace(secret, "***")
    return text


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


def get_cover():
    """Downloads today's cover, trying again for a while if it is not online yet."""
    from cover import fetch_cover

    for attempt in range(1, COVER_ATTEMPTS + 1):
        try:
            return fetch_cover()[0]
        except Exception as error:
            print(f"Cover not ready (attempt {attempt} of {COVER_ATTEMPTS}): {error}")
            if attempt < COVER_ATTEMPTS:
                time.sleep(COVER_WAIT_SECONDS)
    return None


def read_cover_lines(image_bytes):
    """Reads the cover twice (normal and colour-inverted) and returns its text lines with positions."""
    from PIL import Image, ImageOps
    from rapidocr import RapidOCR

    picture = Image.open(io.BytesIO(image_bytes)).convert("RGB")
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
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            found.append({"h": max(ys) - min(ys), "text": text,
                          "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                          "bullet": bool(BULLET.match(text))})
    if not found:
        return []

    median = sorted(f["h"] for f in found)[len(found) // 2]
    keep = [f for f in found
            if f["h"] >= SMALL_TEXT_CUTOFF * median
            and not any(sign in f["text"].lower() for sign in AD_SIGNS)]
    print(f"Cover text pieces read: {len(found)}. Kept {len(keep)}.")
    print("Cover lines kept:", [f["text"] for f in keep][:70])
    return keep


def find(word, pool):
    """The word itself, a plural or near spelling of it in the pool, or None."""
    from rapidfuzz import fuzz, process

    if word in pool:
        return word
    for other in pool:
        if other.rstrip("s") == word.rstrip("s") and len(word) > 3:
            return other
    if len(word) >= 5 and not any(ch.isdigit() for ch in word):
        best = process.extractOne(word, list(pool), scorer=fuzz.ratio, score_cutoff=86)
        if best:
            return best[0]
    return None


def share(words, pool):
    """Share of the words' letters whose word appears in the pool."""
    total = sum(len(w) for w in words)
    if not total:
        return 0.0
    return sum(len(w) for w in words if find(w, pool)) / total


def cover_blocks(lines):
    """Joins neighbouring lines of the same letter size into headlines. Bullet blocks are dropped."""
    parent = list(range(len(lines)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(lines):
        for j in range(i + 1, len(lines)):
            b = lines[j]
            big, small = max(a["h"], b["h"]), min(a["h"], b["h"])
            if big <= 0 or small < BLOCK_HEIGHT_RATIO * big:
                continue
            if min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) <= 0:
                continue  # side by side, not stacked
            gap = max(a["y0"], b["y0"]) - min(a["y1"], b["y1"])
            if gap <= BLOCK_GAP * big:
                parent[root(i)] = root(j)

    groups = {}
    for i, line in enumerate(lines):
        groups.setdefault(root(i), []).append(line)

    blocks = []
    for members in groups.values():
        members.sort(key=lambda m: (m["y0"], m["x0"]))
        if members[0]["bullet"]:
            continue  # the small bullet lines under a main headline are not wanted
        text = " ".join(BULLET.sub("", m["text"]) for m in members)
        words = list(dict.fromkeys(words_in(text)))
        if len(words) < MIN_WORDS:
            continue
        blocks.append({"text": text, "words": words,
                       "size": max(m["h"] for m in members),
                       "top": min(m["y0"] for m in members)})
    return blocks


def match_cover(stories, lines):
    """One story for each cover headline. The biggest headline comes first, then top to bottom."""
    blocks = cover_blocks(lines)
    infos = []
    for story in stories:
        if ROUNDUP.search(story["title"]):
            continue
        words = list(dict.fromkeys(words_in(story["title"])))
        if len(words) >= MIN_WORDS:
            infos.append({"story": story, "words": words})

    pairs = []
    for b, block in enumerate(blocks):
        for s, info in enumerate(infos):
            story_share = share(info["words"], block["words"])
            if story_share < MIN_COVERAGE:
                continue
            block_share = share(block["words"], info["words"])
            if block_share < MIN_BLOCK_COVERAGE:
                continue
            pairs.append((story_share + block_share, b, s))
    pairs.sort(reverse=True)

    used_blocks, used_stories, taken = set(), set(), {}
    for score, b, s in pairs:  # best pairs first; a headline or a story is used once
        if b in used_blocks or s in used_stories:
            continue
        used_blocks.add(b)
        used_stories.add(s)
        taken[b] = infos[s]["story"]

    print("\nCover headlines and the story found for each:")
    for b, block in sorted(enumerate(blocks), key=lambda row: row[1]["top"])[:25]:
        story = taken.get(b)
        label = story["title"][:70] if story else "NO STORY FOUND"
        print(f"  {block['text'][:60]!r} -> {label}")

    order = []
    if taken:
        biggest = max(taken, key=lambda k: blocks[k]["size"])
        order = [biggest] + sorted((b for b in taken if b != biggest), key=lambda b: blocks[b]["top"])
    return [taken[b] for b in order][:MAX_ITEMS]


def repeats(title, chosen_titles):
    """True when the title is mostly the same words as an already chosen story."""
    mine = [w for w in dict.fromkeys(words_in(title)) if w not in REPEAT_IGNORE]
    if not mine:
        return False
    for other_title in chosen_titles:
        other = [w for w in dict.fromkeys(words_in(other_title)) if w not in REPEAT_IGNORE]
        if other and (share(mine, other) >= REPEAT_LIMIT or share(other, mine) >= REPEAT_LIMIT):
            return True
    return False


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
    cover = get_cover()
    if cover is None:
        print("The cover never became available.")
    else:
        try:
            matched = match_cover(feed, read_cover_lines(cover))
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

    chosen, seen, repeated = [], set(), 0
    for tier in (matched, tier1, tier2, tier3):
        for story in tier:
            if story["link"] in seen or len(chosen) >= MAX_ITEMS:
                continue
            if tier is not matched and repeats(story["title"], [c["title"] for c in chosen]):
                repeated += 1  # a filler story about a topic already in the list
                continue
            seen.add(story["link"])
            chosen.append(story)
    print(f"From the cover: {len(matched)}. Filled from the midnight window and newest: "
          f"{len(chosen) - len(matched)}. Filler skipped as repeats: {repeated}.")
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
        # characters that break bold text or links in chat apps are removed
        safe_title = re.sub(r"[*_`\[\]]", "", story["title"])
        lines.append(f"*{number}. {safe_title}*\n{LINK_MARK} {link}")

    footer = (
        "\n\n"
        "*Source:* The Punch\n"
        "*Brought by:* RAC-FUTO Editorial Team"
    )
    return "\n\n".join(lines) + footer


def check_green_hosts():
    """Prints whether this machine can reach each Green API host (helps diagnose timeouts)."""
    for host in GREEN_API_HOSTS:
        name = host.split("//")[1]
        try:
            infos = socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
            addresses = sorted({info[4][0] for info in infos})
            with socket.create_connection((name, 443), timeout=10):
                pass
            print(f"Network check {name}: reachable ({', '.join(addresses[:3])}).")
        except Exception as error:
            print(f"Network check {name}: FAILED ({type(error).__name__}: {error}).")


def green_post(endpoint, **kwargs):
    """Sends a request to Green API, trying each host. Moves on only if no connection was made."""
    if GREEN_STATE["down"]:
        raise ConnectionError("Green API was unreachable earlier in this run")
    last_error = None
    for round_number in range(2):
        for host in list(GREEN_API_HOSTS):
            link = f"{host}/waInstance{ID_INSTANCE}/{endpoint}/{API_TOKEN}"
            try:
                response = requests.post(link, timeout=(10, 60), **kwargs)
            except requests.ConnectionError as error:  # no connection: nothing was sent
                last_error = error
                print(f"Green API host not reachable: {host.split('//')[1]}")
                continue
            response.raise_for_status()
            print(f"Green API host used: {host.split('//')[1]}")
            if host != GREEN_API_HOSTS[0]:  # try the host that worked first next time
                GREEN_API_HOSTS.remove(host)
                GREEN_API_HOSTS.insert(0, host)
            return response.json()
        if round_number == 0:
            print("No Green API host reachable. Waiting 20 seconds, then trying again.")
            time.sleep(20)
    GREEN_STATE["down"] = True
    raise last_error


def chat_identifier(raw):
    cleaned = raw.strip().replace("+", "").replace(" ", "")
    return cleaned if ("@g.us" in cleaned or "@c.us" in cleaned) else f"{cleaned}@c.us"


def whatsapp_ready():
    return bool(ID_INSTANCE and API_TOKEN and PHONE_NUMBERS)


def telegram_ready():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def deliver_whatsapp(message):
    """Returns (messages_sent, problems)."""
    if not whatsapp_ready():
        print("WhatsApp skipped: credentials not set.")
        return 0, []
    check_green_hosts()
    sent, problems = 0, []
    for raw in (p for p in PHONE_NUMBERS.split(",") if p.strip()):
        chat = chat_identifier(raw)
        try:
            green_post("sendMessage", json={"chatId": chat, "message": message})
            sent += 1
            print(f"Headlines delivered via WhatsApp to {chat}")
        except Exception as error:
            problems.append(f"WhatsApp {chat}: {safe(error)}")
            print(f"FAILED for WhatsApp {chat}: {safe(error)}")
        time.sleep(3)
    return sent, problems


def deliver_telegram(message):
    """Returns (messages_sent, problems)."""
    if not telegram_ready():
        print("Telegram skipped: credentials not set.")
        return 0, []
    link = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    base = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    for extra in ({"parse_mode": "Markdown"}, {}):  # plain text if Markdown is rejected
        try:
            response = requests.post(link, json={**base, **extra}, timeout=30)
        except Exception as error:
            print(f"Telegram not reachable: {safe(error)}")
            return 0, [f"Telegram: {safe(error)}"]
        if response.status_code == 400 and extra:
            print(f"Telegram rejected the formatting ({response.text[:150]}). "
                  "Retrying as plain text.")
            continue
        if not response.ok:
            reason = response.text[:300]
            print(f"Telegram refused ({response.status_code}): {reason}")
            return 0, [f"Telegram {response.status_code}: {reason}"]
        print("Headlines delivered to Telegram.")
        return 1, []
    return 0, ["Telegram: delivery failed"]


def main():
    if not (whatsapp_ready() or telegram_ready()):
        print("No delivery channel is configured (WhatsApp or Telegram secrets missing).")
        sys.exit(1)

    try:
        stories = pick_stories(merge_collected(read_feed()))
        message = build_message(stories, tidy_links(stories))
    except Exception as error:
        print(f"NOT SENT: {safe(error)}")
        sys.exit(1)  # the team gets nothing; GitHub emails you instead

    print("\n===== MESSAGE =====\n" + message + "\n===================")

    delivered, problems = 0, []
    for deliver in (deliver_whatsapp, deliver_telegram):
        sent, issues = deliver(message)
        delivered += sent
        problems += issues

    if delivered == 0:
        print("NOT DELIVERED: no channel accepted the message.")
        sys.exit(1)
    if problems:
        print("PROBLEMS (the message reached some recipients):", *problems, sep="\n- ")
        sys.exit(1)  # marks the run as failed so GitHub emails you


if __name__ == "__main__":
    main()