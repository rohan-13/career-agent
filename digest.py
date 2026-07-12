"""Job + recruiter digest: scoring, markdown rendering, email delivery.

Consumed by the future orchestration layer (Task 4) via `run_digest`, which
is called after each jobs+recruiter pipeline run with the newly-inserted
job and recruiter dicts.

Job dicts follow job_sources.py's `jobs` table schema:
    title, company, location, url, source, posted_date, match_score, status, first_seen
Recruiter dicts follow recruiter_finder.py's `recruiters` table schema:
    name, company, title, email, email_confidence, linkedin_url, source, status,
    email_draft, first_seen
"""
import datetime
import logging
import os
import pathlib
import smtplib
import sqlite3
import sys
from email.mime.text import MIMEText

from dotenv import load_dotenv

import job_sources

load_dotenv(pathlib.Path(__file__).parent / ".env")

DB_PATH = pathlib.Path(__file__).parent / "events.db"
DIGEST_DIR = pathlib.Path(__file__).parent / "digests"

# Sources emitted directly by fetch_ats_boards() (see job_sources.py's
# parse_greenhouse/parse_lever/parse_ashby) vs. secondary sources (GitHub
# trackers, LinkedIn) that are slower/noisier to reach.
_DIRECT_ATS_SOURCES = {"greenhouse", "lever", "ashby"}


# ── Scoring ──────────────────────────────────────────────────────────────────

def score(job, today=None):
    """Rank score for a job: target-company bonus + match_score + recency + ATS-source bonus.

    Defensive by design: a missing/None match_score is treated as 0, and a
    missing/malformed posted_date contributes no recency bonus (never raises).
    """
    today = today or datetime.date.today()
    total = 0

    # Target-company bonus: keeps in sync with job_sources.ATS_BOARDS as it grows.
    if job.get("company") in job_sources.ATS_BOARDS.keys():
        total += 3

    total += job.get("match_score") or 0

    posted = job.get("posted_date")
    if posted:
        try:
            posted_date = datetime.date.fromisoformat(str(posted)[:10])
            age_days = (today - posted_date).days
            if 0 <= age_days <= 3:
                total += 2
            elif 0 <= age_days <= 7:
                total += 1
        except (ValueError, TypeError):
            pass  # malformed/garbage date: no recency bonus, don't crash

    if job.get("source") in _DIRECT_ATS_SOURCES:
        total += 1

    return total


# ── Rendering ────────────────────────────────────────────────────────────────

def render_markdown(jobs, recruiters, date_str, notes=(), today=None):
    """Render the digest body: notes, ranked jobs table, recruiters-by-company section."""
    ranked = sorted(jobs, key=lambda j: score(j, today=today), reverse=True)

    lines = [f"# Job Digest — {date_str}", ""]

    if notes:
        lines.append("## Notes")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append(f"## Jobs ({len(ranked)})")
    lines.append("")
    if ranked:
        lines.append("| Score | Title | Company | Location | Source | Posted | Link |")
        lines.append("|---|---|---|---|---|---|---|")
        for job in ranked:
            lines.append(
                f"| {score(job, today=today)} "
                f"| {job.get('title', '')} "
                f"| {job.get('company', '')} "
                f"| {job.get('location', '')} "
                f"| {job.get('source', '')} "
                f"| {job.get('posted_date', '')} "
                f"| [link]({job.get('url', '')}) |"
            )
    else:
        lines.append("_No new jobs this run._")
    lines.append("")

    lines.append(f"## Recruiters ({len(recruiters)})")
    lines.append("")
    if recruiters:
        by_company = {}
        for r in recruiters:
            by_company.setdefault(r.get("company", ""), []).append(r)
        for company in sorted(by_company):
            lines.append(f"### {company}")
            lines.append("")
            lines.append("| Name | Title | Email | Confidence | LinkedIn |")
            lines.append("|---|---|---|---|---|")
            for r in by_company[company]:
                lines.append(
                    f"| {r.get('name', '')} "
                    f"| {r.get('title', '')} "
                    f"| {r.get('email', '')} "
                    f"| {r.get('email_confidence', '')} "
                    f"| [profile]({r.get('linkedin_url', '')}) |"
                )
            lines.append("")
    else:
        lines.append("_No new recruiters this run._")
        lines.append("")

    return "\n".join(lines)


# ── Email ────────────────────────────────────────────────────────────────────

def send_email(subject, body):
    """Send the digest via Gmail SMTP. Gracefully skips (returns False) if unconfigured."""
    password = os.getenv("GMAIL_APP_PASSWORD")
    to_addr = os.getenv("DIGEST_TO")

    if not password or not to_addr:
        msg_text = "send_email: GMAIL_APP_PASSWORD or DIGEST_TO not set; skipping email send."
        logging.warning(msg_text)
        print(msg_text, file=sys.stderr)
        return False

    from_addr = os.getenv("USER_EMAIL")
    if not from_addr:
        msg_text = (
            "send_email: USER_EMAIL not set; skipping email send "
            "(refusing to log in with the recipient's address as the username)."
        )
        logging.warning(msg_text)
        print(msg_text, file=sys.stderr)
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        msg_text = f"send_email failed: {e}"
        logging.warning(msg_text)
        print(msg_text, file=sys.stderr)
        return False


# ── Main entry point ────────────────────────────────────────────────────────

def run_digest(new_jobs, new_recruiters=(), notes=(), db_path=None):
    """Write today's digest file, print a terminal summary, email it, and flip job status.

    Returns the path to the written digest markdown file.
    """
    new_jobs = list(new_jobs)
    new_recruiters = list(new_recruiters)
    date_str = datetime.date.today().isoformat()

    body = render_markdown(new_jobs, new_recruiters, date_str, notes=notes)

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    digest_path = DIGEST_DIR / f"jobs-{date_str}.md"
    digest_path.write_text(body)

    ranked = sorted(new_jobs, key=lambda j: score(j), reverse=True)
    print(f"\n=== Job Digest {date_str} ===")
    print(f"{len(new_jobs)} new job(s), {len(new_recruiters)} new recruiter(s)")
    for job in ranked[:10]:
        print(f"  [{score(job)}] {job.get('title', '')} @ {job.get('company', '')} — {job.get('url', '')}")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  - {note}")

    send_email(f"Job Digest — {date_str}", body)

    urls = [j["url"] for j in new_jobs if j.get("url")]
    if urls:
        con = sqlite3.connect(db_path or DB_PATH)
        con.executemany(
            "UPDATE jobs SET status = 'digested' WHERE url = ?",
            [(u,) for u in urls],
        )
        con.commit()
        con.close()

    return digest_path
