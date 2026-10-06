import os
import re
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
FB_COOKIE = os.getenv("FB_COOKIE")  # Session cookies for Facebook authentication

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"


def download_facebook_frontpage_image():
    """Uses logged-in session cookies to access Facebook's mobile layout, 

    extract the raw high-res front-page photo, and download its binary bytes."""
    if not FB_COOKIE:
        print("FB_COOKIE secret is missing. Cannot authenticate with Facebook.")
        return None, None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Cookie": FB_COOKIE,
        "Accept-Language": "en-US,en;q=0.9",
    }

    session = requests.Session()
    session.headers.update(headers)

    fb_target_urls = [
        "https://mbasic.facebook.com/punchnewspaper/photos",
        "https://m.facebook.com/punchnewspaper/photos",
        "https://mbasic.facebook.com/punchnewspaper",
    ]

    for fb_url in fb_target_urls:
        try:
            print(f"Authenticated request to Facebook container: {fb_url}")
            resp = session.get(fb_url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")

                # Find direct CDN photo links inside post container
                for img in soup.find_all("img"):
                    src = img.get("src") or ""
                    # Filter out avatars, icons, and low-res thumbnails
                    if "scontent" in src and not any(
                        s in src for s in ["p50x50", "p100x100", "p160x160", "s480x480"]
                    ):
                        # Clean CDN dimensions to get full high-res cover image
                        high_res_url = re.sub(r"s\d+x\d+/", "", src)
                        print(f"Direct high-res photo URL extracted: {high_res_url}")

                        # Download raw image bytes using authenticated session
                        img_resp = session.get(high_res_url, timeout=15)
                        if img_resp.status_code == 200 and len(img_resp.content) > 10000:
                            print(f"Successfully downloaded {len(img_resp.content)} bytes of front-page image.")
                            return img_resp.content, high_res_url
        except Exception as e:
            print(f"Error downloading photo from {fb_url}: {e}")

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
            return None, None, None
    except Exception as e:
        print(f"Exception fetching RSS: {e}")
        return None, None, None

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"Failed to parse XML: {e}")
        return None, None, None

    channel = root.find("channel")
    if channel is None:
        return None, None, None

    items = channel.findall("item")
    print(f"--- Fetched {len(items)} items from Punch RSS ---")

    # Format the top 10 headlines text block
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
        " *Source:* The Punch\n"
        "*Brought by:* RAC-FUTO Editorial Team"
    )

    message_text = "\n\n".join(headline_lines) + custom_footer

    # Download front-page photo binary using authenticated session
    image_bytes, image_url = download_facebook_frontpage_image()

    return message_text, image_bytes, image_url


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message, image_bytes, image_url):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        # 1. Directly upload and send the front-page photo binary to WhatsApp
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {
                "chatId": chat_id,
                "fileName": "punch_frontpage.jpg"
            }
            files = {
                "file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")
            }
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Front-Page Image Direct Upload to {chat_id}:", res_img.json())

        # 2. Send news headlines text block
        headers = {"Content-Type": "application/json"}
        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload_msg = {"chatId": chat_id, "message": message}
        res_msg = requests.post(msg_url, json=payload_msg, headers=headers)
        print(f"Text Headlines Delivery to {chat_id}:", res_msg.json())


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

    message_text, image_bytes, image_url = fetch_and_build_content()

    if not message_text:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, None, None)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message_text, image_bytes, image_url)


if __name__ == "__main__":
    main()