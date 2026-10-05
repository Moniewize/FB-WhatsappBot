import os
import urllib.parse
import requests

ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN")
PHONE_NUMBERS = os.getenv(
    "PHONE_NUMBER"
)  # Accepts comma-separated numbers, e.g., 2348012345678,2349012345678
FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "BBCNews")

# Target phrase to filter for the 5:00 AM post
KEYWORD_TARGET = "Today's Biggest Headlines"

# Custom footer you want to append at the end
CUSTOM_FOOTER = (
    "Source: The Punch"
    "Brought by: RAC-FUTO Editorial Team"
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

    # Search through recent items for the post containing the keyword
    target_item = None
    for item in items:
        content = item.get("description", "") or item.get("title", "")
        if KEYWORD_TARGET.lower() in content.lower():
            target_item = item
            break

    if not target_item:
        print(f"No post found matching phrase: '{KEYWORD_TARGET}'")
        return None

    # Get the main post body text
    post_text = target_item.get("description", target_item.get("title", ""))
    link = target_item.get("link", "")

    # Split text into paragraphs
    paragraphs = [p.strip() for p in post_text.split("\n") if p.strip()]

    # Remove the last paragraph if there are multiple paragraphs
    if len(paragraphs) > 1:
        paragraphs = paragraphs[:-1]

    # Reassemble remaining paragraphs
    cleaned_body = "\n\n".join(paragraphs)

    # Append link and custom footer
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
    if not ID_INSTANCE or not API_TOKEN or not PHONE_NUMBERS:
        print("Error: Missing required environment variables.")
        return

    message = fetch_and_modify_target_post(FB_PAGE_NAME)

    if not message:
        print(
            "Target headline post not published yet or not found. Skipping delivery."
        )
        return

    send_whatsapp_green_api(ID_INSTANCE, API_TOKEN, PHONE_NUMBERS, message)


if __name__ == "__main__":
    main()