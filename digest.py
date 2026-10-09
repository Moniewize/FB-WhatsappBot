import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

NIGERIA = ZoneInfo("Africa/Lagos")
FEED = "https://rss.punchng.com/v1/category/latest_news"
POSTS = "https://punchng.com/wp-json/wp/v2/posts"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/xml, */*",
}


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def part_feed():
    print("===== NEWS FEED =====")
    response = requests.get(FEED, headers=HEADERS, timeout=20)
    print("Status:", response.status_code)
    response.raise_for_status()
    items = ET.fromstring(response.content).find("channel").findall("item")
    times = []
    for item in items:
        try:
            times.append(parsedate_to_datetime(item.findtext("pubDate")).astimezone(NIGERIA))
        except Exception:
            pass
    print("Stories in feed:", len(items))
    if times:
        print("Oldest:", min(times), "| Newest:", max(times))
    print("Fields in each story:", [child.tag for child in items[0]])
    for item in items[:5]:
        print("-", clean(item.findtext("title"))[:90], "|", clean(item.findtext("description"))[:150])


def part_posts():
    print("\n===== WEBSITE ARTICLE LIST, MIDNIGHT TO 04:00 TODAY =====")
    midnight = datetime.now(NIGERIA).replace(hour=0, minute=0, second=0, microsecond=0)
    params = {
        "after": midnight.isoformat(),
        "before": (midnight + timedelta(hours=4)).isoformat(),
        "per_page": 100,
        "orderby": "date",
        "order": "asc",
        "_fields": "id,date,link,title,excerpt",
    }
    response = requests.get(POSTS, params=params, headers=HEADERS, timeout=30)
    print("Status:", response.status_code, "| total:", response.headers.get("X-WP-Total"),
          "| pages:", response.headers.get("X-WP-TotalPages"))
    if not response.ok:
        print("Reply starts with:", response.text[:300])
        return
    posts = response.json()
    print("Articles returned:", len(posts))
    for post in posts[:60]:
        print(post["date"][11:16], "|", clean(post["title"]["rendered"])[:85],
              "-> https://punchng.com/?p=" + str(post["id"]))
        print("       ", clean(post["excerpt"]["rendered"])[:140])


def main():
    for part in (part_feed, part_posts):
        try:
            part()
        except Exception as error:
            print(f"{part.__name__} failed: {error}")


if __name__ == "__main__":
    main()