import os
import requests
import xml.etree.ElementTree as ET

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

# Punch RSS Featured Category Endpoint (Curated Editor Choices)
RSS_URL = "https://rss.punchng.com/v1/category/featured"


def fetch_punch_featured_stories(limit=10):
    """Fetches and parses curated editor lead stories from Punch RSS XML feed."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(RSS_URL, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ Failed to fetch RSS XML. HTTP Status Code: {response.status_code}")
            return []

        # Parse XML tree
        root = ET.fromstring(response.content)
        items = root.findall("./channel/item")

        stories = []
        for item in items[:limit]:
            title_node = item.find("title")
            link_node = item.find("link")

            title = title_node.text.strip() if title_node is not None and title_node.text else ""
            link = link_node.text.strip() if link_node is not None and link_node.text else ""

            if title and link:
                stories.append({"title": title, "link": link})

        return stories

    except Exception as e:
        print(f"❌ Error while fetching RSS feed: {e}")
        return []


def build_whatsapp_message(stories):
    """Formats headlines and appends custom footer."""
    if not stories:
        return None

    header = "*Today's Biggest Headlines*\n\nHere are some of the news reports that you shouldn’t miss this morning:\n\n"
    body = ""

    for idx, story in enumerate(stories, 1):
        body += f"{idx}. {story['title']}\n=== {story['link']}\n\n"

    footer = (
        " \n"
        "*Source*: The Punch\n"
        "*Brought by:*  RAC-FUTO Editorial Team !"
    )

    return header + body + footer


def send_whatsapp_via_green_api(id_instance, api_token, raw_phones, message):
    """Sends WhatsApp message to all recipient numbers stored in environment secret."""
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]
    headers = {"Content-Type": "application/json"}

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")
        
        # Determine if recipient is a group (@g.us) or individual (@c.us)
        if "@g.us" in clean_recipient or "@c.us" in clean_recipient:
            chat_id = clean_recipient
        else:
            chat_id = f"{clean_recipient}@c.us"

        api_endpoint = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload = {"chatId": chat_id, "message": message}

        try:
            res = requests.post(api_endpoint, json=payload, headers=headers, timeout=15)
            print(f"✅ Delivered to ({chat_id}):", res.json())
        except Exception as e:
            print(f"❌ Transmission Error for ({chat_id}): {e}")


def main():
    # Validate required secrets
    missing_secrets = []
    if not ID_INSTANCE:
        missing_secrets.append("GREEN_API_ID_INSTANCE")
    if not API_TOKEN:
        missing_secrets.append("GREEN_API_TOKEN")
    if not PHONE_NUMBERS:
        missing_secrets.append("PHONE_NUMBER")

    if missing_secrets:
        print(f"❌ Critical Error: Missing environment variables: {', '.join(missing_secrets)}")
        return

    print("🔍 Fetching today's featured headlines from Punch...")
    stories = fetch_punch_featured_stories(limit=10)

    if not stories:
        print("❌ Could not extract any headlines from RSS feed.")
        return

    message = build_whatsapp_message(stories)
    print("📤 Sending WhatsApp broadcast via Green API...")
    send_whatsapp_via_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message)


if __name__ == "__main__":
    main()