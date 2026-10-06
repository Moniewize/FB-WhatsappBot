import os
import urllib.parse
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv("PHONE_NUMBER")
FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "punchnewspaper")

KEYWORDS = ["biggest headlines", "news reports that you shouldn"]

CUSTOM_FOOTER = (
    "\n\n------------------------------\n"
    "✨ *Customized Daily Briefing*\n"
    "Have a productive and great day ahead!"
)


def fetch_and_modify_target_post(page_name):
    rss_url = f"https://rss.app/feeds/v1/facebook/{page_name}.xml"
    api_url = (
        f"https://api.rss2json.com/v1/api.json?rss_url={urllib.parse.quote(rss_url)}"
    )

    response = requests.get(api_url)
    if response.status_code != 200:
        print("Failed to fetch RSS data from API.")
        return None

    data = response.json()
    items = data.get("items", [])

    target_item = None
    for item in items:
        content = (item.get("description", "") or item.get("title", "")).lower()
        if any(keyword in content for keyword in KEYWORDS):
            target_item = item
            break

    if not target_item:
        print("Target headline post not published yet or not found.")
        return None

    post_text = target_item.get("description", target_item.get("title", ""))
    link = target_item.get("link", "")

    paragraphs = [p.strip() for p in post_text.split("\n") if p.strip()]

    if len(paragraphs) > 1:
        paragraphs = paragraphs[:-1]

    cleaned_body = "\n\n".join(paragraphs)
    final_message = f"{cleaned_body}\n\n🔗 *Full Post:* {link}{CUSTOM_FOOTER}"
    return final_message


def send_whatsapp_green_api(id_instance, api_token, raw_phones, message):
    url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
    headers = {"Content-Type": "application/json"}

    phone_list = [p.strip() for p in raw_phones.split(",") if p.strip()]

    for phone in phone_list:
        clean_phone = phone.replace("+", "").replace(" ", "")
        chat_id = f"{clean_phone}@c.us"

        payload = {"chatId": chat_id, "message": message}

        response = requests.post(url, json=payload, headers=headers)
        print(f"Sent to {clean_phone} - Response:", response.json())


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

    message = fetch_and_modify_target_post(FB_PAGE_NAME)

    if not message:
        # Send notification instead of skipping silently
        fallback_msg = (
            "⚠️ *Daily Update Notice*\n\n"
            "Punch Newspapers has not published 'Today's Biggest Headlines' yet this morning."
        )
        send_whatsapp_green_api(
            ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, fallback_msg
        )
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message)


if __name__ == "__main__":
    main()