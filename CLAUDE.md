# Career Events Agent — Claude Code Master Prompt

## Agent Overview

You are an autonomous career events agent. Your mission is to continuously discover, scrape, parse, and register for tech career events at top companies (Google, Apple, Amazon, Meta, Microsoft, Uber, Stripe, Nike, Netflix, Airbnb, and similar), then sync confirmed events to Google Calendar.

## Candidate Profile (use this to target ALL discovery, scraping, and parsing)

- **Status:** University student, graduating **May 2027** with a **B.S. in Data Science**
- **Experience:** Multiple Software Engineering internships
- **Target level:** **New Grad / early career** (class of 2027 cohort; new-grad requisitions typically open Aug–Oct 2026)
- **Target roles:** Software Engineering (SWE), Data Science, Data Engineering, ML Engineering — and adjacent (analytics engineering, AI/ML research eng)
- **High-value events:** new-grad info sessions, university recruiting events, campus events, early-talent program kickoffs (e.g. application-window openings), new-grad role drops, conference career fairs with university tracks (Grace Hopper, IEEE, AfroTech)
- **Low-value (deprioritize):** generic staffing fairs, warehouse/hourly hiring, mid-career/executive networking, sales-track webinars
- **Also track ROLE OPENINGS, not just events:** when a target company opens "New Grad 2027" SWE/DS/DE/MLE requisitions, treat the application-window opening as an event (date = posting date, url = application link)

You have access to the **last-30-days skill**, which gives you multi-source intelligence across:
- Web articles and company career/events pages
- Instagram, TikTok, YouTube, and X (Twitter) posts and announcements
- LinkedIn Events and professional community content
- Eventbrite, Meetup, and aggregator platforms

**Always leverage the last-30-days skill first** when sourcing events. Social media often surfaces career events (info sessions, hiring hackathons, networking nights, virtual panels) days before they appear on official pages.

---

## Phase 1 — Source Discovery (Use last-30-days skill here)

Before hitting any URLs directly, use the last-30-days skill to sweep all available channels:

### Social Media Sweep
Search the following on Instagram, TikTok, YouTube, and X:
- `"[Company] hiring event 2026"` — for each target company
- `"tech career fair 2026"`
- `"software engineering info session"`
- `"[Company] campus recruiting"`
- `"[Company] early career event"`
- `"[Company] new grad 2027"` / `"new grad 2027 SWE"` / `"data science new grad"`
- `"[Company] university recruiting"` / `"new grad applications open"`
- Hashtags: `#techjobs`, `#techhiring`, `#softwareengineer`, `#careersintech`, `#[Company]careers`, `#newgrad`, `#classof2027`

Companies to always include: Google, Apple, Amazon, Meta, Microsoft, Uber, Stripe, Nike, Netflix, Airbnb, Salesforce, LinkedIn, Snap, Spotify, OpenAI, Anthropic, Figma, Notion, Ramp, Plaid.

### Web + Article Sources
- Official career portals: `careers.google.com/events`, `jobs.apple.com`, `amazon.jobs/events`, etc.
- Eventbrite: search `"tech career"`, `"software engineer networking"`, `"big tech hiring"`
- Meetup.com: `"tech careers"`, `"engineering hiring"` within 50 miles or virtual
- LinkedIn Events: search by company and by keyword `"career"` + `"tech"`
- Handshake and Jumpstart for university-partnered events
- Company university-recruiting portals: `careers.microsoft.com/v2/global/en/students`, `amazon.jobs` university programs, `metacareers.com` students, `careers.uber.com/university`, `stripe.com/jobs/university`
- **GitHub new-grad trackers (highest-signal for role openings):** `SimplifyJobs/New-Grad-Positions` README — community-maintained, updated daily with new-grad SWE/DS/MLE requisitions and direct application links

### Output from Phase 1
Produce a deduplicated list of candidate event URLs and social media posts to process in Phase 2.

---

## Phase 2 — Web Scraping Engine

For each source URL identified in Phase 1:

### Static pages
Use `requests` + `BeautifulSoup`:
```python
import requests
from bs4 import BeautifulSoup

def scrape_static(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)
```

### JS-heavy pages (most modern career portals)
Use `playwright`:
```python
from playwright.async_api import async_playwright

async def scrape_dynamic(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        content = await page.inner_text("body")
        await browser.close()
        return content
```

### Scheduling
Run this agent on a cron schedule — at minimum once daily, ideally every 6 hours:
```
0 */6 * * * python career_agent.py
```

Use a local SQLite database (`events.db`) to track already-seen events and avoid duplicates.

---

## Phase 3 — AI Parsing

After scraping raw content (HTML text or social media post text), pass it through Claude for structured extraction.

### Parsing prompt to use
```python
PARSE_PROMPT = """
You are parsing content for career events at tech companies.

Given the raw text below, extract any career-related events. Only include events that are:
- Hosted by or about a notable tech/business company
- Related to careers, hiring, recruiting, networking, internships, or professional development
- Happening in the future (today or later), or within the next 90 days

For each event found, return a JSON array. Each event object must have these fields:
{
  "title": "Event name",
  "company": "Company name",
  "date": "YYYY-MM-DD or best guess",
  "time": "HH:MM in local time, or null if unknown",
  "timezone": "e.g. ET, PT, UTC",
  "location": "City/State, 'Virtual', or 'Hybrid'",
  "url": "Registration or event URL",
  "description": "1-2 sentence summary",
  "source": "web | instagram | tiktok | youtube | x | linkedin | eventbrite | meetup"
}

If no career events are found, return an empty array [].
Return ONLY valid JSON. No explanation, no markdown.

Raw content:
{raw_content}
"""
```

### Deduplication
After parsing, deduplicate by matching on `(company + date + title similarity)`. Use fuzzy matching (`rapidfuzz`) to catch slight title variations across sources.

---

## Phase 4 — Human-in-the-Loop Approval + Registration

### Step 1: Surface events for approval
Before registering for anything, print a formatted table of discovered events and ask:
```
Found 7 new career events. Review and approve:

[1] Google — Engineering Career Fair — June 14, 2026 @ 2PM ET (Virtual)
    Register: careers.google.com/events/...
    Source: LinkedIn + X

[2] Stripe — Early Career Info Session — June 18, 2026 @ 6PM PT (Virtual)
    Register: stripe.com/events/...
    Source: Instagram (@stripecareers)

Enter numbers to approve (e.g. 1,3,5), 'all', or 'skip':
```

### Step 2: Auto-registration
For approved events, attempt registration using the appropriate method:

**Eventbrite API** (preferred when available):
```python
import requests

def register_eventbrite(event_id, attendee_info):
    url = f"https://www.eventbriteapi.com/v3/events/{event_id}/attendees/"
    headers = {"Authorization": f"Bearer {EVENTBRITE_TOKEN}"}
    payload = {"attendees": [{"profile": attendee_info}]}
    return requests.post(url, json=payload, headers=headers)
```

**Playwright form fill** (for custom RSVP pages):
```python
async def register_via_form(url, user_info):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # visible for review
        page = await browser.new_page()
        await page.goto(url)
        # Fill common fields
        for selector, value in [
            ('input[name*="first"]', user_info["first_name"]),
            ('input[name*="last"]', user_info["last_name"]),
            ('input[type="email"]', user_info["email"]),
        ]:
            try:
                await page.fill(selector, value)
            except:
                pass
        # Pause for human review before final submit
        input("Review the form in the browser, then press Enter to submit...")
        await page.click('button[type="submit"]')
        await browser.close()
```

Store user info in a `.env` file:
```
USER_FIRST_NAME=YourFirstName
USER_LAST_NAME=YourLastName
USER_EMAIL=your@email.com
EVENTBRITE_TOKEN=your_token_here
GOOGLE_CALENDAR_CREDENTIALS=path/to/credentials.json
```

---

## Phase 5 — Google Calendar Sync

For every approved + registered event, create a Google Calendar entry.

### Setup (one-time)
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the **Google Calendar API**
3. Create OAuth 2.0 credentials → download `credentials.json`
4. Place `credentials.json` in the project root

### Calendar event creation
```python
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import datetime

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def add_to_calendar(event):
    creds = None
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    service = build("calendar", "v3", credentials=creds)

    start_dt = f"{event['date']}T{event['time'] or '09:00'}:00"
    body = {
        "summary": f"[CAREER] {event['company']} — {event['title']}",
        "description": f"{event['description']}\n\nRSVP: {event['url']}\nSource: {event['source']}",
        "location": event["location"],
        "start": {"dateTime": start_dt, "timeZone": event.get("timezone", "America/New_York")},
        "end": {"dateTime": start_dt, "timeZone": event.get("timezone", "America/New_York")},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 1440},   # 24 hrs
                {"method": "popup", "minutes": 60},     # 1 hr
            ],
        },
    }
    service.events().insert(calendarId="primary", body=body).execute()
    print(f"✓ Added to calendar: {event['title']}")
```

---

## Project File Structure

```
career-agent/
├── CLAUDE.md                  ← this file (agent instructions)
├── .env                       ← API keys and user info (never commit)
├── credentials.json           ← Google OAuth credentials
├── career_agent.py            ← main orchestration script
├── scraper.py                 ← Phase 2 scraping logic
├── parser.py                  ← Phase 3 Claude parsing logic
├── register.py                ← Phase 4 registration logic
├── calendar_sync.py           ← Phase 5 Google Calendar logic
├── events.db                  ← SQLite store (auto-created)
├── requirements.txt
└── logs/
    └── agent.log
```

### requirements.txt
```
requests
beautifulsoup4
playwright
anthropic
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
python-dotenv
rapidfuzz
schedule
```

---

## Agent Execution Order

When running, always follow this sequence:

1. **Run last-30-days skill** → sweep Instagram, TikTok, YouTube, X, web articles for new career event signals
2. **Scrape identified URLs** → use static or dynamic scraper as appropriate
3. **Parse with Claude** → extract structured JSON event objects
4. **Deduplicate** → check against `events.db`, skip already-seen events
5. **Present for approval** → show new events and await user input
6. **Register** → use Eventbrite API or Playwright form fill
7. **Sync to Google Calendar** → create entry with reminders and RSVP link
8. **Log** → write results to `logs/agent.log`

---

## Notes for Claude Code

- **Always use the last-30-days skill before any scraping.** Social media posts (especially from company recruiters on X and Instagram) often announce events before they appear on official career pages.
- When using the last-30-days skill on TikTok and YouTube, look for videos from official company recruiting accounts and career-focused creators — comment sections often contain registration links.
- Never submit a registration form without pausing for human review first.
- All credentials go in `.env` — never hardcode.
- If a source requires authentication (Instagram private accounts, LinkedIn), note it in the log and skip gracefully.
- Prioritize virtual/hybrid events as they are accessible regardless of location.
