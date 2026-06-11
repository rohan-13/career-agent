"""Phase 3: Claude parsing of raw scraped content into structured event JSON, plus dedupe."""
import json
import os
import pathlib
import sqlite3

from rapidfuzz import fuzz

DB_PATH = pathlib.Path(__file__).parent / "events.db"
RAW_DIR = pathlib.Path(__file__).parent / "data" / "raw"

PARSE_PROMPT = """
You are parsing content for career events at tech companies.

Candidate profile: university student graduating May 2027 (B.S. Data Science, multiple
SWE internships). Targets NEW GRAD / early-career opportunities in Software Engineering,
Data Science, Data Engineering, and ML Engineering.

Given the raw text below, extract any career-related events. Only include events that are:
- Hosted by or about a notable tech/business company
- Related to careers, hiring, recruiting, networking, internships, or professional development
- Relevant to the candidate profile: new-grad / university / early-career / campus events
  and SWE/DS/DE/MLE role openings. EXCLUDE warehouse/hourly hiring, mid-career or
  executive networking, and sales-track sessions.
- Happening in the future (today or later), or within the next 90 days
- ALSO treat "New Grad 2027" role application windows opening as events
  (date = posting date, url = application link, title = "New Grad opening: <role>")

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


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, company TEXT, date TEXT, time TEXT, timezone TEXT,
            location TEXT, url TEXT, description TEXT, source TEXT,
            status TEXT DEFAULT 'new',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, date, title)
        )"""
    )
    con.commit()
    return con


def parse_with_claude(raw_content):
    """Send raw content to Claude for extraction. Requires ANTHROPIC_API_KEY.

    When this project is driven interactively by Claude Code, the host model
    does this extraction itself and calls insert_events() directly instead.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": PARSE_PROMPT.replace("{raw_content}", raw_content[:100000])}],
    )
    return json.loads(msg.content[0].text)


def is_duplicate(con, event, threshold=85):
    rows = con.execute("SELECT title FROM events WHERE company = ? AND date = ?", (event["company"], event["date"])).fetchall()
    return any(fuzz.token_sort_ratio(event["title"], r[0]) >= threshold for r in rows)


def insert_events(events):
    """Dedupe against events.db and insert; returns list of newly-inserted events."""
    con = init_db()
    new = []
    for ev in events:
        if is_duplicate(con, ev):
            continue
        con.execute(
            "INSERT OR IGNORE INTO events (title, company, date, time, timezone, location, url, description, source) VALUES (?,?,?,?,?,?,?,?,?)",
            (ev["title"], ev["company"], ev["date"], ev.get("time"), ev.get("timezone"), ev.get("location"), ev["url"], ev.get("description"), ev.get("source", "web")),
        )
        new.append(ev)
    con.commit()
    con.close()
    return new


if __name__ == "__main__":
    con = init_db()
    print(f"events.db ready at {DB_PATH}")
    for row in con.execute("SELECT company, date, title, status FROM events ORDER BY date"):
        print(row)
