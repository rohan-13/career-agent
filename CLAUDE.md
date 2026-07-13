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

## Phase 6 — Job-Posting Pipeline

In addition to career *events*, the agent tracks new-grad/entry-level *job postings* directly, via `job_sources.py`, `linkedin_source.py`, and `filters.py`, orchestrated by `career_agent.py`'s `run_jobs_pipeline()`.

### Sources

1. **ATS boards** (`job_sources.fetch_ats_boards()`) — structured JSON APIs, no LLM parsing needed. `job_sources.ATS_BOARDS` currently covers **23 companies** across three ATS providers (Greenhouse, Lever, Ashby): Stripe, Airbnb, OpenAI, Anthropic, Figma, Notion, Ramp, Plaid, Databricks, Scale AI, Brex, Coinbase, Snowflake, Confluent, MongoDB, Asana, Discord, Affirm, Robinhood, Instacart, Lyft, Pinterest, Reddit. Each entry maps `company -> (ats, slug)`; `posted_date` semantics differ by provider (Greenhouse = `updated_at`, bumps on edits; Ashby = `publishedAt`; Lever = `createdAt`, UTC).
2. **GitHub new-grad tracker** (`job_sources.fetch_trackers()`) — parses the `SimplifyJobs/New-Grad-Positions` README's HTML `<tr><td>` table format (`job_sources.TRACKER_REPOS["simplify"]`).
3. **LinkedIn job search** (`linkedin_source.fetch_linkedin()`) — covers FAANG and any other company without a public ATS API (Google, Apple, Amazon, Meta, Microsoft, etc.) by scraping LinkedIn's logged-in job-search results. This is the ToS-sensitive path — see the dedicated **LinkedIn ToS & Risk** subsection under "Recruiter Discovery & Outreach" below for the full mitigation list (12h throttle, 40-page cap, randomized delays, abort-on-checkpoint); `fetch_linkedin()`'s docstring documents the 5 possible status values (`ok`, `no-session`, `throttled`, `checkpoint`, `error`).

Every fetched posting is run through `filters.is_target()` (title/description regex matching for new-grad + target-role signals) before being treated as a match; `filters.match_strength()` then scores it 0-3 for digest ranking.

### `jobs` table (in `events.db`)

Created by `job_sources.init_jobs_table()`:

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, company TEXT, location TEXT,
    url TEXT UNIQUE,
    source TEXT, posted_date TEXT,
    match_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP
)
```

Dedup is two-layer (`job_sources.insert_jobs()`): exact `url` match, then a fuzzy `token_sort_ratio >= 85` title match within the same company (catches cross-source title variants like "Software Engineer, New Grad" vs "... New Grad (2027)").

**Status lifecycle:** `new` (just inserted) → `digested` (flipped by `digest.run_digest()` after it writes/emails the digest containing that job — see `digest.py`'s final `UPDATE jobs SET status = 'digested' WHERE url = ?` step).

### Digest output

`digest.run_digest()` renders a ranked markdown digest (jobs table + recruiters-by-company table) to `digests/jobs-YYYY-MM-DD.md` and emails it (see "Env vars / credentials" below for what's required to actually send the email — email send is skipped gracefully, not fatal, if unconfigured). `digests/` is gitignored.

### Running standalone

```
python career_agent.py --jobs-only     # job-posting + recruiter-discovery pipeline
python career_agent.py --events-only   # original events-only pipeline (Phases 1-5)
python career_agent.py                 # same as --events-only (default when no flag given)
```

---

## Recruiter Discovery & Outreach

Beyond job postings, the agent can find and draft outreach to technical/university recruiters at target companies, via `recruiter_finder.py` and `outreach.py`.

### What it does

1. **LinkedIn people-search scraping** (`recruiter_finder.scrape_company_people()`) — Playwright loads a target company's LinkedIn `/people/` page filtered by recruiter-relevant search terms (`recruiter`, `university recruiting`, `early career`, `new grad`), extracts name/title/profile-URL cards, and keeps only ones whose title matches recruiter keywords (falls back to all results if none match).
2. **Email resolution**, per person found:
   - If `HUNTER_API_KEY` is set: Hunter.io's `/email-finder` API for a verified email, or its `/domain-search` pattern as a per-company fallback.
   - Otherwise: `recruiter_finder._DOMAIN_PATTERNS`' known email pattern for that company's domain, or a generic `{first}.{last}@{domain}` guess.

### `recruiters` table (in `events.db`)

Created by `recruiter_finder.init_db()`:

```sql
CREATE TABLE recruiters (
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
```

`recruiter_finder.TARGET_COMPANIES` currently lists **23 companies** (19 original + 4 added: Databricks, Scale AI, Coinbase, Snowflake — the remaining new ATS companies from Phase 6 are a known coverage gap, left for later work). This list is separate from `job_sources.ATS_BOARDS` and doesn't need to match it 1:1.

### Automatic trigger (30-day TTL)

`run_jobs_pipeline()` calls `career_agent._maybe_discover_recruiters(company)` once per distinct company among that run's newly-inserted jobs. This is throttled by a **separate bookkeeping table**, `recruiter_checks` (company TEXT PRIMARY KEY, last_attempted TEXT) — created by `career_agent._init_recruiter_checks_table()` — which is distinct from the `recruiters` table itself:

- `recruiter_checks` tracks "when did we last *attempt* LinkedIn discovery for this company," updated unconditionally after every `discover_recruiters()` call, regardless of how many rows it inserted (or found zero).
- This is deliberately independent of `recruiters.first_seen`, which only reflects when a specific recruiter row was first inserted (an `INSERT OR IGNORE` against `UNIQUE(company, name)` silently no-ops on repeat finds for a stable recruiting roster).
- Net effect: a company is not re-scraped via LinkedIn more than once per `RECRUITER_DISCOVERY_TTL_DAYS` (30 days), **regardless of whether new recruiters are found**, no matter how many new job postings show up for that company in between.

### Manual entry points

```
python career_agent.py --recruiter               # discover recruiters at all target companies
python career_agent.py --recruiter Google        # discover at one company only
python career_agent.py --list-recruiters         # print all discovered recruiters

# Two-step outreach flow (Claude Code does the drafting; no ANTHROPIC_API_KEY needed in outreach.py):
python career_agent.py --outreach --scrape-only --id 3   # scrape recruiter id=3's LinkedIn profile, print text to stdout
python career_agent.py --outreach --save-draft --id 3     # pipe a drafted email via stdin, save it against recruiter id=3
```

(`recruiter_finder.py` and `outreach.py` can also be invoked directly — see each file's module docstring for their standalone CLI forms.)

### LinkedIn ToS & Risk — READ BEFORE RUNNING

> **This feature automates logged-in access to LinkedIn, which is a violation of LinkedIn's Terms of Service.** The user has explicitly reviewed and accepted this risk for their own personal LinkedIn account. Do not extend this automation to scrape on behalf of anyone else's account without the same explicit sign-off.

Mitigations in place (all load-bearing, not decorative — do not loosen any of these for convenience without re-evaluating the risk):

- **Session-cookie reuse instead of repeated logins** — `linkedin_session.get_authenticated_page()` persists cookies to `.linkedin_cookies.json` and reuses them, only falling back to a fresh login (auto-fill or manual+2FA) when the saved session is rejected.
- **Randomized delays between navigations** — `linkedin_source.py` pauses 3-8s (`PAUSE_RANGE_SECONDS`) between page loads within a run.
- **40-page-load cap per run** — `linkedin_source.MAX_PAGE_LOADS`; `_fetch()` aborts once reached.
- **12-hour minimum gap between LinkedIn job-search runs** — `linkedin_source.MIN_INTERVAL_HOURS`, enforced by `allowed_to_run()` / `.linkedin_last_run`.
- **Immediate, no-retry abort on any CAPTCHA/checkpoint/login-wall redirect** — `linkedin_session.is_checkpoint_url()`; hit anywhere in `linkedin_source._fetch()` or during `_perform_login()`, the run stops rather than retrying.
- **30-day per-company recruiter-rescrape throttle** — the `recruiter_checks` mechanism described above, which bounds how often `recruiter_finder.py`'s people-search scraping hits a given company's LinkedIn page.

**These mitigations reduce, but do not eliminate, the risk of LinkedIn account restriction.** Treat any checkpoint/CAPTCHA hit as a signal to stop and investigate, not to retry.

See also `CLAUDE.md`'s "Notes for Claude Code" section (bottom of this file) for the manual-smoke-test command and checklist to run before relying on any of this LinkedIn-driving code in production — none of it is covered by automated tests.

---

## Env vars / credentials

In addition to the Phase 1-5 `.env` vars documented above, the job-posting and recruiter-discovery features depend on:

- **`LINKEDIN_EMAIL`** / **`LINKEDIN_PASSWORD`** — optional. If both are set, `linkedin_session._perform_login()` auto-fills LinkedIn's login form. If unset (or if auto-login hits a CAPTCHA/2FA step), the first run pauses for manual login + any 2FA in a visible browser window, then persists the session to `.linkedin_cookies.json` for reuse on subsequent runs.
- **`HUNTER_API_KEY`** — optional. Enables Hunter.io email lookup/pattern discovery in `recruiter_finder.py`. Without it, email resolution falls back to `recruiter_finder._DOMAIN_PATTERNS`' known per-company pattern, or a generic `{first}.{last}@{domain}` guess.
- **`GMAIL_APP_PASSWORD`** / **`DIGEST_TO`** — required for `digest.send_email()` to actually send the job digest email; without both set, `run_digest()` still writes `digests/jobs-YYYY-MM-DD.md` but skips the email send (logged as a warning, not fatal). To generate a Gmail app password: Google Account → Security → 2-Step Verification → App passwords → generate one for "Mail," then set `GMAIL_APP_PASSWORD` to the generated 16-character value.
- **`USER_EMAIL`** — already documented above (Phase 4); reused as-is by `digest.send_email()` as the SMTP login username and `From` address (not a new/separate var — do not add a second email var for this).

**`.linkedin_cookies.json`** is gitignored (see `.gitignore`) and must never be committed — it holds a live LinkedIn session.

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
├── filters.py                 ← new-grad/entry-level targeting filters (jobs + LinkedIn search)
├── register.py                ← Phase 4 registration logic
├── calendar_sync.py           ← Phase 5 Google Calendar logic
├── job_sources.py             ← Phase 6: ATS boards + GitHub tracker fetchers, `jobs` table
├── linkedin_session.py        ← shared LinkedIn login/cookie-session handling
├── linkedin_source.py         ← Phase 6: LinkedIn job-search fetcher (throttled, ToS-sensitive)
├── digest.py                  ← job+recruiter digest: scoring, markdown rendering, email delivery
├── recruiter_finder.py        ← recruiter discovery: LinkedIn people-search + Hunter/pattern email resolution
├── outreach.py                ← recruiter profile scraping + outreach draft storage (two-step CLI)
├── events.db                  ← SQLite store (auto-created; events + jobs + recruiters + recruiter_checks tables)
├── requirements.txt
├── digests/                   ← generated job digests, jobs-YYYY-MM-DD.md (gitignored)
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
- **LinkedIn browser-driving code is manual-smoke-test-only, not covered by automated tests.** `linkedin_session.get_authenticated_page()` and `linkedin_source.fetch_linkedin()` (and the Playwright scraping in `recruiter_finder.py`/`outreach.py`) require a live, logged-in browser session against LinkedIn's real DOM, so there is no automated/CI test for them — consistent with how the original design doc scoped LinkedIn testing. Only their pure-logic pieces (`job_search_url()`, `allowed_to_run()`) have automated tests (`tests/test_linkedin_source.py`). Before relying on `fetch_linkedin()` in production, manually smoke-test it against a real LinkedIn session (`python -c "import linkedin_source; print(linkedin_source.fetch_linkedin(headless=False))"`) and confirm: it logs in or reuses cookies, respects the 12-hour throttle (`.linkedin_last_run`), stops at the 40-page-load cap, and aborts immediately (no retry) if LinkedIn shows a checkpoint/CAPTCHA/login-wall.
