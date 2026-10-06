import os
import re
import xml.etree.ElementTree as ET
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"


def extract_cover_image_from_item(item):
    """Extracts the direct cover image URL attached to the daily headlines RSS post."""
    # 1. Check for RSS media enclosure tag (<enclosure url="..." type="image/jpeg" />)
    enclosure = item.find("enclosure")
    if enclosure is None:
        # Search namespace variations for enclosure
        for elem in item:
            if "enclosure" in elem.tag:
                enclosure = elem
                break

    if enclosure is not None:
        img_url = enclosure.get("url")
        if img_url and "uploads" in img_url:
            print(f"🖼️ [DEBUG] Found image in RSS enclosure: {img_url}")
            return img_url

    # 2. Check content:encoded or description HTML body for embedded <img> tags
    for elem in item:
        if "encoded" in elem.tag or "description" in elem.tag:
            html_text = elem.text or ""
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
            for src in img_matches:
                if "uploads" in src and not any(k in src.lower() for k in ["logo", "avatar", "icon", "150x150"]):
                    print(f"🖼️ [DEBUG] Found image embedded in RSS item HTML: {src}")
                    return src

    return None


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

    if not items:
        return None, None, None

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

    first_message = "\n\n".join(headline_lines) + custom_footer

    # Extract attached cover image directly from the headline RSS post
    first_item = items[0]
    cover_image_url = extract_cover_image_from_item(first_item)
    
    first_item_link = first_item.find("link")
    fallback_link = first_item_link.text.strip() if first_item_link is not None else "https://punchng.com"

    image_bytes = None
    if cover_image_url:
        try:
            print(f"🔄 [DEBUG] Downloading image directly from CDN: {cover_image_url}")
            img_res = requests.get(cover_image_url, headers=headers, timeout=15)
            if img_res.status_code == 200 and len(img_res.content) > 5000:
                print(f"✅ Successfully downloaded {len(img_res.content)} bytes of frontpage cover image!")
                image_bytes = img_res.content
        except Exception as img_err:
            print(f"❌ Failed to download cover image binary: {img_err}")

    # Message 2: Link Fallback / Source Reference
    second_message = (
        "📰 *Official Story & Cover Page Link*\n\n"
        "Tap here to view today's lead story and newspaper cover online:\n"
        f"{fallback_link}"
    )

    return first_message, second_message, image_bytes


def send_whatsapp_green_api(id_instance, api_token, raw_phones, msg1, msg2, image_bytes):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        headers = {"Content-Type": "application/json"}

        # Message 1: Send Headlines Digest
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Delivery Status ({chat_id}):", res1.json())

        # Direct Image Upload (if image binary was fetched)
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Front-Page Image Direct Delivery Status ({chat_id}):", res_img.json())

        # Message 2: Send Link Reference Message
        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers)
            print(f"Link Reference Delivery Status ({chat_id}):", res2.json())


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