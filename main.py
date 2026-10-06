import os
import xml.etree.ElementTree as ET
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"
FRONTPAGES_PUNCH_URL = "https://www.frontpages.com/the-punch/"


def fetch_frontpage_cover_image():
    """Renders and fetches the full frontpage image from FrontPages using the Microlink headless browser API."""
    microlink_url = f"https://api.microlink.io/?url={FRONTPAGES_PUNCH_URL}&screenshot=true&embed=screenshot.url"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        print(f"🌐 Headless Render: Requesting cover screenshot via Microlink API...")
        res = requests.get(microlink_url, headers=headers, timeout=30)
        print(f"📡 Microlink API Status: {res.status_code}")

        if res.status_code == 200 and len(res.content) > 10000:
            print(f"✅ Successfully captured frontpage image binary ({len(res.content)} bytes)!")
            return res.content
        else:
            print(f"❌ Microlink failed with status {res.status_code} or small payload size.")
    except Exception as e:
        print(f"❌ Error fetching rendered cover image: {e}")

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

        # 1. Deliver Front-Page Image First (if successfully captured)
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Frontpage Cover Image Delivery to ({chat_id}):", res_img.json())

        # 2. Deliver Headlines Digest (Chat 1)
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Digest Sent to ({chat_id}):", res1.json())

        # 3. Deliver Facebook Reference Link (Chat 2)
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

    # Render and fetch cover image binary
    image_bytes = fetch_frontpage_cover_image()

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message, image_bytes)


if __name__ == "__main__":
    main()