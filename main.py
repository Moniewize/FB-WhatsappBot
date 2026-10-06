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


def get_exact_facebook_post_permalink():
    """Extracts the direct permalink of the specific post using public 

    OEmbed/feed mirrors and article cross-references, bypassing login redirects."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    # Method 1: Check Punch's official site for cross-posted Facebook Embed/Permalink tags
    try:
        print("Checking Punch online frontpage section for direct FB embed permalink...")
        resp = requests.get("https://punchng.com/topics/frontpage/", headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, "html.parser")
            # Look for Facebook embed wrappers or direct post links
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "facebook.com" in href and any(k in href for k in ["/posts/", "pfbid", "story_fbid", "/photos/"]):
                    clean_link = href.split("?")[0]
                    print(f"Extracted direct Facebook post link from Punch web: {clean_link}")
                    return clean_link
    except Exception as e:
        print(f"Error checking web cross-reference: {e}")

    # Method 2: Use RSS feed enclosure / source links if Facebook post ID is tagged
    try:
        resp = requests.get(PUNCH_OFFICIAL_RSS, headers=headers, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                desc = item.find("description")
                content = desc.text if desc is not None and desc.text else ""
                fb_match = re.search(r'https://www\.facebook\.com/[^\s"<]+', content)
                if fb_match:
                    found_url = fb_match.group(0).split("?")[0]
                    if any(k in found_url for k in ["/posts/", "pfbid", "story_fbid", "/photos/"]):
                        print(f"Found direct post link in RSS payload: {found_url}")
                        return found_url
    except Exception as e:
        print(f"Error parsing RSS for post link: {e}")

    # Method 3: Direct mobile feed parser with session cookies simulation
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    try:
        res = session.get("https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Fwww.facebook.com%2Fpunchnewspaper&tabs=timeline", timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "punchnewspaper" in href and any(k in href for k in ["/posts/", "pfbid", "story_fbid", "/photos/"]):
                    # Clean relative URL and restore full desktop link format
                    clean_href = href.split("&")[0].replace("m.facebook.com", "www.facebook.com")
                    if not clean_href.startswith("http"):
                        clean_href = f"https://www.facebook.com{clean_href}"
                    print(f"Extracted direct post link from Facebook plugin widget: {clean_href}")
                    return clean_href
    except Exception as e:
        print(f"Error querying Facebook plugin widget: {e}")

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
        "\n\n\n"
        "*Source: The Punch*\n"
        "*Brought by:* RAC-FUTO Editorial Team"
    )

    first_message = "\n\n".join(headline_lines) + custom_footer

    # 2. Message 2: Exact Direct Post Link
    direct_post_url = get_exact_facebook_post_permalink()
    second_message = (
        "📰 *Direct Front-Page Post Link*\n\n"
        "Tap here to view and download today's exact newspaper cover:\n"
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

        # Send Message 1: News headlines and links
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers)
        print(f"Headlines Sent to {chat_id}:", res1.json())

        # Send Message 2: Direct link to the specific post
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