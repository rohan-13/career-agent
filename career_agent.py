"""Main orchestration: scrape -> parse -> dedupe -> approve -> register -> calendar -> log.

Modes:
  python career_agent.py                              # events pipeline (default)
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

LOG_FILE = pathlib.Path(__file__).parent / "logs" / "agent.log"
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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
    else:
        main()
