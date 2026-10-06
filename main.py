import os
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"


def get_frontpage_cover_image_url():
    """Scrapes Punch's official frontpage topic page to extract the direct 

    high-res frontpage cover image URL."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    target_pages = [
        "https://punchng.com/topics/frontpage/",
        "https://punchng.com/",
    ]

    for page_url in target_pages:
        try:
            print(f"Checking for front-page image on: {page_url}")
            resp = requests.get(page_url, headers=headers, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")

                # Look for image tags with frontpage keywords
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    alt = img.get("alt") or ""
                    if src and any(
                        k in src.lower() or k in alt.lower()
                        for k in ["frontpage", "front-page", "cover", "newspaper-front"]
                    ):
                        print(f"Found newspaper cover image: {src}")
                        return src

                # Fallback: Extract meta og:image from the frontpage section
                og_img = soup.find("meta", property="og:image")
                if og_img and og_img.get("content"):
                    content_url = og_img["content"]
                    if "logo" not in content_url.lower():
                        print(f"Found frontpage og:image: {content_url}")
                        return content_url
        except Exception as e:
            print(f"Error checking {page_url}: {e}")

    return None


def fetch_and_modify_target_post():
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

    # Extract high-res cover image URL
    cover_image_url = get_frontpage_cover_image_url()

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

    body_text = "\n\n".join(headline_lines)

    # Add direct download link fallback at the bottom of the message
    if cover_image_url:
        link_fallback_section = (
            f"\n\n🖼 *Direct Front-Page Cover Link:*\n{cover_image_url}"
        )
    else:
        link_fallback_section = (
            "\n\n🖼 *Front-Page Cover Link:*\nhttps://punchng.com/topics/frontpage/"
        )

    custom_footer = (
        "\n\n------------------------------\n"
        "✨ *Customized Daily Briefing*\n"
        "Have a productive and great day ahead!"
    )

    final_message = f"{body_text}{link_fallback_section}{custom_footer}"
    return final_message, cover_image_url


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message, cover_image_url=None):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    # Download raw image bytes into memory first
    image_bytes = None
    if cover_image_url:
        print(f"Downloading cover image directly from: {cover_image_url}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }
        try:
            res = requests.get(cover_image_url, headers=headers, timeout=15)
            if res.status_code == 200:
                image_bytes = res.content
                print(f"Successfully downloaded {len(image_bytes)} image bytes.")
            else:
                print(f"Image download failed. Status code: {res.status_code}")
        except Exception as e:
            print(f"Error downloading image binary: {e}")

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        # 1. Direct file upload to WhatsApp
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {
                "chatId": chat_id,
                "fileName": "punch_front_page.jpg"
            }
            files = {
                "file": ("punch_front_page.jpg", image_bytes, "image/jpeg")
            }
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Image upload status ({chat_id}):", res_img.json())

        # 2. Text message with headline links and direct image URL fallback
        headers = {"Content-Type": "application/json"}
        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload_msg = {"chatId": chat_id, "message": message}
        res_msg = requests.post(msg_url, json=payload_msg, headers=headers)
        print(f"Text message status ({chat_id}):", res_msg.json())


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