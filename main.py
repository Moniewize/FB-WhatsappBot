import os
import re
import xml.etree.ElementTree as ET
import requests
from playwright.sync_api import sync_playwright

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
FRONTPAGES_PUNCH_URL = "https://www.frontpages.com/the-punch/"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def fetch_frontpage_cover_image():
    """Renders JS via Playwright to extract and download the direct high-res image binary."""
    print(f"🌐 Playwright: Launching headless browser for {FRONTPAGES_PUNCH_URL}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            # Wait until DOM and network requests settle
            page.goto(FRONTPAGES_PUNCH_URL, wait_until="networkidle", timeout=30000)

            img_url = None

            # Strategy 1: Look for <a> tags linking directly to high-res image files
            anchors = page.query_selector_all("a[href]")
            for a in anchors:
                href = a.get_attribute("href") or ""
                if re.search(r"\.(jpg|jpeg|png)($|\?)", href, re.I):
                    if not any(skip in href.lower() for skip in ["logo", "icon", "avatar", "banner", "150x150"]):
                        img_url = href
                        print(f"🖼️ Found full-res image URL in anchor tag: {img_url}")
                        break

            # Strategy 2: Check dynamically rendered <img> tags
            if not img_url:
                imgs = page.query_selector_all("img")
                for img in imgs:
                    src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    if re.search(r"\.(jpg|jpeg|png)", src, re.I):
                        if not any(skip in src.lower() for skip in ["logo", "icon", "avatar", "150x150"]):
                            img_url = src
                            print(f"🖼️ Found full-res image URL in <img> element: {img_url}")
                            break

            browser.close()

            if not img_url:
                print("❌ Playwright Warning: No cover image element detected in rendered DOM.")
                return None

            # Ensure complete URL schema
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                img_url = "https://www.frontpages.com" + img_url

            # Download original high-resolution image binary directly
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            }
            print(f"🔄 Downloading original full-resolution image from: {img_url}")
            img_res = requests.get(img_url, headers=headers, timeout=20)

            if img_res.status_code == 200 and len(img_res.content) > 10000:
                print(f"✅ Downloaded full-resolution cover image ({len(img_res.content)} bytes)!")
                return img_res.content
            else:
                print(f"❌ Image download failed. Status: {img_res.status_code}, Length: {len(img_res.content)} bytes")

    except Exception as e:
        print(f"❌ Error during Playwright execution: {e}")

    return None


def fetch_and_build_messages():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(PUNCH_OFFICIAL_RSS, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch Punch RSS. Status: {response.status_code}")
            return None, None
    except Exception as e:
        print(f"Exception fetching RSS: {e}")
        return None, None

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"Failed to parse XML: {e}")
        return None, None

    channel = root.find("channel")
    if channel is None:
        return None, None

    items = channel.findall("item")
    print(f"--- Fetched {len(items)} items from Punch RSS ---")

    if not items:
        return None, None

    # Chat 1: Top 10 Headlines Digest
    intro_header = (
        "Today's Biggest Headlines\n\n"
        "Here are some of the news reports that you shouldn’t miss this morning:\n"
    )
    headline_lines = [intro_header]

    for idx, item in enumerate(items[:10], 1):
        t_elem = item.find("title")
        l_elem = item.find("link")
        t_text = t_elem.text.strip() if t_elem is not None else ""
        l_text = l_elem.text.strip() if l_elem is not None else ""

        headline_lines.append(f"{idx}. {t_text}\n\n=== {l_text}")

    custom_footer = (
        "\n\n------------------------------\n"
        "✨ *Customized Daily Briefing*\n"
        "Have a productive and great day ahead!"
    )

    first_message = "\n\n".join(headline_lines) + custom_footer

    # Chat 2: Official Facebook Page Link
    second_message = (
        "📰 *Official Newspaper Facebook Page*\n\n"
        "Tap here to visit Punch's official Facebook page:\n"
        f"{PUNCH_FB_PAGE_URL}"
    )

    return first_message, second_message


def send_whatsapp_green_api(id_instance, api_token, raw_phones, msg1, msg2, image_bytes):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]
    headers = {"Content-Type": "application/json"}

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"

        # 1. Deliver Original Full-Resolution Image
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Frontpage Cover Image Delivery to ({chat_id}):", res_img.json())

        # 2. Deliver Headlines Digest
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Digest Sent to ({chat_id}):", res1.json())

        # 3. Deliver Facebook Reference Link
        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers)
            print(f"Facebook Reference Link Sent to ({chat_id}):", res2.json())


def main():
    missing = []
    if not ID_INSTANCE:
        missing.append("GREEN_API_ID_INSTANCE")
    if not API_TOKEN:
        missing.append("GREEN_API_TOKEN")
    if not PHONE_NUMBERS:
        missing.append("PHONE_NUMBER")

    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        return

    first_message, second_message = fetch_and_build_messages()

    if not first_message:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, None, None)
        return

    image_bytes = fetch_frontpage_cover_image()

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message, image_bytes)


if __name__ == "__main__":
    main()