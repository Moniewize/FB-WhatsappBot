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

# Optional: the hosts shown as "apiUrl" and "mediaUrl" in your Green API console
GREEN_API_URL = (os.getenv("GREEN_API_URL") or "").strip().rstrip("/")
GREEN_MEDIA_URL = (os.getenv("GREEN_MEDIA_URL") or "").strip().rstrip("/")
API_HOSTS = [h for h in dict.fromkeys([
    GREEN_API_URL,
    "https://api.greenapi.com",    # Green API's universal host
    "https://api.green-api.com",   # the old host
]) if h]
MEDIA_HOSTS = [h for h in dict.fromkeys([
    GREEN_MEDIA_URL,
    "https://media.greenapi.com",  # universal media host (file uploads)
    "https://media.green-api.com",
    *API_HOSTS,                    # these accepted uploads for you before
]) if h]
GREEN_STATE = {"down": False}      # set once every host proved unreachable
SEND_ATTEMPTS = 2                  # tries per recipient
JOURNAL_WAIT_SECONDS = 120         # Green API's journal can lag by up to 2 minutes

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

COVER_PAGE_LINK = "https://www.frontpages.com/the-punch/"
COVER_SELECTOR = 'img[alt^="Cover The Punch"]'
NIGERIA = ZoneInfo("Africa/Lagos")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
COVER_ATTEMPTS = 6        # tries to get the cover ...
COVER_WAIT_SECONDS = 120  # ... with this pause between tries (about 12 minutes in total)


class GreenAmbiguous(Exception):
    """Green API answered with a server error or timed out after connecting.
    The message may or may not have been accepted."""

    def __init__(self, host, message):
        super().__init__(message)
        self.host = host


def safe(text):
    """Hides secret tokens in anything that is printed."""
    text = str(text)
    for secret in (API_TOKEN, TELEGRAM_BOT_TOKEN):
        if secret:
            text = text.replace(secret, "***")
    return text


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


def get_cover():
    """Downloads today's cover, trying again for a while if it is not online yet."""
    for attempt in range(1, COVER_ATTEMPTS + 1):
        try:
            return fetch_cover()
        except Exception as error:
            print(f"Cover not ready (attempt {attempt} of {COVER_ATTEMPTS}): {error}")
            if attempt < COVER_ATTEMPTS:
                time.sleep(COVER_WAIT_SECONDS)
    return None


def green_post(endpoint, skip_hosts=(), **kwargs):
    """Sends a request to Green API, trying each host.
    Moves on only when no connection was made. A server error or a timeout after
    connecting raises GreenAmbiguous, because the message may already be accepted."""
    if GREEN_STATE["down"]:
        raise ConnectionError("Green API was unreachable earlier in this run")
    pool = MEDIA_HOSTS if endpoint in ("sendFileByUpload", "uploadFile") else API_HOSTS
    hosts = [h for h in pool if h not in skip_hosts]
    if not hosts:
        raise ConnectionError("no Green API host left to try")

    last_error = None
    for round_number in range(2):
        for host in list(hosts):
            name = host.split("//")[1]
            link = f"{host}/waInstance{ID_INSTANCE}/{endpoint}/{API_TOKEN}"
            try:
                response = requests.post(link, timeout=(10, 90), **kwargs)
            except requests.ConnectionError as error:  # no connection: nothing was sent
                last_error = error
                print(f"Green API host not reachable: {name}")
                continue
            except requests.Timeout as error:  # connected, then no answer in time
                raise GreenAmbiguous(host, f"no answer from {name}") from error
            if response.status_code in (502, 503, 504):
                raise GreenAmbiguous(host, f"{response.status_code} from {name}")
            if response.status_code in (401, 403, 404) and host != hosts[-1]:
                last_error = requests.HTTPError(f"{response.status_code} from {name}")
                print(f"{name} refused this instance ({response.status_code}). Trying the next host.")
                continue
            response.raise_for_status()
            print(f"Green API host used: {name}")
            if host != pool[0]:  # try the host that worked first next time
                pool.remove(host)
                pool.insert(0, host)
            return response.json()
        if round_number == 0:
            print("No Green API host reachable. Waiting 20 seconds, then trying again.")
            time.sleep(20)
    if isinstance(last_error, requests.ConnectionError):
        GREEN_STATE["down"] = True
    raise last_error


def already_sent(chat, caption):
    """Asks Green API's message journal whether this chat already got the cover."""
    for host in API_HOSTS:
        link = f"{host}/waInstance{ID_INSTANCE}/lastOutgoingMessages/{API_TOKEN}"
        try:
            response = requests.get(link, params={"minutes": 15}, timeout=(10, 30))
            if not response.ok:
                continue
            rows = response.json()
        except (requests.RequestException, ValueError):
            continue
        return any(
            isinstance(row, dict)
            and row.get("chatId") == chat
            and (row.get("caption") or "").strip() == caption.strip()
            and row.get("statusMessage") != "failed"
            for row in rows
        )
    return False


def send_cover(chat, image, caption):
    """Sends the cover to one chat without risking a duplicate after a gateway timeout."""
    data = {"chatId": chat, "fileName": "punch_frontpage.jpg", "caption": caption}
    files = {"file": ("punch_frontpage.jpg", image, "image/jpeg")}
    skip = set()
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            green_post("sendFileByUpload", skip_hosts=skip, data=data, files=files)
            return
        except GreenAmbiguous as error:
            print(f"Green API gave no clear answer ({error}). Waiting "
                  f"{JOURNAL_WAIT_SECONDS} seconds, then checking whether it was sent anyway.")
            skip.add(error.host)
            time.sleep(JOURNAL_WAIT_SECONDS)
            if already_sent(chat, caption):
                print("The message journal shows the cover was delivered after all.")
                return
            if attempt == SEND_ATTEMPTS:
                raise
            print("Not in the journal. Trying the next host.")


def chat_identifier(raw):
    cleaned = raw.strip().replace("+", "").replace(" ", "")
    return cleaned if ("@g.us" in cleaned or "@c.us" in cleaned) else f"{cleaned}@c.us"


def whatsapp_ready():
    return bool(ID_INSTANCE and API_TOKEN and PHONE_NUMBERS)


def telegram_ready():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def deliver_whatsapp(image):
    """Returns (photos_sent, problems)."""
    if not whatsapp_ready():
        print("WhatsApp skipped: credentials not set.")
        return 0, []
    sent, problems = 0, []
    caption = f"The Punch front page, {datetime.now(NIGERIA).strftime('%A, %d %B %Y')}"
    for raw in (p for p in PHONE_NUMBERS.split(",") if p.strip()):
        chat = chat_identifier(raw)
        try:
            send_cover(chat, image, caption)
            sent += 1
            print(f"Cover delivered to WhatsApp chat {chat}")
        except Exception as error:
            problems.append(f"WhatsApp {chat}: {safe(error)}")
            print(f"FAILED for WhatsApp {chat}: {safe(error)}")
        time.sleep(3)
    return sent, problems


def deliver_telegram(image):
    """Returns (photos_sent, problems)."""
    if not telegram_ready():
        print("Telegram skipped: credentials not set.")
        return 0, []

    today = datetime.now(NIGERIA).strftime("%A, %d %B %Y")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    for attempt in range(1, 3):
        try:
            response = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"The Punch front page, {today}"},
                files={"photo": ("punch_frontpage.jpg", image, "image/jpeg")},
                timeout=(10, 60),
            )
        except requests.ConnectionError as error:  # no connection: nothing was sent
            print(f"Telegram not reachable (attempt {attempt} of 2): {safe(error)}")
            time.sleep(10)
            continue
        except Exception as error:
            print(f"Telegram delivery failed: {safe(error)}")
            return 0, [f"Telegram: {safe(error)}"]
        if not response.ok:
            reason = response.text[:300]
            print(f"Telegram refused ({response.status_code}): {reason}")
            return 0, [f"Telegram {response.status_code}: {reason}"]
        print("Cover delivered to Telegram.")
        return 1, []
    return 0, ["Telegram: not reachable"]


def main():
    if not (whatsapp_ready() or telegram_ready()):
        print("No delivery channel is configured (WhatsApp or Telegram secrets missing).")
        sys.exit(1)

    image = get_cover()
    if image is None:
        print("No cover sent: it never became available.")
        sys.exit(1)

    delivered, problems = 0, []
    for deliver in (deliver_whatsapp, deliver_telegram):
        sent, issues = deliver(image)
        delivered += sent
        problems += issues

    if delivered == 0:
        print("NOT DELIVERED: no channel accepted the cover.")
        sys.exit(1)
    if problems:
        print("PROBLEMS (the cover reached some recipients):", *problems, sep="\n- ")
        sys.exit(1)  # marks the run as failed so GitHub emails you


if __name__ == "__main__":
    main()