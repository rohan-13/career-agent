"""Phase 2 scraping engine: static (requests+bs4) with Playwright fallback for JS-heavy pages."""
import asyncio
import json
import pathlib
import re
import sys

import requests
from bs4 import BeautifulSoup

RAW_DIR = pathlib.Path(__file__).parent / "data" / "raw"

# Sources: aggregators that proved useful (2026-06-09 run) + new-grad/university
# targets per the Candidate Profile in CLAUDE.md (May 2027 grad, SWE/DS/DE/MLE).
SOURCES = {
    # Working aggregators
    "eventbrite-online-tech-career-fair": "https://www.eventbrite.com/d/online/tech-career-fair/",
    "jobfairx-calendar": "https://jobfairx.com/job-fair-calendar",
    "powertofly-events": "https://powertofly.com/events/",
    "ieee-career-fair": "https://careerfair.ieee.org/",
    # New-grad role trackers (highest signal)
    "simplify-new-grad": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
    # Company university-recruiting portals
    "microsoft-students": "https://careers.microsoft.com/v2/global/en/students",
    "microsoft-virtual-events": "https://careers.microsoft.com/v2/global/en/virtualevents",
    "meta-students": "https://www.metacareers.com/careerprograms/students/",
    "amazon-university": "https://www.amazon.jobs/content/en/career-programs/university",
    "uber-university": "https://www.uber.com/us/en/careers/teams/university/",
    "stripe-university": "https://stripe.com/jobs/university",
    "airbnb-university": "https://careers.airbnb.com/university/",
    # Login-walled, kept for reference (skipped unless auth added):
    # "google-careers-onair": "https://careersonair.withgoogle.com/north-america",
}

# Pages shorter than this after static scraping are assumed JS-rendered shells.
MIN_USEFUL_CHARS = 800


def scrape_static(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
    res = requests.get(url, headers=headers, timeout=20)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


async def scrape_dynamic(url):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45000)
        content = await page.inner_text("body")
        await browser.close()
        return content


def clean(text):
    return re.sub(r"\s{2,}", " ", text).strip()


def main(use_playwright=False):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for slug, url in SOURCES.items():
        out = RAW_DIR / f"{slug}.txt"
        try:
            text = clean(scrape_static(url))
            method = "static"
        except Exception as e:
            text, method = f"ERROR: {e}", "error"
        if use_playwright and (method == "error" or len(text) < MIN_USEFUL_CHARS):
            try:
                text = clean(asyncio.run(scrape_dynamic(url)))
                method = "playwright"
            except Exception as e:
                text, method = f"ERROR: {e}", "error"
        out.write_text(f"URL: {url}\nMETHOD: {method}\n\n{text}")
        results[slug] = {"method": method, "chars": len(text)}
        print(f"{slug:32s} {method:10s} {len(text):>7d} chars")
    (RAW_DIR / "_scrape_summary.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main(use_playwright="--js" in sys.argv)
