import os
import xml.etree.ElementTree as ET
import requests
from duckduckgo_search import DDGS

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def fetch_frontpage_image():
    """Fetches Punch front page image using DuckDuckGo search."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        print("🌐 Searching DuckDuckGo for Punch front page...")
        with DDGS() as ddgs:
            results = list(ddgs.images("Punch newspaper front page today", max_results=5))

        for item in results:
            img_url = item.get("image")
            print(f"📌 Found image candidate: {img_url}")

            if img_url:
                try:
                    img_res = requests.get(img_url, headers=headers, timeout=15)
                    if img_res.status_code == 200 and len(img_res.content) > 10000:
                        print(f"✅ Downloaded cover image ({len(img_res.content)} bytes)!")
                        return img_res.content
                except Exception as e:
                    print(f"⚠️ Error downloading candidate {img_url}: {e}")

    except Exception as e:
        print(f"⚠️ DuckDuckGo Search Error: {e}")

    print("❌ Scraper Warning: Could not retrieve cover image.")
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

        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            try:
                res_img = requests.post(upload_url, data=payload, files=files, timeout=30)
                print(f"Frontpage Cover Image Delivery to ({chat_id}):", res_img.json())
            except Exception as e:
                print(f"Failed to send image: {e}")

        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers, timeout=15)
        print(f"Headlines Digest Sent to ({chat_id}):", res1.json())

        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers, timeout=15)
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

    image_bytes = fetch_frontpage_image()
    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message, image_bytes)


if __name__ == "__main__":
    main()