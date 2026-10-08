import io
import os
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

COVER_PAGE_LINK = "https://www.frontpages.com/the-punch/"
COVER_SELECTOR = 'img[alt^="Cover The Punch"]'
NIGERIA = ZoneInfo("Africa/Lagos")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def launch_browser(playwright):
    """Use the Chrome already installed on GitHub's machine; fall back to downloading one."""
    try:
        return playwright.chromium.launch(channel="chrome")
    except Exception as error:
        print(f"Installed Chrome not usable ({error}). Trying the bundled browser.")
    try:
        return playwright.chromium.launch()
    except Exception:
        print("Downloading a browser (one time, about a minute)...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return playwright.chromium.launch()


def to_jpeg(data):
    picture = Image.open(io.BytesIO(data))
    if min(picture.size) < 400:
        raise ValueError(f"image too small ({picture.size})")
    output = io.BytesIO()
    picture.convert("RGB").save(output, "JPEG", quality=90)
    return output.getvalue()


def fetch_cover():
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 2000},
                device_scale_factor=2,
            )
            page = context.new_page()
            page.goto(COVER_PAGE_LINK, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector(COVER_SELECTOR, state="attached", timeout=30_000)

            # Scroll the cover into view so the page starts loading it, then wait until it is loaded
            page.evaluate(
                "document.querySelector('%s').scrollIntoView({block: 'center'})" % COVER_SELECTOR
            )
            try:
                page.wait_for_function(
                    """() => {
                        const img = document.querySelector('img[alt^="Cover The Punch"]');
                        return img && img.complete && img.naturalWidth > 400;
                    }""",
                    timeout=45_000,
                )
            except Exception:
                tag = page.evaluate(
                    "(document.querySelector('%s') || {}).outerHTML || 'no cover tag found'"
                    % COVER_SELECTOR
                )
                print(f"Cover never finished loading. Its tag looks like: {str(tag)[:600]}")
                raise

            cover = page.locator(COVER_SELECTOR).first
            alt = cover.get_attribute("alt") or ""
            source = cover.evaluate("img => img.currentSrc || img.src")
            print(f"Cover found. Label: {alt!r}. Address: {source}")

            today = datetime.now(NIGERIA).strftime("%d/%m/%Y")  # the label uses day/month/year
            if "/" in alt and today not in alt:
                raise ValueError(f"page still shows an older cover (label {alt!r}, today is {today})")

            data = None
            try:
                response = context.request.get(source, headers={"Referer": COVER_PAGE_LINK})
                print(f"Direct download: status {response.status}")
                if response.ok:
                    data = response.body()
            except Exception as error:
                print(f"Direct download failed: {error}")

            if not data or len(data) < 20_000:
                print("Using a screenshot of the cover instead.")
                data = cover.screenshot(type="png")

            return to_jpeg(data)
        finally:
            browser.close()


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