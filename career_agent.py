"""Main orchestration: scrape -> parse -> dedupe -> approve -> register -> calendar -> log.

Modes:
  python career_agent.py                              # events pipeline (default)
  python career_agent.py --events-only                # events pipeline (explicit)
  python career_agent.py --jobs-only                  # job-posting + recruiter-discovery pipeline
  python career_agent.py --recruiter                  # discover recruiters at all target companies
  python career_agent.py --recruiter Google           # discover at specific company only
  python career_agent.py --outreach --scrape-only --id 3   # print recruiter's profile text for Claude to draft from
  python career_agent.py --outreach --save-draft --id 3     # save a drafted email (piped via stdin) for recruiter id=3
  python career_agent.py --list-recruiters            # print all discovered recruiters
"""
import datetime
import logging
import pathlib
import sys

import scraper
import parser as event_parser
import job_sources
import linkedin_source
import filters
import digest

LOG_FILE = pathlib.Path(__file__).parent / "logs" / "agent.log"
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# TTL guardrail for auto-triggered recruiter discovery: once a company has a
# recruiters row younger than this, skip re-scraping LinkedIn for it. Keeps
# recruiter discovery from firing every time a new job posting shows up for a
# company we've already scraped recently.
RECRUITER_DISCOVERY_TTL_DAYS = 30


def present_for_approval(events):
    print(f"\nFound {len(events)} new career events. Review and approve:\n")
    for i, ev in enumerate(events, 1):
        when = ev["date"] + (f" @ {ev['time']} {ev.get('timezone', '')}" if ev.get("time") else "")
        print(f"[{i}] {ev['company']} — {ev['title']} — {when} ({ev.get('location', '?')})")
        print(f"    Register: {ev['url']}")
        print(f"    Source: {ev.get('source', 'web')}\n")
    choice = input("Enter numbers to approve (e.g. 1,3,5), 'all', or 'skip': ").strip().lower()
    if choice == "skip":
        return []
    if choice == "all":
        return events
    idx = {int(n) for n in choice.replace(" ", "").split(",") if n.isdigit()}
    return [ev for i, ev in enumerate(events, 1) if i in idx]


def main():
    logging.info("Run started")
    scraper.main(use_playwright=True)

    all_events = []
    for raw_file in (scraper.RAW_DIR).glob("*.txt"):
        text = raw_file.read_text()
        if text.startswith("URL:") and "ERROR:" not in text[:200]:
            try:
                all_events += event_parser.parse_with_claude(text)
            except Exception as e:
                logging.warning("Parse failed for %s: %s", raw_file.name, e)

    today = datetime.date.today().isoformat()
    all_events = [e for e in all_events if e.get("date", "") >= today]
    new_events = event_parser.insert_events(all_events)
    logging.info("Parsed %d events, %d new", len(all_events), len(new_events))

    if not new_events:
        print("No new events found.")
        return

    approved = present_for_approval(new_events)
    for ev in approved:
        print(f"-> Approved: {ev['title']}. Register at {ev['url']}, then sync with calendar_sync.add_to_calendar(ev).")
        logging.info("Approved: %s | %s | %s", ev["company"], ev["title"], ev["url"])


_LINKEDIN_STATUS_NOTES = {
    "no-session": "LinkedIn: no session",
    "throttled": "LinkedIn: throttled",
    "checkpoint": "LinkedIn: checkpoint hit, aborted",
    "error": "LinkedIn: error",
}


def _init_recruiter_checks_table(con):
    """Create the `recruiter_checks` bookkeeping table if absent.

    This is separate from (and does NOT touch) recruiter_finder.py's
    `recruiters` table/schema. It tracks "when did we last ATTEMPT LinkedIn
    discovery for this company" -- updated unconditionally after every call
    to discover_recruiters(), regardless of how many rows it inserted. This
    is intentionally distinct from `recruiters.first_seen`, which only
    reflects when a specific recruiter row was first inserted and is never
    touched again (INSERT OR IGNORE no-ops on repeat finds).
    """
    con.execute(
        """CREATE TABLE IF NOT EXISTS recruiter_checks (
            company TEXT PRIMARY KEY,
            last_attempted TEXT
        )"""
    )
    con.commit()


def _maybe_discover_recruiters(company):
    """Auto-trigger recruiter discovery for `company`, throttled by a TTL.

    Skips (no LinkedIn hit) if this company was already CHECKED -- a
    discovery attempt made, successful or not -- within
    RECRUITER_DISCOVERY_TTL_DAYS, tracked in the `recruiter_checks` table.
    This is deliberately independent of whether `recruiters` gained any new
    rows: discover_recruiters() writes via `INSERT OR IGNORE` against a
    `UNIQUE(company, name)` constraint, so re-scraping a company with a
    stable recruiting roster (the common case) finds the same people every
    time and silently no-ops on every row -- `first_seen` is only set at
    insertion and never refreshed. Keying the throttle off
    `recruiters.first_seen` alone would only catch a company's very first
    successful discovery; every new job posting after that would re-trigger
    a live LinkedIn scrape, defeating the 30-day throttle the user requires
    to keep this ToS-violating automation within an accepted risk boundary.

    Also skips if the company has no known TARGET_COMPANIES entry (the known
    gap for newer ATS-only companies). Otherwise runs discovery scoped to
    this single company, unconditionally records the check attempt (even if
    zero new recruiters were found), and returns the newly-added recruiter
    dicts (shaped for digest.run_digest).
    """
    import recruiter_finder

    # first_seen / last_attempted are both stored as SQLite CURRENT_TIMESTAMP
    # ("YYYY-MM-DD HH:MM:SS", UTC) -- format `now`/the cutoff identically so
    # string comparison stays valid across both tables.
    now = datetime.datetime.now(datetime.timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (now - datetime.timedelta(days=RECRUITER_DISCOVERY_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    con = recruiter_finder.init_db()
    _init_recruiter_checks_table(con)
    fresh = con.execute(
        "SELECT 1 FROM recruiter_checks WHERE company = ? AND last_attempted >= ? LIMIT 1",
        (company, cutoff),
    ).fetchone()
    con.close()

    if fresh:
        logging.info("Recruiter discovery skipped for %s: checked <%dd ago (recruiter_checks)",
                      company, RECRUITER_DISCOVERY_TTL_DAYS)
        return []

    matched = [c for c in recruiter_finder.TARGET_COMPANIES if c["name"].lower() == company.lower()]
    if not matched:
        logging.info("Recruiter discovery skipped for %s: no TARGET_COMPANIES entry (known gap)", company)
        return []

    n = recruiter_finder.discover_recruiters(companies=[matched[0]], max_per_company=10, interactive=False)
    logging.info("Recruiter discovery for %s: %d new recruiter(s)", company, n)

    # Record the attempt unconditionally -- even 0 new recruiters means we
    # just checked LinkedIn for this company and must not check again for
    # RECRUITER_DISCOVERY_TTL_DAYS, no matter how many new jobs show up.
    con = recruiter_finder.init_db()
    _init_recruiter_checks_table(con)
    con.execute(
        "INSERT OR REPLACE INTO recruiter_checks (company, last_attempted) VALUES (?, ?)",
        (company, now_str),
    )
    con.commit()
    con.close()

    if not n:
        return []

    con = recruiter_finder.init_db()
    rows = con.execute(
        "SELECT name, company, title, email, email_confidence, linkedin_url"
        " FROM recruiters WHERE company = ? AND first_seen >= ?",
        (company, cutoff),
    ).fetchall()
    con.close()

    return [
        {"name": r[0], "company": r[1], "title": r[2], "email": r[3],
         "email_confidence": r[4], "linkedin_url": r[5]}
        for r in rows
    ]


def run_jobs_pipeline():
    """Fetch job postings (ATS boards + trackers + LinkedIn), filter to targets,
    insert new ones, auto-trigger recruiter discovery per new-job company, and
    send the digest. Returns (new_jobs, collected_recruiters)."""
    logging.info("Jobs pipeline run started")
    notes = []
    all_jobs = []

    try:
        all_jobs += job_sources.fetch_ats_boards()
    except Exception as e:
        logging.warning("fetch_ats_boards failed: %s", e)

    try:
        all_jobs += job_sources.fetch_trackers()
    except Exception as e:
        logging.warning("fetch_trackers failed: %s", e)

    li_jobs, li_status = linkedin_source.fetch_linkedin()
    all_jobs += li_jobs
    if li_status != "ok":
        notes.append(_LINKEDIN_STATUS_NOTES.get(li_status, f"LinkedIn: {li_status}"))

    targeted_jobs = [j for j in all_jobs if filters.is_target(j.get("title", ""), j.get("description", ""))]
    for job in targeted_jobs:
        job["match_score"] = filters.match_strength(job["title"])

    new_jobs = job_sources.insert_jobs(targeted_jobs)
    logging.info("Jobs pipeline: %d fetched, %d targeted, %d new", len(all_jobs), len(targeted_jobs), len(new_jobs))

    companies = sorted({j["company"] for j in new_jobs if j.get("company")})
    collected_recruiters = []
    for company in companies:
        try:
            collected_recruiters += _maybe_discover_recruiters(company)
        except Exception as e:
            logging.warning("Recruiter discovery failed for %s: %s", company, e)

    digest.run_digest(new_jobs, new_recruiters=collected_recruiters, notes=notes)

    return new_jobs, collected_recruiters


def recruiter_mode(args):
    import recruiter_finder

    if "--list" in args or "--list-recruiters" in args:
        recruiter_finder.list_recruiters()
        return

    company_filter = None
    for arg in args:
        if not arg.startswith("--"):
            matches = [c for c in recruiter_finder.TARGET_COMPANIES if c["name"].lower() == arg.lower()]
            if matches:
                company_filter = matches
                print(f"Filtering to: {matches[0]['name']}")
            else:
                print(f"Unknown company '{arg}'. Searching all companies.")

    n = recruiter_finder.discover_recruiters(companies=company_filter)
    logging.info("Recruiter discovery: %d new recruiters added", n)
    recruiter_finder.list_recruiters()


def outreach_mode(args):
    import outreach, sys as _sys
    _sys.argv = ["outreach.py"] + args
    outreach.main()


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--recruiter" in args or "--list-recruiters" in args:
        remaining = [a for a in args if a not in ("--recruiter",)]
        recruiter_mode(remaining)
    elif "--outreach" in args:
        remaining = [a for a in args if a != "--outreach"]
        outreach_mode(remaining)
    elif "--jobs-only" in args:
        run_jobs_pipeline()
    elif "--events-only" in args:
        main()
    else:
        main()
