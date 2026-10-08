import io
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

COVER_PAGE_LINK = "https://www.frontpages.com/the-punch/"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
IMAGE_HEADERS = {
    **HEADERS,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": COVER_PAGE_LINK,
}
LINK_PATTERN = re.compile(
    r'''((?:https?:)?(?://www\.frontpages\.com)?/[gt]/\d{4}/\d{2}/\d{2}/[^"'\s)<>\\]+)'''
)


def candidate_links(html):
    html = html.replace("\\/", "/")
    soup = BeautifulSoup(html, "html.parser")

    og_link = None
    for tag in soup.find_all("meta"):
        if (tag.get("property") == "og:image" or tag.get("name") == "og:image") and tag.get("content"):
            og_link = urljoin(COVER_PAGE_LINK, tag["content"].strip())
            break

    links = []

    def add(link):
        if link and "the-punch-" in link.lower() and link not in links:
            links.append(link)

    # 1. The preview name is shortened, so find the full file name in the page source
    if og_link:
        folder, _, filename = og_link.rpartition("/")
        stem = filename.split(".")[0]  # for example: the-punch-0658453se
        full_names = set(re.findall(re.escape(stem) + r"[a-z0-9]*\.webp", html))
        for full in sorted(full_names, key=len, reverse=True):
            add(f"{folder}/{full}")

    # 2. Any cover-looking address anywhere in the page source
    for raw in LINK_PATTERN.findall(html):
        add(urljoin(COVER_PAGE_LINK, raw.strip()))

    # 3. Last resort: the shortened preview address itself
    add(og_link)
    return links


def is_older_cover(link):
    match = re.search(r"/g/(\d{4})/(\d{2})/(\d{2})/", link)
    if not match:
        return False
    return "-".join(match.groups()) != datetime.now(NIGERIA).strftime("%Y-%m-%d")


def to_jpeg(data):
    picture = Image.open(io.BytesIO(data))
    if min(picture.size) < 400:
        raise ValueError(f"image too small ({picture.size})")
    output = io.BytesIO()
    picture.convert("RGB").save(output, "JPEG", quality=90)
    return output.getvalue()


def fetch_cover():
    page = requests.get(COVER_PAGE_LINK, headers=HEADERS, timeout=30)
    page.raise_for_status()
    links = candidate_links(page.text)
    print(f"Page loaded. Candidate cover addresses: {links}")
    if not links:
        raise ValueError("no cover addresses found in the page")

    notes = []
    for link in links:
        if is_older_cover(link):
            notes.append(f"{link} -> older cover")
            continue
        try:
            response = requests.get(link, headers=IMAGE_HEADERS, timeout=60)
            print(f"Tried {link} -> status {response.status_code}, "
                  f"{response.headers.get('content-type')}, {len(response.content)} bytes")
            response.raise_for_status()
            if len(response.content) < 20_000:
                raise ValueError("file too small to be a front page")
            return to_jpeg(response.content)
        except Exception as error:
            notes.append(f"{link} -> {error}")
    raise ValueError(" | ".join(notes))


def green_post(endpoint, **kwargs):
    link = f"https://api.green-api.com/waInstance{ID_INSTANCE}/{endpoint}/{API_TOKEN}"
    response = requests.post(link, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def chat_identifier(raw):
    cleaned = raw.strip().replace("+", "").replace(" ", "")
    return cleaned if ("@g.us" in cleaned or "@c.us" in cleaned) else f"{cleaned}@c.us"


def deliver(image):
    failures = []
    today = datetime.now(NIGERIA).strftime("%A, %d %B %Y")
    for raw in (p for p in PHONE_NUMBERS.split(",") if p.strip()):
        chat = chat_identifier(raw)
        try:
            green_post(
                "sendFileByUpload",
                data={"chatId": chat, "fileName": "punch_frontpage.jpg",
                      "caption": f"The Punch front page, {today}"},
                files={"file": ("punch_frontpage.jpg", image, "image/jpeg")},
            )
            print(f"Cover delivered to {chat}")
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
        image = fetch_cover()
    except Exception as error:
        print(f"No cover sent: {error}")
        sys.exit(1)  # nothing goes to your team; GitHub emails you instead

    problems = deliver(image)
    if problems:
        print("PROBLEMS:", *problems, sep="\n- ")
        sys.exit(1)


if __name__ == "__main__":
    main()