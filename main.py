import os
import re
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
FRONTPAGES_PUNCH_URL = "https://www.frontpages.com/the-punch/"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def fetch_frontpage_cover_image():
    """Scrapes frontpages.com/the-punch/ for the daily newspaper cover image URL and downloads the binary."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        print(f"🌐 Scraper: Fetching cover page from {FRONTPAGES_PUNCH_URL}...")
        response = requests.get(FRONTPAGES_PUNCH_URL, headers=headers, timeout=15)
        print(f"📡 FrontPages HTTP Status: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Failed to reach FrontPages. Status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        target_img_url = None

        # Method 1: Look for <a> links wrapping the cover image that point to .jpg/.png files
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if re.search(r"\.(jpg|jpeg|png)($|\?)", href, re.IGNORECASE):
                # Filter out small UI icons/logos
                if not any(skip in href.lower() for skip in ["logo", "icon", "avatar", "banner"]):
                    target_img_url = href
                    print(f"🖼️ Found cover image link in <a> tag: {target_img_url}")
                    break

        # Method 2: If no <a> link found, inspect all <img> tags for src, srcset, or data-src
        if not target_img_url:
            for img in soup.find_all("img"):
                # Check src, data-src, or first URL in srcset
                src = img.get("src") or img.get("data-src") or ""
                srcset = img.get("srcset") or ""

                candidates = [src]
                if srcset:
                    # extract URLs from srcset attribute (e.g. "image.jpg 1024w, image-small.jpg 300w")
                    candidates.extend([item.strip().split()[0] for item in srcset.split(",") if item.strip()])

                for url in candidates:
                    if url and re.search(r"\.(jpg|jpeg|png)", url, re.IGNORECASE):
                        if not any(skip in url.lower() for skip in ["logo", "icon", "avatar", "150x150"]):
                            target_img_url = url
                            print(f"🖼️ Found cover image in <img> tag: {target_img_url}")
                            break
                if target_img_url:
                    break

        if not target_img_url:
            print("❌ Scraper Warning: Could not locate cover image element on FrontPages!")
            return None

        # Download the cover image binary
        print(f"🔄 Downloading image binary from: {target_img_url}")
        img_res = requests.get(target_img_url, headers=headers, timeout=20)
        
        if img_res.status_code == 200 and len(img_res.content) > 5000:
            print(f"✅ Successfully downloaded {len(img_res.content)} bytes of frontpage cover image!")
            return img_res.content
        else:
            print(f"❌ Image download failed. Status: {img_res.status_code}, Length: {len(img_res.content)} bytes")

    except Exception as e:
        print(f"❌ Error scraping FrontPages cover image: {e}")

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

    # Chat 2: Facebook Link Reference
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

        # 1. Deliver FrontPages Cover Photo (if successfully fetched)
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "punch_frontpage.jpg"}
            files = {"file": ("punch_frontpage.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"FrontPages Cover Image Sent to ({chat_id}):", res_img.json())

        # 2. Deliver Headlines Digest (Chat 1)
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Digest Sent to ({chat_id}):", res1.json())

        # 3. Deliver Facebook Link Reference (Chat 2)
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

    # Fetch the image binary from FrontPages
    image_bytes = fetch_frontpage_cover_image()

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message, image_bytes)


if __name__ == "__main__":
    main()