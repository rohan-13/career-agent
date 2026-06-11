"""Job-posting pipeline: fetchers for ATS boards, GitHub trackers, and startup
boards, plus the jobs table in events.db. (LinkedIn lives in linkedin_source.py.)

All fetchers return dicts: {title, company, location, url, posted_date, source}.
"""
import datetime
import json
import logging
import pathlib
import re

import requests
from rapidfuzz import fuzz

DB_PATH = pathlib.Path(__file__).parent / "events.db"


def init_jobs_table(db_path=None):
    import sqlite3

    # Resolve at call time so tests can monkeypatch DB_PATH after import.
    con = sqlite3.connect(db_path or DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, company TEXT, location TEXT,
            url TEXT UNIQUE,
            source TEXT, posted_date TEXT,
            match_score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    con.commit()
    return con


# 85 matches parser.py's events threshold and catches cross-source title
# variants like "Software Engineer, New Grad" vs "... New Grad (2027)".
def _is_duplicate(con, job, threshold=85):
    rows = con.execute("SELECT title FROM jobs WHERE company = ?", (job["company"],)).fetchall()
    return any(fuzz.token_sort_ratio(job["title"], r[0]) >= threshold for r in rows)


def insert_jobs(jobs, db_path=None):
    """Dedupe (URL exact + company/title fuzzy) and insert; returns new jobs."""
    con = init_jobs_table(db_path)
    new = []
    for job in jobs:
        if con.execute("SELECT 1 FROM jobs WHERE url = ?", (job["url"],)).fetchone():
            logging.debug("skip dup url: %s", job["url"])
            continue
        if _is_duplicate(con, job):
            logging.debug("skip fuzzy dup: %s @ %s", job["title"], job["company"])
            continue
        con.execute(
            "INSERT OR IGNORE INTO jobs (title, company, location, url, source, posted_date, match_score)"
            " VALUES (?,?,?,?,?,?,?)",
            (job["title"], job["company"], job.get("location", ""), job["url"],
             job.get("source", "web"), job.get("posted_date", ""), job.get("match_score", 0)),
        )
        new.append(job)
    con.commit()
    con.close()
    return new
