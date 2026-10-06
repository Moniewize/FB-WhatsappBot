import os
import re
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
FB_COOKIE = os.getenv("FB_COOKIE")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def get_facebook_content():
    """Attempts to download direct front-page image bytes using session cookies.

    If binary download fails, returns the best resolved post link as a fallback.
    """
    if not FB_COOKIE:
        print("⚠️ [DEBUG] FB_COOKIE environment variable is empty or missing.")
        return None, PUNCH_FB_PAGE_URL

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Cookie": FB_COOKIE.strip(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    session = requests.Session()
    session.headers.update(headers)

    fb_target_urls = [
        "https://mbasic.facebook.com/punchnewspaper/photos",
        "https://m.facebook.com/punchnewspaper/photos",
        "https://mbasic.facebook.com/punchnewspaper",
    ]

    extracted_post_link = PUNCH_FB_PAGE_URL

    for fb_url in fb_target_urls:
        try:
            print(f"🔄 [DEBUG] Attempting authenticated GET: {fb_url}")
            resp = session.get(fb_url, timeout=15)
            print(f"ℹ️ [DEBUG] HTTP Status Code: {resp.status_code}")

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")

                # Check if Facebook threw a checkpoint/login redirection
                if "checkpoint" in resp.url or "login" in resp.url:
                    print("❌ [DEBUG] Facebook redirected to login/checkpoint wall. Cookie may be invalid or expired.")

                # Extract potential direct post permalinks for link fallback
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    if any(k in href for k in ["/photos/", "/posts/", "story.php", "pfbid"]):
                        clean_href = href.split("&")[0].replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
                        if not clean_href.startswith("http"):
                            clean_href = f"https://www.facebook.com{clean_href}"
                        extracted_post_link = clean_href
                        print(f"📌 [DEBUG] Found direct post permalink: {extracted_post_link}")
                        break

                # Extract direct CDN image binary
                for img in soup.find_all("img"):
                    src = img.get("src") or ""
                    if "scontent" in src and not any(
                        s in src for s in ["p50x50", "p100x100", "p160x160", "s480x480", "p180x180"]
                    ):
                        high_res_url = re.sub(r"s\d+x\d+/", "", src)
                        print(f"🖼️ [DEBUG] Direct CDN image URL isolated: {high_res_url}")

                        img_resp = session.get(high_res_url, timeout=15)
                        if img_resp.status_code == 200 and len(img_resp.content) > 10000:
                            print(f"✅ [DEBUG] Successfully downloaded {len(img_resp.content)} bytes of frontpage image.")
                            return img_resp.content, extracted_post_link

        except Exception as e:
            print(f"❌ [DEBUG] Exception during fetch from {fb_url}: {e}")

    print("⚠️ [DEBUG] Could not download image binary. Returning post link as fallback.")
    return None, extracted_post_link


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
            return None, None, None, None
    except Exception as e:
        print(f"Exception fetching RSS: {e}")
        return None, None, None, None

    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"Failed to parse XML: {e}")
        return None, None, None, None

    channel = root.find("channel")
    if channel is None:
        return None, None, None, None

    items = channel.findall("item")
    print(f"--- Fetched {len(items)} items from Punch RSS ---")

    # Message 1: News Headlines
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

    # Fetch image bytes and Facebook post link
    image_bytes, direct_post_link = get_facebook_content()

    # Message 2 (Fallback message if image is not downloaded or alongside link)
    second_message = (
        "📰 *Direct Front-Page Facebook Post Link*\n\n"
        "Tap here to view and download today's exact newspaper cover:\n"
        f"{direct_post_link}"
    )

    return first_message, second_message, image_bytes, direct_post_link


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

        # 1. Send Chat 1: News Headlines Digest
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Delivery Status ({chat_id}):", res1.json())

        # 2. Attempt Image Upload if binary was successfully downloaded
        if image_bytes:
            upload_url = f"https://api.green-api.com/waInstance{id_instance}/sendFileByUpload/{api_token}"
            payload = {"chatId": chat_id, "fileName": "frontpage_cover.jpg"}
            files = {"file": ("frontpage_cover.jpg", image_bytes, "image/jpeg")}
            res_img = requests.post(upload_url, data=payload, files=files)
            print(f"Front-Page Image Direct Upload Status ({chat_id}):", res_img.json())

        # 3. Send Chat 2: Direct Facebook Post Link (Ensures you ALWAYS get the link)
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

    msg1, msg2, image_bytes, _ = fetch_and_build_content()

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