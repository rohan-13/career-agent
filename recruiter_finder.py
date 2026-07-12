"""Discover technical/university recruiters at target companies via LinkedIn.

Discovery flow (per company):
  1. Playwright → LinkedIn company /people/ page filtered by recruiter keywords
     (headless=False; prompts a one-time login and saves cookies to .linkedin_cookies.json)
  2. Hunter.io /email-finder per person (HUNTER_API_KEY in .env) — verified email
  3. If no Hunter key: apply the known domain email pattern (or common guesses)
     to generate a high-likelihood email address

Usage:
  python recruiter_finder.py                  # sweep all companies
  python recruiter_finder.py Google           # single company
  python recruiter_finder.py --list           # print DB contents
"""

import asyncio
import json
import os
import pathlib
import sqlite3
import sys
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env")

DB_PATH = pathlib.Path(__file__).parent / "events.db"
COOKIES_PATH = pathlib.Path(__file__).parent / ".linkedin_cookies.json"

TARGET_COMPANIES = [
    {"name": "Google",     "domain": "google.com",     "linkedin_slug": "google"},
    {"name": "Apple",      "domain": "apple.com",      "linkedin_slug": "apple"},
    {"name": "Amazon",     "domain": "amazon.com",     "linkedin_slug": "amazon"},
    {"name": "Meta",       "domain": "meta.com",       "linkedin_slug": "meta"},
    {"name": "Microsoft",  "domain": "microsoft.com",  "linkedin_slug": "microsoft"},
    {"name": "Uber",       "domain": "uber.com",       "linkedin_slug": "uber"},
    {"name": "Stripe",     "domain": "stripe.com",     "linkedin_slug": "stripe"},
    {"name": "Netflix",    "domain": "netflix.com",    "linkedin_slug": "netflix"},
    {"name": "Airbnb",     "domain": "airbnb.com",     "linkedin_slug": "airbnb"},
    {"name": "Salesforce", "domain": "salesforce.com", "linkedin_slug": "salesforce"},
    {"name": "Snap",       "domain": "snap.com",       "linkedin_slug": "snap"},
    {"name": "Spotify",    "domain": "spotify.com",    "linkedin_slug": "spotify"},
    {"name": "OpenAI",     "domain": "openai.com",     "linkedin_slug": "openai"},
    {"name": "Anthropic",  "domain": "anthropic.com",  "linkedin_slug": "anthropic"},
    {"name": "Figma",      "domain": "figma.com",      "linkedin_slug": "figma-inc-"},
    {"name": "Notion",     "domain": "notion.so",      "linkedin_slug": "notionhq"},
    {"name": "Ramp",       "domain": "ramp.com",       "linkedin_slug": "ramp-financial"},
    {"name": "Plaid",      "domain": "plaid.com",      "linkedin_slug": "plaid-"},
    {"name": "LinkedIn",   "domain": "linkedin.com",   "linkedin_slug": "linkedin"},
]

# Title substrings that mark a person as relevant to new-grad outreach
_RECRUITER_KEYWORDS = [
    "recruiter", "recruiting", "talent acquisition",
    "university recruit", "campus recruit", "technical recruit",
    "early career", "university programs", "new grad", "hiring manager",
]

# LinkedIn company people-search terms (tried in order until we have enough results)
_SEARCH_TERMS = ["recruiter", "university recruiting", "early career", "new grad"]

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Well-documented email patterns for major companies.
# {first} / {last} are lower-cased first/last name tokens.
_DOMAIN_PATTERNS = {
    "google.com":     "{first}.{last}@{domain}",
    "apple.com":      "{first}.{last}@{domain}",
    "microsoft.com":  "{first}.{last}@{domain}",
    "amazon.com":     "{first}@{domain}",
    "netflix.com":    "{first}.{last}@{domain}",
    "airbnb.com":     "{first}.{last}@{domain}",
    "salesforce.com": "{first}.{last}@{domain}",
    "uber.com":       "{first}@{domain}",
    "stripe.com":     "{first}@{domain}",
    "spotify.com":    "{first}@{domain}",
    "openai.com":     "{first}@{domain}",
    "anthropic.com":  "{first}@{domain}",
    "figma.com":      "{first}@{domain}",
    "notion.so":      "{first}@{domain}",
    "ramp.com":       "{first}@{domain}",
    "snap.com":       "{first}.{last}@{domain}",
}


# ── DB ─────────────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS recruiters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            company TEXT,
            title TEXT,
            email TEXT,
            email_confidence TEXT,
            linkedin_url TEXT,
            source TEXT,
            status TEXT DEFAULT 'discovered',
            email_draft TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, name)
        )
    """)
    con.commit()
    return con


def _is_recruiter(title):
    t = (title or "").lower()
    return any(kw in t for kw in _RECRUITER_KEYWORDS)


# ── LinkedIn company people scraper (Playwright) ───────────────────────────────

async def _playwright_people(slug, search_terms, max_results):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=_UA)

        if COOKIES_PATH.exists():
            context_cookies = json.loads(COOKIES_PATH.read_text())
            await context.add_cookies(context_cookies)

        page = await context.new_page()
        seen_urls: dict = {}
        logged_in = False

        for term in search_terms:
            url = (
                f"https://www.linkedin.com/company/{slug}/people/"
                f"?keywords={quote(term)}"
            )
            await page.goto(url, wait_until="networkidle", timeout=45000)

            # Handle auth wall
            if not logged_in and any(x in page.url for x in ["login", "authwall", "signup"]):
                email = os.getenv("LINKEDIN_EMAIL")
                password = os.getenv("LINKEDIN_PASSWORD")

                if email and password:
                    # Auto-fill login form
                    print("  Auto-filling LinkedIn login...", file=sys.stderr)
                    await page.goto("https://www.linkedin.com/login", wait_until="load", timeout=30000)
                    email_sel = 'input#username, input[name="session_key"], input[autocomplete="username"]'
                    pass_sel  = 'input#password, input[name="session_password"], input[autocomplete="current-password"]'
                    await page.wait_for_selector(email_sel, state="attached", timeout=15000)
                    await page.fill(email_sel, email, force=True)
                    await page.fill(pass_sel, password, force=True)
                    await page.click('button[type="submit"]')
                    await page.wait_for_timeout(4000)

                    # Handle 2FA or CAPTCHA — fall back to manual if still on auth page
                    if any(x in page.url for x in ["checkpoint", "challenge", "login", "authwall"]):
                        print(
                            "  LinkedIn triggered a verification step (2FA/CAPTCHA).\n"
                            "  Complete it in the browser window, then press Enter...",
                            file=sys.stderr,
                        )
                        input()

                    COOKIES_PATH.write_text(json.dumps(await context.cookies()))
                    print("  Cookies saved.", file=sys.stderr)
                    await page.goto(url, wait_until="networkidle", timeout=45000)

                else:
                    print(
                        "\nLinkedIn requires login. A browser window is open.\n"
                        "Log in, then press Enter here to continue...\n"
                        "Tip: add LINKEDIN_EMAIL and LINKEDIN_PASSWORD to .env for auto-login.",
                        file=sys.stderr,
                    )
                    input()
                    COOKIES_PATH.write_text(json.dumps(await context.cookies()))
                    print("  Cookies saved.", file=sys.stderr)
                    await page.goto(url, wait_until="networkidle", timeout=45000)

            logged_in = True

            # Scroll to load lazy-rendered cards
            for _ in range(4):
                await page.keyboard.press("End")
                await page.wait_for_timeout(1300)

            # Extract people cards from the DOM
            cards = await page.evaluate("""() => {
                const results = [];
                const seen = new Set();

                document.querySelectorAll('a[href*="/in/"]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href.includes('/in/') || href.includes('/company/')) return;

                    const rawSlug = href.split('/in/')[1]
                        ?.split('?')[0]?.replace(/\\/$/, '');
                    if (!rawSlug || rawSlug.length < 2 || seen.has(rawSlug)) return;
                    seen.add(rawSlug);

                    // Name: prefer explicit aria-hidden span inside the link
                    const span = a.querySelector('span[aria-hidden="true"]');
                    let name = (span ? span.innerText : a.innerText || '').trim();
                    if (!name || name.length < 2) return;

                    // Title: first sibling text block after the name in the card
                    const card = a.closest('li') ||
                                 a.closest('[data-view-name]') ||
                                 a.parentElement?.parentElement;
                    let title = '';
                    if (card) {
                        const lines = card.innerText
                            .split('\\n').map(l => l.trim()).filter(Boolean);
                        const ni = lines.findIndex(
                            l => l.toLowerCase().startsWith(name.toLowerCase().split(' ')[0])
                        );
                        title = ni >= 0 && lines[ni + 1] ? lines[ni + 1] : (lines[1] || '');
                    }

                    results.push({
                        name,
                        title,
                        url: `https://www.linkedin.com/in/${rawSlug}`,
                    });
                });

                return results;
            }""")

            for c in cards:
                if c["url"] not in seen_urls:
                    seen_urls[c["url"]] = c

            if len(seen_urls) >= max_results:
                break

            await page.wait_for_timeout(800)

        await browser.close()
        return list(seen_urls.values())[:max_results]


def scrape_company_people(linkedin_slug, max_results=15):
    """Return list of {name, title, url} dicts from LinkedIn company people search."""
    try:
        people = asyncio.run(_playwright_people(linkedin_slug, _SEARCH_TERMS, max_results))
    except Exception as e:
        print(f"    Playwright error: {e}")
        return []

    # Prefer people with recruiter-matching titles; fall back to all if none match
    filtered = [p for p in people if _is_recruiter(p.get("title", ""))]
    return filtered or people


# ── Hunter.io ──────────────────────────────────────────────────────────────────

def hunter_domain_pattern(domain, api_key):
    """Return Hunter.io's discovered email pattern for a domain, or None."""
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": api_key, "limit": 1},
            timeout=15,
        )
        return r.json().get("data", {}).get("pattern")
    except Exception:
        return None


def hunter_find_email(first, last, domain, api_key):
    """Look up a person's verified email via Hunter.io. Returns (email, score_str) or (None, None)."""
    try:
        r = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": api_key},
            timeout=15,
        )
        data = r.json().get("data", {})
        email = data.get("email")
        return (email, str(data.get("score", ""))) if email else (None, None)
    except Exception:
        return None, None


# ── Email generation ───────────────────────────────────────────────────────────

def _apply(template, first, last, domain):
    result = (
        template
        .replace("{first}", first)
        .replace("{last}", last)
        .replace("{domain}", domain)
    )
    return result if "@" in result else f"{result}@{domain}"


def generate_email(name, domain, hunter_pattern=None):
    """
    Return (best_email, confidence) using:
      Hunter pattern → known domain pattern → generic {first}.{last} guess.
    """
    parts = name.lower().split()
    if len(parts) < 2:
        return None, None

    first, last = parts[0], parts[-1]

    if hunter_pattern:
        return _apply(hunter_pattern, first, last, domain), "hunter-pattern"

    if domain in _DOMAIN_PATTERNS:
        return _apply(_DOMAIN_PATTERNS[domain], first, last, domain), "pattern"

    return f"{first}.{last}@{domain}", "guessed"


# ── Main ───────────────────────────────────────────────────────────────────────

def discover_recruiters(companies=None, max_per_company=10):
    """Scrape LinkedIn company people pages and upsert results into events.db."""
    api_key = os.getenv("HUNTER_API_KEY") or None
    companies = companies or TARGET_COMPANIES
    con = init_db()
    total_new = 0
    pattern_cache = {}

    for co in companies:
        cname = co["name"]
        domain = co["domain"]
        slug = co.get("linkedin_slug", cname.lower().replace(" ", ""))

        print(f"\n── {cname} (linkedin.com/company/{slug}) ──")

        people = scrape_company_people(slug, max_results=max_per_company)
        print(f"  {len(people)} candidate(s) found")

        # Fetch Hunter domain pattern once per company
        if api_key and domain not in pattern_cache:
            pattern_cache[domain] = hunter_domain_pattern(domain, api_key)
            if pattern_cache[domain]:
                print(f"  Hunter pattern: {pattern_cache[domain]}")
            time.sleep(0.3)

        for person in people[:max_per_company]:
            pname = person["name"]
            title = person.get("title", "")
            li_url = person.get("url", "")

            # Try Hunter per-person lookup first
            email, conf = None, None
            parts = pname.split()
            if api_key and len(parts) >= 2:
                email, conf = hunter_find_email(parts[0], parts[-1], domain, api_key)
                time.sleep(0.3)

            if not email:
                email, conf = generate_email(pname, domain, pattern_cache.get(domain))

            try:
                con.execute(
                    """INSERT OR IGNORE INTO recruiters
                       (name, company, title, email, email_confidence, linkedin_url, source)
                       VALUES (?,?,?,?,?,?,?)""",
                    (pname, cname, title, email, conf, li_url, "linkedin-direct"),
                )
                if con.execute("SELECT changes()").fetchone()[0]:
                    total_new += 1
            except sqlite3.Error:
                pass

        con.commit()
        time.sleep(2)  # polite delay between companies

    con.close()
    print(f"\nDone. {total_new} new recruiter(s) added to events.db.")
    return total_new


def list_recruiters(company=None, status=None):
    con = init_db()
    q = "SELECT id, name, company, title, email, email_confidence, status FROM recruiters WHERE 1=1"
    params = []
    if company:
        q += " AND company = ?"
        params.append(company)
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY company, name"
    rows = con.execute(q, params).fetchall()
    con.close()

    if not rows:
        print("No recruiters found.")
        return rows

    print(f"\n{'ID':>4}  {'Company':<14} {'Name':<26} {'Title':<30} {'Email':<38} Conf")
    print("-" * 120)
    for rid, name, company, title, email, conf, status in rows:
        print(
            f"{rid:>4}  {company:<14} {name:<26} {(title or ''):<30} "
            f"{(email or '(none)'):<38} {conf or ''}"
        )
    return rows


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_recruiters()
    else:
        company_filter = None
        for arg in sys.argv[1:]:
            if not arg.startswith("--"):
                company_filter = [
                    c for c in TARGET_COMPANIES if c["name"].lower() == arg.lower()
                ]
        discover_recruiters(companies=company_filter)
        list_recruiters()
