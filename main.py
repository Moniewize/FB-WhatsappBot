import os
import urllib.parse
import requests

# Read sensitive credentials from Render Environment Variables
FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "BBCNews")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
CALLMEBOT_API_KEY = os.getenv("CALLMEBOT_API_KEY")


def fetch_facebook_posts(page_name):
    rss_url = f"https://rss.app/feeds/v1/facebook/{page_name}.xml"
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={urllib.parse.quote(rss_url)}"

    response = requests.get(api_url)
    if response.status_code != 200:
        return []

    data = response.json()
    items = data.get("items", [])[:3]

    posts = []
    for item in items:
        title = item.get("title", "FB Post")
        link = item.get("link", "")
        posts.append(f"• *{title[:80]}...*\n  {link}")

    return posts


def send_whatsapp_message(phone, api_key, message):
    encoded_message = urllib.parse.quote(message)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded_message}&apikey={api_key}"
    requests.get(url)


def main():
    if not PHONE_NUMBER or not CALLMEBOT_API_KEY:
        print("Error: Missing PHONE_NUMBER or CALLMEBOT_API_KEY environment variables.")
        return

    posts = fetch_facebook_posts(FB_PAGE_NAME)

    if not posts:
        message = "📰 *Daily FB Updates*\n\nNo new posts found today."
    else:
        formatted_posts = "\n\n".join(posts)
        message = f"📰 *Daily Facebook Updates*\n\n{formatted_posts}\n\nHave a great day!"

    send_whatsapp_message(PHONE_NUMBER, CALLMEBOT_API_KEY, message)
    print("WhatsApp message sent successfully!")


if __name__ == "__main__":
    main()