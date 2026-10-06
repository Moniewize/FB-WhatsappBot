import os
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FRONTPAGE_WEB = "https://punchng.com/topics/frontpage/"
PUNCH_WP_API = "https://punchng.com/wp-json/wp/v2/posts?per_page=5"


def fetch_punch_frontpage_image():
    """Extracts the direct front-page cover image binary from Punch's official site

    to bypass Facebook's IP/bot restrictions entirely.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }

    session = requests.Session()
    session.headers.update(headers)

    # Strategy 1: Query Punch's WordPress REST API for Featured Image Media
    try:
        print("🔄 [DEBUG] Fetching post metadata from Punch WP API...")
        res = session.get(PUNCH_WP_API, timeout=12)
        if res.status_code == 200:
            posts = res.json()
            for post in posts:
                # Look for frontpage or headline posts
                title = post.get("title", {}).get("rendered", "")
                if "frontpage" in title.lower() or "headlines" in title.lower():
                    # Get media ID or jetpack featured media URL
                    img_url = post.get("jetpack_featured_media_url")
                    if img_url:
                        print(f"🖼️ [DEBUG] Found image via WP API: {img_url}")
                        img_res = session.get(img_url, timeout=12)
                        if img_res.status_code == 200 and len(img_res.content) > 10000:
                            return img_res.content, img_url
    except Exception as e:
        print(f"❌ [DEBUG] WP API error: {e}")

    # Strategy 2: Web scrape Punch Frontpage Topic Page
    try:
        print(f"🔄 [DEBUG] Scraping Punch frontpage section: {PUNCH_FRONTPAGE_WEB}")
        res = session.get(PUNCH_FRONTPAGE_WEB, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, "html.parser")
            
            # Find the main article card image
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if "uploads" in src and not any(k in src for k in ["logo", "avatar", "150x150", "50x50"]):
                    print(f"🖼️ [DEBUG] Found web cover image: {src}")
                    img_res = session.get(src, timeout=12)
                    if img_res.status_code == 200 and len(img_res.content) > 10000:
                        return img_res.content, src
    except Exception as e:
        print(f"❌ [DEBUG] Web scrape error: {e}")

    print("⚠️ [DEBUG] Could not retrieve image binary from Punch web source.")
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

    # Message 1: Top 10 Headlines
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

    # Fetch cover photo binary from Punch
    image_bytes, image_url = fetch_punch_frontpage_image()

    # Message 2: Fallback / Photo Source Link
    second_message = (
        "📰 *Official Newspaper Cover Link*\n\n"
        "View today's cover page online:\n"
        f"{image_url if image_url else PUNCH_FRONTPAGE_WEB}"
    )

    return first_message, second_message, image_bytes


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

        # 1. Send News Headlines Block
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Delivery Status ({chat_id}):", res1.json())

        # 2. Upload and send Image Binary directly to WhatsApp
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Front-Page Image Direct Upload Status ({chat_id}):", res_img.json())

        # 3. Send Link Chat
        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers)
            print(f"Post Link Delivery Status ({chat_id}):", res2.json())


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

    msg1, msg2, image_bytes = fetch_and_build_content()

    if not msg1:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, "", None)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, msg1, msg2, image_bytes)


if __name__ == "__main__":
    main()