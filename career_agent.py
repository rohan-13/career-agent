"""Main orchestration: scrape -> parse -> dedupe -> approve -> register -> calendar -> log."""
import datetime
import logging
import pathlib

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


if __name__ == "__main__":
    main()
