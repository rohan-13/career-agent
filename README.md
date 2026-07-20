# career-agent

A personal automation pipeline for a new-grad tech job search. It discovers career events and new-grad/entry-level job postings, tracks them in a local database, finds recruiter contacts at target companies, and helps draft outreach — with a human always in the loop for anything that gets registered, applied to, or sent.

Built to be driven by [Claude Code](https://claude.com/claude-code); most of the "intelligence" (parsing raw scrapes into structured data, drafting outreach emails) happens in a Claude Code session, not inside the scripts themselves.

## What it does

**Career events** (Phases 1–5) — sweeps company career pages, Eventbrite/Meetup/aggregators, and social platforms for new-grad info sessions, campus recruiting events, and career fairs. Scraped pages are parsed into structured events by Claude, deduped against a local SQLite database, presented for approval, and — only after explicit approval — registered and synced to Google Calendar.

**Job postings** (Phase 6) — pulls new-grad/entry-level openings directly from company ATS APIs (Greenhouse, Lever, Ashby — 23 companies tracked), the community-maintained [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) tracker, and a throttled LinkedIn job search for companies (Google, Apple, Amazon, Meta, Microsoft, etc.) that don't publish to a public ATS. Postings are filtered against new-grad/entry-level role signals, scored, deduplicated, and written to the same database.

**Recruiter discovery & outreach** — for companies with a newly-found job posting, automatically looks up technical/university recruiters on LinkedIn and resolves an email via Hunter.io or a known per-company email pattern. Recruiter lookups are throttled to once per company per 30 days regardless of how many new postings appear in between. A two-step CLI flow lets you (via Claude Code) draft and save a personalized cold outreach email per recruiter.

**Digest** — a ranked markdown digest of new postings + newly-found recruiters is written daily and optionally emailed.

> **LinkedIn automation notice:** the job-search and recruiter-discovery features scrape LinkedIn while logged in, which is a violation of LinkedIn's Terms of Service and carries real risk of account restriction. This is opt-in (nothing touches LinkedIn without `LINKEDIN_EMAIL`/`LINKEDIN_PASSWORD` or existing session cookies configured) and mitigated with session reuse, rate limiting, and automatic abort on any checkpoint/CAPTCHA — see the **LinkedIn ToS & Risk** section in [`CLAUDE.md`](./CLAUDE.md) before enabling it. Use at your own risk, on your own account.

## Setup

**Requirements:** Python 3.10+, a Claude API key (for event parsing), and — optionally — a Google Cloud OAuth client, an Eventbrite API token, a Hunter.io API key, and a Gmail account for email delivery.

```bash
git clone https://github.com/rohanp-13/career-agent.git
cd career-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for LinkedIn scraping / dynamic-page fallback
```

Create a `.env` file in the project root:

```bash
# You
USER_FIRST_NAME=
USER_LAST_NAME=
USER_EMAIL=

# Required — event parsing
ANTHROPIC_API_KEY=

# Optional — event registration
EVENTBRITE_TOKEN=

# Optional — Google Calendar sync (see "Google Calendar setup" below)
GOOGLE_CALENDAR_CREDENTIALS=credentials.json

# Optional — recruiter email lookup (falls back to pattern-guessing if unset)
HUNTER_API_KEY=

# Optional — enables LinkedIn job search + recruiter discovery (see the risk notice above)
LINKEDIN_EMAIL=
LINKEDIN_PASSWORD=

# Optional — daily digest email (Gmail app password: Google Account -> Security -> 2-Step Verification -> App passwords)
GMAIL_APP_PASSWORD=
DIGEST_TO=
```

Everything is optional except `ANTHROPIC_API_KEY` — unset features degrade gracefully (e.g. no Hunter key falls back to pattern-guessed emails; no LinkedIn credentials means `fetch_linkedin()` refuses to run rather than hang; no Gmail credentials means the digest is still written to disk, just not emailed).

### Google Calendar setup (optional)

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com) and enable the Google Calendar API.
2. Create an OAuth 2.0 Desktop client and download `credentials.json` into the project root.
3. The first calendar sync will open a browser for one-time authorization.

## Usage

```bash
python career_agent.py                    # events pipeline (Phases 1-5): scrape, parse, approve, register, sync
python career_agent.py --jobs-only        # job-posting + recruiter-discovery pipeline (Phase 6)
python career_agent.py --events-only      # same as running with no flags

python career_agent.py --recruiter              # find recruiters at all tracked target companies
python career_agent.py --recruiter Google       # find recruiters at one company
python career_agent.py --list-recruiters        # list everything discovered so far

# Two-step outreach drafting (drafting itself happens in your Claude Code session)
python career_agent.py --outreach --scrape-only --id 3   # print a recruiter's LinkedIn profile text
python career_agent.py --outreach --save-draft --id 3     # save a drafted email against that recruiter
```

Run the tests with:

```bash
pytest
```

## How it's organized

| File | Responsibility |
|---|---|
| `career_agent.py` | Orchestration + CLI entry point for every mode above |
| `scraper.py` / `parser.py` | Event scraping (static + Playwright) and Claude-based structured extraction |
| `job_sources.py` | ATS board APIs (Greenhouse/Lever/Ashby) + SimplifyJobs tracker fetchers, `jobs` table |
| `linkedin_source.py` / `linkedin_session.py` | Throttled LinkedIn job search + shared login/cookie session handling |
| `filters.py` | New-grad/entry-level role targeting logic |
| `recruiter_finder.py` | LinkedIn people-search scraping + Hunter.io/pattern-based email resolution, `recruiters` table |
| `outreach.py` | LinkedIn profile scraping + outreach draft storage |
| `digest.py` | Job/recruiter scoring, markdown digest rendering, email delivery |
| `register.py` / `calendar_sync.py` | Event registration (Eventbrite / Playwright form-fill) and Google Calendar sync |
| `events.db` | SQLite store for events, jobs, and recruiters (git-ignored, auto-created) |

For the full agent spec — including the exact prompts, schemas, and the LinkedIn risk/mitigation details — see [`CLAUDE.md`](./CLAUDE.md).

## Status

Personal project, built and driven interactively with Claude Code. Not a general-purpose tool — targeting/company lists reflect one person's job search and are meant to be edited for your own.
