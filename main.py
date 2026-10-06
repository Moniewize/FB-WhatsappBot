import os
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

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


def fetch_newspaper_frontpage_image(first_item_link=None):
    """Attempts to scrape Punch's print frontpage cover photo. 
    Falls back to the lead article's photo if print cover isn't found."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
    }

    # 1. Check Punch's frontpage topics for an og:image or cover image
    urls_to_check = [
        "https://punchng.com/topics/frontpage/",
        "https://punchng.com/",
    ]

    for site_url in urls_to_check:
        try:
            resp = requests.get(site_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                
                # Check meta og:image tags
                og_img = soup.find("meta", property="og:image")
                if og_img and og_img.get("content") and "logo" not in og_img["content"].lower():
                    print(f"Found front-page meta image: {og_img['content']}")
                    return og_img["content"]

                # Check featured image tags
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    if src and any(term in src.lower() for term in ["frontpage", "cover", "paper", "edition"]):
                        print(f"Found front-page img tag: {src}")
                        return src
        except Exception as e:
            print(f"Error checking {site_url}: {e}")

    # 2. Fallback: Scrape og:image directly from the lead news story
    if first_item_link:
        print(f"Checking lead article page for cover photo: {first_item_link}")
        try:
            resp = requests.get(first_item_link, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                og_img = soup.find("meta", property="og:image")
                if og_img and og_img.get("content"):
                    print(f"Found lead article og:image: {og_img['content']}")
                    return og_img["content"]
        except Exception as e:
            print(f"Error scraping lead article image: {e}")

    return None


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
        print("Invalid RSS feed structure (no channel element found).")
        return None, None

    items = channel.findall("item")
    print(f"--- Punch Native RSS: Fetched {len(items)} items ---")

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

    # Aggregate top 10 headlines matching exact Punch format
    if target_item is None and len(items) >= 5:
        print("Generating structured headline digest matching Punch layout...")
        intro_header = (
            "Today's Biggest Headlines\n\n"
            "Here are some of the news reports that you shouldn’t miss this morning:\n"
        )
        headline_lines = [intro_header]
        first_article_link = None

        for idx, item in enumerate(items[:10], 1):
            t_elem = item.find("title")
            l_elem = item.find("link")
            t_text = t_elem.text.strip() if t_elem is not None else ""
            l_text = l_elem.text.strip() if l_elem is not None else ""

            if idx == 1:
                first_article_link = l_text

            headline_lines.append(f"{idx}. {t_text}\n\n=== {l_text}")

        # Fetch front-page image or fallback to lead story cover photo
        cover_image_url = fetch_newspaper_frontpage_image(first_article_link)

        final_message = "\n\n".join(headline_lines) + CUSTOM_FOOTER
        return final_message, cover_image_url

    if target_item is None:
        print("Target headline post not found in RSS feed.")
        return None, None

    # Processing matched post
    title_elem = target_item.find("title")
    desc_elem = target_item.find("description")
    link_elem = target_item.find("link")

    post_text = desc_elem.text if desc_elem is not None and desc_elem.text else ""
    if not post_text:
        post_text = title_elem.text if title_elem is not None else ""

    link_text = link_elem.text if link_elem is not None else ""
    cover_image_url = fetch_newspaper_frontpage_image(link_text)

    paragraphs = [p.strip() for p in post_text.split("\n") if p.strip()]

    if len(paragraphs) > 1:
        paragraphs = paragraphs[:-1]

    cleaned_body = "\n\n".join(paragraphs)
    final_message = f"{cleaned_body}{CUSTOM_FOOTER}"

    return final_message, cover_image_url


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message, cover_image_url=None):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    image_bytes = None
    if cover_image_url:
        print(f"Downloading cover image directly from: {cover_image_url}")
        try:
            res = requests.get(cover_image_url, timeout=15)
            if res.status_code == 200:
                image_bytes = res.content
            else:
                print(f"Failed to download image. Status: {res.status_code}")
        except Exception as e:
            print(f"Error downloading cover image: {e}")
    else:
        print("No image URL resolved. Skipping image transmission.")

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        # Step 1: Upload and send raw cover image binary
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
            print(f"Front-Page Image Sent to {chat_id} - Response:", res_img.json())

        # Step 2: Send complete text block + links + custom footer
        headers = {"Content-Type": "application/json"}
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
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        return

    message, cover_image_url = fetch_and_modify_target_post()

    if not message:
        fallback_msg = (
            "⚠️️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message, cover_image_url)


if __name__ == "__main__":
    main()