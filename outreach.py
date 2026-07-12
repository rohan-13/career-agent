"""LinkedIn profile scraper and outreach draft manager.

Designed to be orchestrated by Claude Code, which handles the AI drafting.
No ANTHROPIC_API_KEY needed in this script.

Modes:
  python outreach.py --scrape-only --id <N>       # scrape LinkedIn, print profile text to stdout
  python outreach.py --scrape-only <linkedin_url> # scrape by URL, print to stdout
  python outreach.py --save-draft --id <N>        # read draft from stdin, save to events.db
  python outreach.py --list                       # print all recruiters with draft status
  python outreach.py --show-draft --id <N>        # print saved draft for recruiter N
"""
import asyncio
import pathlib
import sqlite3
import sys

from dotenv import load_dotenv

import linkedin_session

load_dotenv(pathlib.Path(__file__).parent / ".env")

DB_PATH = pathlib.Path(__file__).parent / "events.db"


# ── LinkedIn scraping ──────────────────────────────────────────────────────────

async def _scrape_with_playwright(url):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=linkedin_session.USER_AGENT,
        )

        page = await linkedin_session.get_authenticated_page(context, url)

        for _ in range(3):
            await page.keyboard.press("End")
            await page.wait_for_timeout(1200)

        text = await page.inner_text("body")
        await browser.close()
        return text


def scrape_profile(url):
    return asyncio.run(_scrape_with_playwright(url))


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_recruiter(recruiter_id):
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT id, name, company, title, email, linkedin_url, status, email_draft FROM recruiters WHERE id = ?",
        (recruiter_id,),
    ).fetchone()
    con.close()
    return row


def save_draft(recruiter_id, draft_text):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE recruiters SET email_draft = ?, status = 'draft_ready' WHERE id = ?",
        (draft_text, recruiter_id),
    )
    con.commit()
    con.close()


def list_recruiters():
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            "SELECT id, name, company, title, email, status FROM recruiters ORDER BY company, name"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()

    if not rows:
        print("No recruiters in events.db yet. Run recruiter_finder.py first.")
        return

    print(f"\n{'ID':>4}  {'Company':<14} {'Name':<22} {'Title':<28} {'Email':<35} Status")
    print("-" * 115)
    for rid, name, company, title, email, status in rows:
        print(f"{rid:>4}  {company:<14} {name:<22} {(title or ''):<28} {(email or '(none)'):<35} {status or ''}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--list" in args:
        list_recruiters()
        return

    if "--show-draft" in args:
        rid = None
        if "--id" in args:
            rid = int(args[args.index("--id") + 1])
        if not rid:
            print("Usage: --show-draft --id <N>")
            return
        row = _get_recruiter(rid)
        if row and row[7]:
            print(row[7])
        else:
            print(f"No draft saved for recruiter id={rid}")
        return

    if "--save-draft" in args:
        rid = None
        if "--id" in args:
            rid = int(args[args.index("--id") + 1])
        if not rid:
            print("Usage: --save-draft --id <N>  (pipe draft text via stdin)")
            sys.exit(1)
        draft_text = sys.stdin.read().strip()
        if not draft_text:
            print("No draft text received on stdin.", file=sys.stderr)
            sys.exit(1)
        save_draft(rid, draft_text)
        print(f"Draft saved for recruiter id={rid}.")
        return

    if "--scrape-only" in args:
        linkedin_url = None
        recruiter_id = None

        if "--id" in args:
            recruiter_id = int(args[args.index("--id") + 1])
            row = _get_recruiter(recruiter_id)
            if not row:
                print(f"No recruiter with id={recruiter_id}", file=sys.stderr)
                sys.exit(1)
            linkedin_url = row[5]
            print(f"Recruiter: {row[1]} @ {row[2]}", file=sys.stderr)

        for arg in args:
            if arg.startswith("http"):
                linkedin_url = arg

        if not linkedin_url:
            print("Provide --id <N> or a LinkedIn URL.", file=sys.stderr)
            sys.exit(1)

        print(f"Scraping {linkedin_url} ...", file=sys.stderr)
        text = scrape_profile(linkedin_url)
        # Print profile text to stdout so Claude Code can read it
        print(text)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
