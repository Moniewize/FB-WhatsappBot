import os
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

# Featured RSS feed contains Punch's curated editor choices/lead stories
RSS_FEATURED_URL = "https://rss.punchng.com/v1/category/featured"
PUNCH_HOMEPAGE_URL = "https://punchng.com/"


def get_featured_headlines(limit=10):
    """Fetches top curated editor choices from Punch's featured RSS category."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(RSS_FEATURED_URL, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch RSS feed. Status code: {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall("./channel/item")

        stories = []
        for item in items[:limit]:
            title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            if title and link:
                stories.append({"title": title.strip(), "link": link.strip()})

        return stories

    except Exception as e:
        print(f"Error parsing RSS feed: {e}")
        return []


def build_message(stories):
    """Formats headlines and appends custom footer."""
    if not stories:
        return None

    header = "*Today's Biggest Headlines*\n\nHere are some of the news reports that you shouldn’t miss this morning:\n\n"
    body = ""

    for idx, story in enumerate(stories, 1):
        body += f"{idx}. {story['title']}\n=== {story['link']}\n\n"

    footer = (
        "------------------------------\n"
        "✨ *Customized Daily Briefing*\n"
        "Have a productive and great day ahead!"
    )

    return header + body + footer


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message):
    """Sends the message to all configured numbers using Green API."""
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]
    headers = {"Content-Type": "application/json"}

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")
        chat_id = (
            clean_recipient
            if ("@g.us" in clean_recipient or "@c.us" in clean_recipient)
            else f"{clean_recipient}@c.us"
        )

        url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
        payload = {"chatId": chat_id, "message": message}

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            print(f"Sent to {chat_id}:", res.json())
        except Exception as e:
            print(f"Failed to send to {chat_id}: {e}")


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

    print("🔍 Fetching featured headlines from Punch...")
    stories = get_featured_headlines(limit=10)

    if not stories:
        print("❌ No stories found.")
        return

    message = build_message(stories)
    print("📤 Sending daily briefing via Green API...")
    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message)


if __name__ == "__main__":
    main()