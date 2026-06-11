"""Phase 4: registration via Eventbrite API or Playwright form fill (human-in-the-loop)."""
import asyncio
import os

import requests
from dotenv import load_dotenv

load_dotenv()

EVENTBRITE_TOKEN = os.getenv("EVENTBRITE_TOKEN")


def user_info():
    return {
        "first_name": os.getenv("USER_FIRST_NAME"),
        "last_name": os.getenv("USER_LAST_NAME"),
        "email": os.getenv("USER_EMAIL"),
    }


def register_eventbrite(event_id, attendee_info):
    url = f"https://www.eventbriteapi.com/v3/events/{event_id}/attendees/"
    headers = {"Authorization": f"Bearer {EVENTBRITE_TOKEN}"}
    payload = {"attendees": [{"profile": attendee_info}]}
    return requests.post(url, json=payload, headers=headers)


async def register_via_form(url, info):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # visible for review
        page = await browser.new_page()
        await page.goto(url)
        for selector, value in [
            ('input[name*="first"]', info["first_name"]),
            ('input[name*="last"]', info["last_name"]),
            ('input[type="email"]', info["email"]),
        ]:
            try:
                await page.fill(selector, value)
            except Exception:
                pass
        # Never submit without human review (CLAUDE.md rule)
        input("Review the form in the browser, then press Enter to submit...")
        await page.click('button[type="submit"]')
        await browser.close()


if __name__ == "__main__":
    import sys

    asyncio.run(register_via_form(sys.argv[1], user_info()))
