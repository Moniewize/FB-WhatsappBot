import json
import sys

from playwright.sync_api import sync_playwright

from cover import launch_browser, USER_AGENT

TIMELINE = "https://syndication.twitter.com/srv/timeline-profile/screen-name/MobilePunch"


def walk(node, found):
    if isinstance(node, dict):
        text = node.get("full_text") or node.get("text")
        if isinstance(text, str) and "created_at" in node:
            found.append(node)
        for value in node.values():
            walk(value, found)
    elif isinstance(node, list):
        for item in node:
            walk(item, found)


def main():
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            response = page.goto(TIMELINE, wait_until="domcontentloaded", timeout=60_000)
            print("Status:", response.status if response else None)

            raw = page.evaluate(
                "() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }"
            )
            if not raw:
                print("No data block found. Page text starts with:")
                print(page.inner_text("body")[:600])
                sys.exit(1)

            found = []
            walk(json.loads(raw), found)
            print("Tweets found:", len(found))

            def text_of(tweet):
                return tweet.get("full_text") or tweet.get("text") or ""

            matches = [t for t in found if "Biggest Headlines" in text_of(t)]
            print("Digest posts found:", len(matches))

            for tweet in (matches or found)[:2]:
                print("---- created:", tweet.get("created_at"), "| length:", len(text_of(tweet)))
                print(text_of(tweet))
                print("fields:", sorted(tweet.keys()))
                urls = (tweet.get("entities") or {}).get("urls", [])
                print("links:", [u.get("expanded_url") for u in urls])
        finally:
            browser.close()


if __name__ == "__main__":
    main()