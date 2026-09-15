"""Job-posting pipeline: fetchers for ATS boards, GitHub trackers, and startup
boards, plus the jobs table in events.db. (LinkedIn lives in linkedin_source.py.)

All fetchers return dicts: {title, company, location, url, posted_date, source}.
"""
import datetime
import html
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
# COLLATE NOCASE: different sources capitalize the same company differently
# (Simplify's tracker says "Autostore", speedyapply's says "AutoStore") --
# without this, a case-sensitive company match misses the fuzzy title check
# entirely and both rows get inserted as if they were different companies.
def _is_duplicate(con, job, threshold=85):
    rows = con.execute(
        "SELECT title FROM jobs WHERE company = ? COLLATE NOCASE", (job["company"],)
    ).fetchall()
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


# --- ATS boards (structured JSON, no LLM needed) ---
# posted_date semantics differ: greenhouse=updated_at (bumps on edits), ashby=publishedAt, lever=createdAt (UTC).

# company: (ats, slug). Slugs verified live in Task 3 Step 5; fix any that 404.
ATS_BOARDS = {
    "Stripe": ("greenhouse", "stripe"),
    "Airbnb": ("greenhouse", "airbnb"),
    "OpenAI": ("ashby", "openai"),   # verified 2026-06-11: moved from Greenhouse to Ashby
    "Anthropic": ("greenhouse", "anthropic"),
    "Figma": ("greenhouse", "figma"),
    "Notion": ("ashby", "notion"),
    "Ramp": ("ashby", "ramp"),
    "Plaid": ("ashby", "plaid"),     # verified 2026-06-11: moved from Lever to Ashby (Lever returns 0 jobs)
    # Task 2 expansion: 15 new companies (live-verified 2026-07-10)
    "Databricks": ("greenhouse", "databricks"),
    "Scale AI": ("greenhouse", "scaleai"),
    "Brex": ("greenhouse", "brex"),
    "Coinbase": ("greenhouse", "coinbase"),
    "Snowflake": ("ashby", "snowflake"),
    "Confluent": ("ashby", "confluent"),
    "MongoDB": ("greenhouse", "mongodb"),
    "Asana": ("greenhouse", "asana"),
    "Discord": ("greenhouse", "discord"),
    "Affirm": ("greenhouse", "affirm"),
    "Robinhood": ("greenhouse", "robinhood"),
    "Instacart": ("greenhouse", "instacart"),
    "Lyft": ("greenhouse", "lyft"),
    "Pinterest": ("greenhouse", "pinterest"),
    "Reddit": ("greenhouse", "reddit"),
}


def parse_greenhouse(data, company):
    return [
        {"title": j.get("title", ""), "company": company,
         "location": (j.get("location") or {}).get("name", ""),
         "url": j.get("absolute_url", ""),
         "posted_date": (j.get("updated_at") or "")[:10],
         "source": "greenhouse"}
        for j in data.get("jobs", [])
    ]


def parse_lever(data, company):
    return [
        {"title": j.get("text", ""), "company": company,
         "location": (j.get("categories") or {}).get("location", ""),
         "url": j.get("hostedUrl", ""),
         "posted_date": (datetime.datetime.fromtimestamp(j["createdAt"] / 1000, datetime.timezone.utc).date().isoformat()
                         if j.get("createdAt") else ""),
         "source": "lever"}
        for j in data
    ]


def parse_ashby(data, company):
    return [
        {"title": j.get("title", ""), "company": company,
         "location": j.get("location") or "",
         "url": j.get("jobUrl") or j.get("applyUrl") or "",
         "posted_date": (j.get("publishedAt") or "")[:10],
         "source": "ashby"}
        for j in data.get("jobs", [])
    ]


_ATS_ENDPOINTS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", parse_greenhouse),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}", parse_ashby),
}


def fetch_ats_boards():
    jobs = []
    for company, (ats, slug) in ATS_BOARDS.items():
        url_tmpl, parse = _ATS_ENDPOINTS[ats]
        try:
            res = requests.get(url_tmpl.format(slug=slug), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            res.raise_for_status()
            jobs += parse(res.json(), company)
        except Exception as e:
            logging.warning("ATS fetch failed for %s (%s/%s): %s", company, ats, slug, e)
    return jobs


# --- GitHub new-grad trackers ---
# Two README formats are in the wild: Simplify's HTML <tr><td> tables, and the
# markdown pipe-tables (| Company | Role | ... |) used by vanshb03/speedyapply.
# Each entry maps source -> (raw README url, format), format in {"html", "pipe"}.
#
# These are broad, community-maintained trackers covering hundreds of companies
# (startups included) beyond the ~23 in ATS_BOARDS -- added 2026-09-01 so the
# job pipeline isn't limited to a small hardcoded company list. Verify these
# repos are still alive periodically; they get renamed/archived year to year
# (e.g. cvrve/New-Grad-2027 -> vanshb03/New-Grad-2027).
TRACKER_REPOS = {
    "simplify": ("https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md", "html"),
    "vansh": ("https://raw.githubusercontent.com/vanshb03/New-Grad-2027/dev/README.md", "pipe"),
    "speedyapply": ("https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md", "pipe"),
    # Added 2026-09-14: speedyapply also maintains a SEPARATE repo specifically
    # for AI/Data-Science/ML new-grad roles (2027-AI-College-Jobs), distinct
    # from their SWE-only repo above -- same pipe-table format, but ~450 listings
    # not otherwise covered. Gap found when a DraftKings "Data Science Engineer
    # (December 2026 and May 2027 Grads)" posting the user found manually turned
    # out to be listed here (and nowhere else we track).
    "speedyapply-ai": ("https://raw.githubusercontent.com/speedyapply/2027-AI-College-Jobs/main/NEW_GRAD_USA.md", "pipe"),
}

_HREF_RE = re.compile(r'href="([^"]+)"')
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _first_url(cell):
    m = _HREF_RE.search(cell)
    if m:
        return m.group(1)
    m = _MD_LINK_RE.search(cell)
    return m.group(2) if m else ""


def _strip_tags(text):
    return html.unescape(_TAG_RE.sub("", text).replace("**", "")).strip()


_AGE_UNIT_DAYS = {"d": 1, "w": 7, "mo": 30, "y": 365}


def _age_to_date(cell):
    cell = cell.strip()
    if cell.lower() == "today":
        return datetime.date.today().isoformat()
    m = re.fullmatch(r"(\d+)(d|w|mo|y)", cell)
    if m:
        days = int(m.group(1)) * _AGE_UNIT_DAYS[m.group(2)]
        return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return ""


def parse_tracker_markdown(md, source):
    """Parse GitHub new-grad tracker READMEs.

    Supports the HTML <tr><td> format used by SimplifyJobs/New-Grad-Positions
    (each <td> on its own line, grouped by <tr> blocks).
    """
    jobs, last_company = [], None
    # Split into <tr>...</tr> blocks; each block has 4-5 <td> lines
    row_blocks = re.split(r"<tr>", md)
    for block in row_blocks:
        cells = _TD_RE.findall(block)
        if len(cells) < 4:
            continue
        company_raw = cells[0].strip()
        company = _strip_tags(company_raw)
        if company in {"↳", ""}:
            company = last_company
        else:
            last_company = company
        if not company:
            continue
        url = _first_url(cells[3])
        if not url:
            continue  # locked (🔒) or no link
        title = _strip_tags(cells[1])
        location = _strip_tags(cells[2])
        age_cell = cells[4] if len(cells) > 4 else ""
        jobs.append({
            "title": title, "company": company, "location": location,
            "url": url, "posted_date": _age_to_date(age_cell.strip()),
            "source": source,
        })
    return jobs


# --- Markdown pipe-table trackers (vanshb03/New-Grad-2027, speedyapply/2027-SWE-College-Jobs) ---
# These use standard `| col | col |` markdown tables rather than Simplify's raw HTML.
# Column layout isn't fixed even within one file -- speedyapply's "Other" section
# drops the Salary column that its "FAANG+"/"Quant" sections have -- so each table's
# own header row is read to map column names to indices, rather than assuming
# fixed positions.

_PIPE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_PIPE_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")

_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTHDAY_RE = re.compile(r"^([A-Za-z]{3})[a-z]*\s+(\d{1,2})$")

# Header aliases -> the field they map to. Matching is case-insensitive against
# the table's own header cells, so a repo renaming "Role" to "Position" (as
# speedyapply does vs. vanshb03's "Role") still resolves correctly.
_PIPE_HEADER_ALIASES = {
    "company": {"company"},
    "title": {"position", "role", "title"},
    "location": {"location"},
    "link": {"application/link", "posting", "apply", "link"},
    "date": {"date posted", "age", "posted"},
}


def _split_pipe_row(line):
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _classify_pipe_headers(header_cells):
    col = {}
    for i, cell in enumerate(header_cells):
        key = cell.strip().lower()
        for field, aliases in _PIPE_HEADER_ALIASES.items():
            if field not in col and key in aliases:
                col[field] = i
    return col


def _monthday_to_date(cell):
    """Convert a bare 'Aug 05'-style date (no year) to an ISO date, inferring
    the year from today's date (rolls back a year if the month/day would
    otherwise land in the future -- these trackers only list recent postings)."""
    m = _MONTHDAY_RE.match(cell.strip())
    if not m:
        return ""
    month = _MONTH_NUM.get(m.group(1).lower())
    if not month:
        return ""
    day = int(m.group(2))
    today = datetime.date.today()
    try:
        d = datetime.date(today.year, month, day)
    except ValueError:
        return ""  # e.g. Feb 30 -- malformed, don't guess
    if d > today:
        d = datetime.date(today.year - 1, month, day)
    return d.isoformat()


def parse_tracker_pipe_markdown(md, source):
    """Parse GitHub new-grad trackers that use markdown pipe tables instead of
    Simplify's HTML <tr><td> format (vanshb03/New-Grad-2027, speedyapply/2027-SWE-College-Jobs).
    """
    lines = md.splitlines()
    jobs = []
    col = {}
    for i, line in enumerate(lines):
        if i > 0 and _PIPE_SEP_RE.match(line) and _PIPE_ROW_RE.match(lines[i - 1]):
            col = _classify_pipe_headers(_split_pipe_row(lines[i - 1]))
            continue
        if not col or "company" not in col or "title" not in col:
            continue
        if not _PIPE_ROW_RE.match(line):
            continue
        cells = _split_pipe_row(line)
        if len(cells) < 3 or col["company"] >= len(cells) or col["title"] >= len(cells):
            continue
        company = _strip_tags(cells[col["company"]])
        title = _strip_tags(cells[col["title"]])
        if not company or not title:
            continue
        location = _strip_tags(cells[col["location"]]) if "location" in col and col["location"] < len(cells) else ""
        link_cell = cells[col["link"]] if "link" in col and col["link"] < len(cells) else ""
        url = _first_url(link_cell)
        if not url:
            continue  # locked/closed row (🔒), or no application link yet
        date_cell = cells[col["date"]] if "date" in col and col["date"] < len(cells) else ""
        posted_date = _age_to_date(date_cell) or _monthday_to_date(date_cell)
        jobs.append({
            "title": title, "company": company, "location": location,
            "url": url, "posted_date": posted_date, "source": source,
        })
    return jobs


_TRACKER_PARSERS = {"html": parse_tracker_markdown, "pipe": parse_tracker_pipe_markdown}


def fetch_trackers():
    jobs = []
    for source, (url, fmt) in TRACKER_REPOS.items():
        try:
            res = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            res.raise_for_status()
            jobs += _TRACKER_PARSERS[fmt](res.text, source)
        except Exception as e:
            logging.warning("Tracker fetch failed for %s: %s", source, e)
    return jobs


# --- Workday campus/early-career boards (direct-tracked) ---
# Added 2026-09-14, same gap-fix session as speedyapply-ai above. Many
# companies run Workday with MULTIPLE "sites" on one tenant: a general board
# (often 50-100+ postings, mostly senior/experienced) and a separate, much
# smaller campus/early-career site aimed specifically at students and new
# grads. DraftKings is the first example found: its general "DraftKings" site
# had ~90 postings and did NOT include the new-grad Data Science Engineer
# posting the user found; a dedicated "campus_career_portal" site (7 postings
# total) did. That early-career site is the one worth direct-tracking here --
# far higher signal, and not dependent on a GitHub tracker having scraped it
# yet. Unlike ATS_BOARDS (single global endpoint per provider), each Workday
# tenant's shard number (wd1, wd5, ...) and site name are tenant-specific and
# not guessable -- find both from the company's public "early careers"/campus
# recruiting page (its Apply links reveal the host + site segment).
#
# company: (tenant, host, site). host includes the wdN shard.
WORKDAY_BOARDS = {
    "DraftKings": ("draftkings", "draftkings.wd1.myworkdayjobs.com", "campus_career_portal"),
}

_WORKDAY_RELATIVE_DAYS_RE = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def _workday_posted_to_date(text):
    """Convert Workday's relative 'Posted N Days Ago' / 'Posted Today' text to
    an ISO date. '30+ Days Ago' is treated as exactly 30 (a floor, not exact) --
    fine for our purposes since match_strength/ranking doesn't need precision
    past 'this is roughly a month-old-or-more posting'."""
    text = (text or "").strip()
    if not text:
        return ""
    if re.search(r"\btoday\b", text, re.IGNORECASE):
        return datetime.date.today().isoformat()
    m = _WORKDAY_RELATIVE_DAYS_RE.search(text)
    if not m:
        return ""
    days = int(m.group(1))
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def fetch_workday_boards():
    jobs = []
    for company, (tenant, host, site) in WORKDAY_BOARDS.items():
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        offset = 0
        try:
            while True:
                res = requests.post(
                    url,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
                    # A single space, not "", as searchText -- Workday's CXS API
                    # rejects an empty string with HTTP 400 but treats a blank
                    # space as "browse all" (verified live against DraftKings'
                    # tenant). limit must stay <=20 or the API 400s.
                    json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": " "},
                )
                res.raise_for_status()
                data = res.json()
                postings = data.get("jobPostings", [])
                for p in postings:
                    jobs.append({
                        "title": p.get("title", ""),
                        "company": company,
                        "location": p.get("locationsText", ""),
                        # Workday's public apply links carry an "en-US" locale
                        # segment before the site name that the CXS API response
                        # itself omits.
                        "url": f"https://{host}/en-US/{site}{p.get('externalPath', '')}",
                        "posted_date": _workday_posted_to_date(p.get("postedOn", "")),
                        "source": "workday",
                    })
                offset += len(postings)
                if not postings or offset >= data.get("total", 0):
                    break
        except Exception as e:
            logging.warning("Workday fetch failed for %s (%s/%s): %s", company, tenant, site, e)
    return jobs
