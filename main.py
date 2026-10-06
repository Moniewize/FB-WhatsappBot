import os
import re
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

PUNCH_OFFICIAL_RSS = "https://rss.punchng.com/v1/category/latest_news"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def get_direct_facebook_post_url():
    """Scrapes mobile Facebook to extract the exact URL of the latest 

    'Album Frontpage' / 'Today's Biggest Headlines' post."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    mobile_urls = [
        "https://m.facebook.com/punchnewspaper",
        "https://mbasic.facebook.com/punchnewspaper",
    ]

    for url in mobile_urls:
        try:
            print(f"Searching for direct post URL on: {url}")
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")

                # Find post permalinks (stories, photos/album, or story.php)
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]

                    # Match direct Facebook post, photo album, or story paths
                    if any(p in href for p in ["/posts/", "/photos/", "story.php", "/permalink/"]):
                        # Clean up relative pathing to form a canonical desktop Facebook URL
                        if href.startswith("/"):
                            full_url = f"https://www.facebook.com{href}"
                        else:
                            full_url = href

                        # Remove tracking parameters for a clean link
                        clean_url = full_url.split("?")[0].replace("m.facebook.com", "www.facebook.com").replace("mbasic.facebook.com", "www.facebook.com")
                        
                        # Verify link belongs to the Punch page post
                        if "punchnewspaper" in clean_url or "story.php" in href:
                            print(f"Extracted direct Facebook post link: {clean_url}")
                            return clean_url
        except Exception as e:
            print(f"Error fetching direct post link from {url}: {e}")

    # Fallback to general page if exact post permalink couldn't be parsed
    return PUNCH_FB_PAGE_URL


def fetch_and_build_messages():
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

    # 1. Message 1: Top 10 Headlines Digest
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

    # 2. Message 2: Exact Direct Post Link
    direct_post_url = get_direct_facebook_post_url()
    second_message = (
        "📰 *Direct Facebook Front-Page Post Link*\n\n"
        "Tap here to view and download today's exact newspaper front-page cover:\n"
        f"{direct_post_url}"
    )

    return first_message, second_message


def send_whatsapp_green_api(id_instance, api_token, raw_phones, msg1, msg2):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]
    headers = {"Content-Type": "application/json"}

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")

        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"

        # Send Chat 1: News headlines and links
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Sent to {chat_id}:", res1.json())

        # Send Chat 2: Direct link to the specific Facebook post
        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers)
            print(f"Direct Post Link Sent to {chat_id}:", res2.json())


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
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, None)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message)


if __name__ == "__main__":
    main()