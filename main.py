import os
import urllib.parse
import xml.etree.ElementTree as ET
import requests

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


def fetch_and_modify_target_post():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(PUNCH_OFFICIAL_RSS, headers=headers, timeout=15)
        if response.status_code != 200:
            print(
                f"Failed to fetch Punch RSS. Status code: {response.status_code}"
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

    channel = root.find("channel")
    if channel is None:
        print("Invalid RSS feed structure (no channel element found).")
        return None, None

    items = channel.findall("item")
    print(f"--- Punch Native RSS: Fetched {len(items)} items ---")

    target_item = None
    # 1. Search top feed items for morning digest match
    for item in items:
        title_elem = item.find("title")
        desc_elem = item.find("description")

        title = title_elem.text if title_elem is not None else ""
        desc = desc_elem.text if desc_elem is not None else ""

        full_content = (desc or title).lower()

        if any(keyword in full_content for keyword in KEYWORDS):
            target_item = item
            break

    # 2. Fallback: Aggregate top 10 news stories into exact Punch layout
    if target_item is None and len(items) >= 5:
        print("Generating structured headline digest matching Punch layout...")
        intro_header = (
            "Today's Biggest Headlines\n\n"
            "Here are some of the news reports that you shouldn’t miss this morning:\n"
        )
        headline_lines = [intro_header]
        cover_image = None

        namespaces = {
            "media": "http://search.yahoo.com/mrss/",
            "content": "http://purl.org/rss/1.0/modules/content/",
        }

        for idx, item in enumerate(items[:10], 1):
            t_elem = item.find("title")
            l_elem = item.find("link")
            t_text = t_elem.text.strip() if t_elem is not None else ""
            l_text = l_elem.text.strip() if l_elem is not None else ""

            headline_lines.append(f"{idx}. {t_text}\n\n=== {l_text}")

            # Grab image from first story
            if idx == 1:
                media_content = item.find("media:content", namespaces)
                enclosure = item.find("enclosure")
                if (
                    media_content is not None
                    and media_content.attrib.get("url")
                ):
                    cover_image = media_content.attrib.get("url")
                elif enclosure is not None and enclosure.attrib.get("url"):
                    cover_image = enclosure.attrib.get("url")

        final_message = "\n\n".join(headline_lines) + CUSTOM_FOOTER
        return final_message, cover_image

    if target_item is None:
        print("Target headline post not found in RSS feed.")
        return None, None

    # Processing matched digest item directly
    title_elem = target_item.find("title")
    desc_elem = target_item.find("description")
    link_elem = target_item.find("link")

    post_text = (
        desc_elem.text if desc_elem is not None and desc_elem.text else ""
    )
    if not post_text:
        post_text = title_elem.text if title_elem is not None else ""

    cover_image = None
    namespaces = {
        "media": "http://search.yahoo.com/mrss/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    media_content = target_item.find("media:content", namespaces)
    enclosure = target_item.find("enclosure")

    if media_content is not None and media_content.attrib.get("url"):
        cover_image = media_content.attrib.get("url")
    elif enclosure is not None and enclosure.attrib.get("url"):
        cover_image = enclosure.attrib.get("url")

    paragraphs = [p.strip() for p in post_text.split("\n") if p.strip()]

    # Strip last paragraph (original footer link)
    if len(paragraphs) > 1:
        paragraphs = paragraphs[:-1]

    cleaned_body = "\n\n".join(paragraphs)
    final_message = f"{cleaned_body}{CUSTOM_FOOTER}"

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

        # Step 1: Send Image with short headline title
        if cover_image:
            file_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUrl/{api_token}"
            payload_image = {
                "chatId": chat_id,
                "urlFile": cover_image,
                "fileName": "cover_page.jpg",
                "caption": "Today's Biggest Headlines",
            }
            res_img = requests.post(
                file_url, json=payload_image, headers=headers
            )
            print(f"Image Sent to {chat_id} - Response:", res_img.json())

        # Step 2: Send complete headlines, links, and custom footer in full text message
        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload_msg = {"chatId": chat_id, "message": message}
        res_msg = requests.post(msg_url, json=payload_msg, headers=headers)
        print(f"Full Text Sent to {chat_id} - Response:", res_msg.json())


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

    message, cover_image = fetch_and_modify_target_post()

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