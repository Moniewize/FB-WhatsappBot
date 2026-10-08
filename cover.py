import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

COVER_PAGE_LINK = "https://www.frontpages.com/the-punch/"
NIGERIA = ZoneInfo("Africa/Lagos")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_cover():
    """One attempt. Returns the image bytes, or raises an error saying why not."""
    page = requests.get(COVER_PAGE_LINK, headers=HEADERS, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if not tag or not tag.get("content"):
        raise ValueError("cover tag not found on the page")

    link = tag["content"]
    # The link contains the date, for example /g/2026/10/07/
    if datetime.now(NIGERIA).strftime("/g/%Y/%m/%d/") not in link:
        raise ValueError("page still shows an older cover (today's is not up yet)")

    image = requests.get(link, headers={**HEADERS, "Referer": COVER_PAGE_LINK}, timeout=60)
    image.raise_for_status()
    kind = image.headers.get("content-type", "")
    if not kind.startswith("image/") or len(image.content) < 20_000:
        raise ValueError(f"download is not a real cover ({kind}, {len(image.content)} bytes)")
    return image.content


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