import os
import re
import requests
from facebook_scraper import get_posts

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")

FB_PAGE = "punchnewspaper"
PUNCH_FB_PAGE_URL = "https://www.facebook.com/punchnewspaper"


def fetch_punch_facebook_headlines():
    """Scrapes Punch's official Facebook page for the morning 'Today's Biggest Headlines' post."""
    print(f"🔍 Checking Punch Facebook page (@{FB_PAGE}) for morning headlines post...")

    try:
        # Fetch the top 10 latest posts from Punch's public page
        for post in get_posts(FB_PAGE, pages=2):
            post_text = post.get("text") or ""

            # Identify the specific morning summary post
            if "Today's Biggest Headlines" in post_text or "Here are some of the news" in post_text:
                print("✅ Found 'Today's Biggest Headlines' post from Facebook!")
                return clean_and_format_facebook_post(post_text)

    except Exception as e:
        print(f"⚠️ Error fetching from Facebook: {e}")

    print("❌ Could not locate the morning Facebook headlines post.")
    return None, None


def clean_and_format_facebook_post(raw_text):
    """Trims the last unwanted paragraph, appends the custom footer, and formats for WhatsApp."""
    # Split post into distinct paragraphs/blocks
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]

    # Trim the last paragraph if it contains promo text or boilerplate sign-offs
    if len(paragraphs) > 1:
        last_p = paragraphs[-1].lower()
        if any(kw in last_p for kw in ["follow us", "read full", "punchng.com", "social media", "subscribe"]):
            paragraphs.pop()

    # Reconstruct body text
    cleaned_body = "\n\n".join(paragraphs)

    custom_footer = (
        "\n\n------------------------------\n"
        "✨ *Customized Daily Briefing*\n"
        "Have a productive and great day ahead!"
    )

    first_message = cleaned_body + custom_footer

    second_message = (
        "📰 *Official Newspaper Facebook Page*\n\n"
        "Tap here to visit Punch's official Facebook page:\n"
        f"{PUNCH_FB_PAGE_URL}"
    )

    return first_message, second_message


def send_whatsapp_green_api(id_instance, api_token, raw_phones, msg1, msg2):
    recipient_list = [p.strip() for p in raw_phones.split(",") if p.strip()]
    headers = {"Content-Type": "application/json"}

    for recipient in recipient_list:
        clean_recipient = recipient.replace("+", "").replace(" ", "")
        chat_id = clean_recipient if ("@g.us" in clean_recipient or "@c.us" in clean_recipient) else f"{clean_recipient}@c.us"

        msg_url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"

        # 1. Send Main Facebook Headlines Message
        res1 = requests.post(msg_url, json={"chatId": chat_id, "message": msg1}, headers=headers, timeout=15)
        print(f"Facebook Headlines Digest Sent to ({chat_id}):", res1.json())

        # 2. Send Facebook Reference Link
        if msg2:
            res2 = requests.post(msg_url, json={"chatId": chat_id, "message": msg2}, headers=headers, timeout=15)
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

    first_message, second_message = fetch_punch_facebook_headlines()

    if not first_message:
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published the 'Today's Biggest Headlines' post on Facebook yet."
        )
        send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg, None)
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, first_message, second_message)


if __name__ == "__main__":
    main()