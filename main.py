import os
import urllib.parse
import xml.etree.ElementTree as ET
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "punchnewspaper")

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


def fetch_and_modify_target_post(page_name):
    # Fetch RSS XML directly from rss.app without third-party converters
    rss_url = f"https://rss.app/feeds/v1/facebook/{page_name}.xml"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(rss_url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(
                f"Failed to fetch direct RSS XML. Status code: {response.status_code}"
            )
            return None, None
    except Exception as e:
        print(f"Exception while fetching RSS feed: {e}")
        return None, None

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"Failed to parse XML content: {e}")
        return None, None

    # Standard RSS items are inside <channel><item>...
    channel = root.find("channel")
    if channel is None:
        print("Invalid RSS feed structure (no channel element found).")
        return None, None

    items = channel.findall("item")
    print(f"--- Direct XML Debug: Fetched {len(items)} items ---")

    target_item = None
    for item in items:
        title_elem = item.find("title")
        desc_elem = item.find("description")

        title = title_elem.text if title_elem is not None else ""
        desc = desc_elem.text if desc_elem is not None else ""

        full_content = (desc or title).lower()

        if any(keyword in full_content for keyword in KEYWORDS):
            target_item = item
            break

    if target_item is None:
        print("Target headline post not matched in current direct XML feed.")
        return None, None

    # Extract text & link
    title_elem = target_item.find("title")
    desc_elem = target_item.find("description")
    link_elem = target_item.find("link")

    post_text = (
        desc_elem.text if desc_elem is not None and desc_elem.text else ""
    )
    if not post_text:
        post_text = title_elem.text if title_elem is not None else ""

    link = link_elem.text if link_elem is not None else ""

    # Extract cover image from media:content or enclosure tags
    cover_image = None
    # Check media:content / media:thumbnail
    namespaces = {
        "media": "http://search.yahoo.com/mrss/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    media_content = target_item.find("media:content", namespaces)
    media_thumbnail = target_item.find("media:thumbnail", namespaces)
    enclosure = target_item.find("enclosure")

    if media_content is not None and media_content.attrib.get("url"):
        cover_image = media_content.attrib.get("url")
    elif media_thumbnail is not None and media_thumbnail.attrib.get("url"):
        cover_image = media_thumbnail.attrib.get("url")
    elif enclosure is not None and enclosure.attrib.get("url"):
        cover_image = enclosure.attrib.get("url")

    # Format body paragraphs
    paragraphs = [p.strip() for p in post_text.split("\n") if p.strip()]

    # Strip the original bottom paragraph (footer link)
    if len(paragraphs) > 1:
        paragraphs = paragraphs[:-1]

    cleaned_body = "\n\n".join(paragraphs)
    final_message = f"{cleaned_body}\n\n🔗 *Full Post:* {link}{CUSTOM_FOOTER}"

    return final_message, cover_image


def send_whatsapp_green_api(
    id_instance, api_token, raw_phones, message, cover_image=None
):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        headers = {"Content-Type": "application/json"}

        if cover_image:
            url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUrl/{api_token}"
            payload = {
                "chatId": chat_id,
                "urlFile": cover_image,
                "fileName": "cover_page.jpg",
                "caption": message,
            }
        else:
            url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
            payload = {"chatId": chat_id, "message": message}

        response = requests.post(url, json=payload, headers=headers)
        print(f"Sent to {chat_id} - Response:", response.json())


def main():
    missing = []
    if not ID_INSTANCE:
        missing.append("GREEN_API_ID_INSTANCE")
    if not API_TOKEN:
        missing.append("GREEN_API_TOKEN")
    if not PHONE_NUMBERS:
        missing.append("PHONE_NUMBER")

    if missing:
        print(
            f"Error: Missing required environment variables: {', '.join(missing)}"
        )
        return

    message, cover_image = fetch_and_modify_target_post(FB_PAGE_NAME)

    if not message:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(
            ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg
        )
        return

    send_whatsapp_green_api(
        ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message, cover_image
    )


if __name__ == "__main__":
    main()