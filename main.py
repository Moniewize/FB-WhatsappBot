import os
import time
import xml.etree.ElementTree as ET
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

KEYWORDS = [
    "biggest headlines",
    "today's biggest headlines",
    "today’s biggest headlines",
    "news reports that you shouldn",
    "headlines",
]

CUSTOM_FOOTER = (
    "\n\n------------------------------\n"
    "✨ *Customized Daily Briefing*\n"
    "Have a productive and great day ahead!"
)

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FB_PHOTOS_URL = "https://www.facebook.com/punchnewspaper/photos"


def get_facebook_first_cover_image_url():
    """Uses Headless Chrome to render Punch's Facebook page and extract the exact 

    first photo container image URL."""
    print("Launching Headless Chrome browser to fetch Facebook cover image...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=chrome_options)
    img_url = None

    try:
        driver.get(PUNCH_FB_PHOTOS_URL)
        time.sleep(5)  # Allow dynamic JS content to render

        # Look for image tags within Facebook post containers
        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src") or ""
            # Filter out UI icons, profile pictures, and small avatars
            if src and "scontent" in src and "p50x50" not in src and "p160x160" not in src:
                print(f"Extracted direct Facebook cover image container URL: {src}")
                img_url = src
                break
    except Exception as e:
        print(f"Error fetching image via Selenium: {e}")
    finally:
        driver.quit()

    return img_url


def fetch_and_modify_target_post():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(PUNCH_OFFICIAL_RSS, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch Punch RSS. Status code: {response.status_code}")
            return None, None
    except Exception as e:
        print(f"Exception while fetching RSS feed: {e}")
        return None, None

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"Failed to parse XML content: {e}")
        return None, None

    channel = root.find("channel")
    if channel is None:
        print("Invalid RSS feed structure.")
        return None, None

    items = channel.findall("item")
    print(f"--- Punch RSS: Fetched {len(items)} items ---")

    # Fetch the exact newspaper front page image from Facebook container
    cover_image_url = get_facebook_first_cover_image_url()

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

    final_message = "\n\n".join(headline_lines) + CUSTOM_FOOTER
    return final_message, cover_image_url


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message, cover_image_url=None):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    image_bytes = None
    if cover_image_url:
        print(f"Downloading raw image binary from Facebook CDN: {cover_image_url}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        try:
            res = requests.get(cover_image_url, headers=headers, timeout=15)
            if res.status_code == 200:
                image_bytes = res.content
                print(f"Successfully downloaded {len(image_bytes)} bytes of the front page cover.")
            else:
                print(f"Failed to download image. Status code: {res.status_code}")
        except Exception as e:
            print(f"Error downloading image binary: {e}")

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        # 1. Upload uncompressed raw binary image to WhatsApp
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {
                "chatId": chat_id,
                "fileName": "newspaper_frontpage.jpg"
            }
            files = {
                "file": ("newspaper_frontpage.jpg", image_bytes, "image/jpeg")
            }
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Image delivery response to {chat_id}:", res_img.json())

        # 2. Send headlines text message
        headers = {"Content-Type": "application/json"}
        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload_msg = {"chatId": chat_id, "message": message}
        res_msg = requests.post(msg_url, json=payload_msg, headers=headers)
        print(f"Text delivery response to {chat_id}:", res_msg.json())


def main():
    missing = []
    if not ID_INSTANCE:
        missing.append("GREEN_API_ID_INSTANCE")
    if not API_TOKEN:
        missing.append("GREEN_API_TOKEN")
    if not PHONE_NUMBERS:
        missing.append("PHONE_NUMBER")

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        return

    message, cover_image_url = fetch_and_modify_target_post()
    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message, cover_image_url)


if __name__ == "__main__":
    main()