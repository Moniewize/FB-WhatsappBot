import os
import xml.etree.ElementTree as ET
import requests
from playwright.sync_api import sync_playwright

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FRONTPAGE_URL = "https://punchng.com/topics/frontpage/"


def capture_frontpage_with_playwright():
    """Launches a real headless browser with Playwright to render the front-page section

    and extract the high-resolution cover image binary directly from the DOM.
    """
    print("🚀 Launching Headless Chromium with Playwright...")
    try:
        with sync_playwright() as p:
            # Launch Chromium with a realistic desktop viewport
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            print(f"🌐 Navigating to: {PUNCH_FRONTPAGE_URL}")
            page.goto(PUNCH_FRONTPAGE_URL, wait_until="networkidle", timeout=30000)

            # Wait explicitly for post card image elements to load in the DOM
            page.wait_for_selector("article img", timeout=15000)

            # Extract the main front-page image element
            img_element = page.query_selector("article img")

            if img_element:
                img_url = img_element.get_attribute("src") or img_element.get_attribute("data-src")
                print(f"🖼️ Found rendered front-page image URL: {img_url}")

                # Take an exact screenshot of the image element itself
                image_bytes = img_element.screenshot()
                browser.close()

                if image_bytes and len(image_bytes) > 5000:
                    print(f"✅ Successfully captured {len(image_bytes)} bytes of cover photo!")
                    return image_bytes, img_url

            browser.close()
    except Exception as e:
        print(f"❌ Playwright execution error: {e}")

    return None, None


def fetch_and_build_content():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
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

    # Message 1: Top 10 Headlines Digest
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

    message_text = "\n\n".join(headline_lines) + custom_footer

    # Capture front-page photo binary with Playwright
    image_bytes, _ = capture_frontpage_with_playwright()

    return message_text, image_bytes


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message_text, image_bytes):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        # 1. Send the rendered Cover Image directly to WhatsApp (if captured)
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Front-Page Image Direct Delivery ({chat_id}):", res_img.json())

        # 2. Send the Top 10 Headlines block
        headers = {"Content-Type": "application/json"}
        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        res_msg = requests.post(msg_url, json={"chatId": chat_id, "message": message_text}, headers=headers)
        print(f"Headlines Delivery ({chat_id}):", res_msg.json())


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

    message_text, image_bytes = fetch_and_build_content()

    if not message_text:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, None)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message_text, image_bytes)


if __name__ == "__main__":
    main()