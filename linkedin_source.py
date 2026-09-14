"""LinkedIn job-search source: FAANG + any other non-ATS company coverage.

`job_sources.py` only covers companies with public ATS APIs (Greenhouse/
Lever/Ashby). Google, Apple, Amazon, Meta, Microsoft, and everyone else who
runs a custom/Workday-style careers site have no such API, so this module
gets their postings by scraping LinkedIn's public job-search results while
logged in.

This is a ToS-sensitive path (LinkedIn does not want automated, logged-in
scraping), so real safety mitigations are load-bearing, not decoration:
  - `allowed_to_run()` throttles to one run per 12 hours via `.linkedin_last_run`.
  - `fetch_linkedin()` hard-caps at 40 page loads per run.
  - Randomized 3-8s pauses between navigations.
  - Any checkpoint/CAPTCHA/login-wall redirect aborts the whole run
    immediately — no retry.

Queries reuse `filters.py`'s real new-grad/entry-level role vocabulary.
LinkedIn's own `f_E=2` filter is only a coarse pre-filter; every result
returned here still needs to be run through `filters.is_target()` downstream
before being treated as a match.
"""
import asyncio
import datetime
import logging
import os
import pathlib
import random
from urllib.parse import quote

from dotenv import load_dotenv

import linkedin_session

load_dotenv(pathlib.Path(__file__).parent / ".env")

LAST_RUN_PATH = pathlib.Path(__file__).parent / ".linkedin_last_run"
MIN_INTERVAL_HOURS = 12
MAX_PAGE_LOADS = 40
PAUSE_RANGE_SECONDS = (3, 8)
RESULTS_PER_PAGE = 25

# Real role/qualifier vocabulary from filters.py's ROLE_PATTERNS/INCLUDE_PATTERNS
# (not invented phrasing) — e.g. "software engineer" matches
# r"software\s+engineer", "new grad" matches r"new[\s-]*grad", etc.
# "2027 start date" catches postings phrased around a start date/cohort year
# rather than "new grad"/"entry level" (still covered downstream by
# filters.py's bare r"\b2027\b" INCLUDE_PATTERN either way).
_ROLE_TERMS = [
    "software engineer",
    "data scientist",
    "data engineer",
    "machine learning engineer",
    "software developer",
]
_QUALIFIER_TERMS = ["new grad", "entry level", "2027 start date"]

SEARCH_QUERIES = [f"{role} {qualifier}" for role in _ROLE_TERMS for qualifier in _QUALIFIER_TERMS]


def job_search_url(query, start=0):
    """Build a LinkedIn job-search URL for `query`, paginated at `start`.

    f_E=2   -> entry-level experience filter (LinkedIn's own coarse pre-filter)
    f_TPR=r604800 -> postings from the last 7 days (604800 seconds)
    """
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote(query)}&f_E=2&f_TPR=r604800&start={start}"
    )


def allowed_to_run(now=None):
    """True if at least MIN_INTERVAL_HOURS have passed since the last recorded run.

    Reads the timestamp from LAST_RUN_PATH; missing/unparseable file means
    "never run before" -> allowed.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not LAST_RUN_PATH.exists():
        return True
    try:
        last_run = datetime.datetime.fromisoformat(LAST_RUN_PATH.read_text().strip())
    except (ValueError, OSError):
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=datetime.timezone.utc)
    return now - last_run >= datetime.timedelta(hours=MIN_INTERVAL_HOURS)


def _record_run(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    LAST_RUN_PATH.write_text(now.isoformat())


def _has_session_material():
    """True if we can plausibly get logged in without a human at the keyboard:
    either saved cookies already exist, or auto-fill credentials are configured."""
    if linkedin_session.COOKIES_PATH.exists():
        return True
    return bool(os.getenv("LINKEDIN_EMAIL") and os.getenv("LINKEDIN_PASSWORD"))


async def _extract_jobs(page):
    """Best-effort extraction of job cards from a LinkedIn job-search results page.

    NOTE: LinkedIn's DOM/selectors are not covered by automated tests (see
    tests/test_linkedin_source.py + CLAUDE.md) since they require a live,
    logged-in browser session. Verify selectors still match via a manual
    smoke test before relying on this in production.
    """
    return await page.evaluate("""() => {
        const results = [];
        const cards = document.querySelectorAll(
            'div.job-search-card, li.jobs-search-results__list-item, div.base-card'
        );
        cards.forEach(card => {
            const link = card.querySelector('a.base-card__full-link, a[href*="/jobs/view/"]');
            const titleEl = card.querySelector('h3.base-search-card__title, .job-search-card__title');
            const companyEl = card.querySelector('h4.base-search-card__subtitle, .job-search-card__subtitle-link');
            const locationEl = card.querySelector('.job-search-card__location');
            const dateEl = card.querySelector('time');
            if (!link || !titleEl) return;
            results.push({
                title: titleEl.innerText.trim(),
                company: companyEl ? companyEl.innerText.trim() : '',
                location: locationEl ? locationEl.innerText.trim() : '',
                url: link.href.split('?')[0],
                posted_date: dateEl ? (dateEl.getAttribute('datetime') || '') : '',
            });
        });
        return results;
    }""")


async def _fetch(headless):
    from playwright.async_api import async_playwright

    jobs_by_url = {}
    page_loads = 0
    status = "ok"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=linkedin_session.USER_AGENT,
        )

        page = None
        aborted = False

        for query in SEARCH_QUERIES:
            if aborted:
                break

            start = 0
            while True:
                if page_loads >= MAX_PAGE_LOADS:
                    aborted = True
                    break

                url = job_search_url(query, start=start)

                try:
                    if page is None:
                        # First navigation of the run: establish/verify the session.
                        # interactive=False -- never block on input() with no human
                        # present; if login can't complete, we'll detect the
                        # checkpoint/authwall below and abort, no retry.
                        page = await linkedin_session.get_authenticated_page(
                            context, url, interactive=False
                        )
                    else:
                        await asyncio.sleep(random.uniform(*PAUSE_RANGE_SECONDS))
                        await page.goto(url, wait_until="networkidle", timeout=45000)
                except Exception as e:
                    logging.warning(
                        "LinkedIn navigation error for %r (start=%s): %s", query, start, e
                    )
                    status = "error"
                    aborted = True
                    break

                page_loads += 1

                if linkedin_session.is_checkpoint_url(page.url):
                    logging.warning(
                        "LinkedIn checkpoint/CAPTCHA/login-wall redirect at %s "
                        "-- aborting run, no retry.", page.url
                    )
                    status = "checkpoint"
                    aborted = True
                    break

                cards = await _extract_jobs(page)
                if not cards:
                    break  # no more results for this query; move to the next one

                for c in cards:
                    if c["url"] and c["url"] not in jobs_by_url:
                        c["source"] = "linkedin"
                        jobs_by_url[c["url"]] = c

                start += RESULTS_PER_PAGE

        await browser.close()

    return list(jobs_by_url.values()), status


def fetch_linkedin(headless=True):
    """Fetch new-grad/entry-level job postings from LinkedIn search.

    Returns (jobs, status) with status in:
      ok         -- completed at least one successful page load, jobs may be []
      no-session -- no saved cookies and no LINKEDIN_EMAIL/LINKEDIN_PASSWORD;
                    refuses to open a browser at all rather than risk hanging
                    on an interactive login prompt with no human present
      throttled  -- called again within MIN_INTERVAL_HOURS of the last run
      checkpoint -- LinkedIn redirected to a checkpoint/CAPTCHA/login-wall;
                    aborted immediately, no retry
      error      -- an unexpected exception occurred during the run

    The 12-hour throttle, 40-page-load cap, randomized pauses, and immediate
    abort-on-checkpoint are safety mitigations for scraping LinkedIn while
    logged in (against LinkedIn's ToS) -- they are not tunable for
    convenience without re-evaluating that risk.
    """
    if not allowed_to_run():
        return [], "throttled"

    if not _has_session_material():
        return [], "no-session"

    # Record the attempt before running so a checkpoint/error doesn't leave the
    # door open for an immediate retry -- the throttle applies to attempts,
    # not just successes.
    _record_run()

    try:
        jobs, status = asyncio.run(_fetch(headless))
    except Exception as e:
        logging.warning("fetch_linkedin failed: %s", e)
        return [], "error"

    return jobs, status
