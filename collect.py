import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

FEED = "https://rss.punchng.com/v1/category/latest_news"
STORE = "stories.json"
KEEP_HOURS = 48
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def read_feed():
    response = requests.get(FEED, headers=HEADERS, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    stories = []
    for item in (channel.findall("item") if channel is not None else []):
        title = clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).replace(tzinfo=NIGERIA)
        except Exception:
            continue
        if title and link:
            stories.append({"title": title, "link": link, "published": published.isoformat()})
    return stories


def main():
    try:
        with open(STORE, encoding="utf-8") as handle:
            saved = json.load(handle)
    except Exception:
        saved = []
    known = {s["link"] for s in saved}
    feed = read_feed()
    fresh = [s for s in feed if s["link"] not in known]
    saved += fresh
    cutoff = (datetime.now(NIGERIA) - timedelta(hours=KEEP_HOURS)).isoformat()
    saved = sorted((s for s in saved if s["published"] >= cutoff), key=lambda s: s["published"])
    with open(STORE, "w", encoding="utf-8") as handle:
        json.dump(saved, handle, ensure_ascii=False, indent=1)
    print(f"Feed had {len(feed)} stories, {len(fresh)} new. Saved file holds {len(saved)}.")


if __name__ == "__main__":
    main()