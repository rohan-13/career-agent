import datetime
import sqlite3

import pytest

import career_agent
import job_sources
import recruiter_finder

# Save the real, un-monkeypatched insert_jobs before any test replaces
# career_agent.job_sources.insert_jobs (career_agent.job_sources IS the
# job_sources module object -- patching one patches the other).
_REAL_INSERT_JOBS = job_sources.insert_jobs


# ── helpers ──────────────────────────────────────────────────────────────────

def _job(**overrides):
    job = {
        "title": "Software Engineer, New Grad",
        "company": "Acme",
        "location": "Remote",
        "url": "https://acme.example.com/jobs/1",
        "source": "web",
        "posted_date": "2026-07-09",
    }
    job.update(overrides)
    return job


def _insert_recruiter_row(db_path, company, name="Jane Doe", first_seen=None):
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS recruiters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, company TEXT, title TEXT, email TEXT,
            email_confidence TEXT, linkedin_url TEXT, source TEXT,
            status TEXT DEFAULT 'discovered', email_draft TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, name)
        )"""
    )
    if first_seen is not None:
        con.execute(
            "INSERT INTO recruiters (name, company, title, email, email_confidence, linkedin_url, source, first_seen)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (name, company, "Technical Recruiter", f"{name.lower().replace(' ', '.')}@acme.com",
             "pattern", "https://linkedin.com/in/janedoe", "linkedin-direct", first_seen),
        )
    else:
        con.execute(
            "INSERT INTO recruiters (name, company, title, email, email_confidence, linkedin_url, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (name, company, "Technical Recruiter", f"{name.lower().replace(' ', '.')}@acme.com",
             "pattern", "https://linkedin.com/in/janedoe", "linkedin-direct"),
        )
    con.commit()
    con.close()


def _insert_check_row(db_path, company, last_attempted):
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS recruiter_checks (
            company TEXT PRIMARY KEY,
            last_attempted TEXT
        )"""
    )
    con.execute(
        "INSERT OR REPLACE INTO recruiter_checks (company, last_attempted) VALUES (?, ?)",
        (company, last_attempted),
    )
    con.commit()
    con.close()


def _iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── run_jobs_pipeline: filtering + match_score stamping ─────────────────────

def test_run_jobs_pipeline_filters_non_target_and_keeps_target(monkeypatch, tmp_path):
    target = _job(title="Software Engineer, New Grad", url="https://acme.example.com/jobs/1")
    non_target = _job(title="Senior Software Engineer", url="https://acme.example.com/jobs/2", company="Beta")

    monkeypatch.setattr(career_agent.job_sources, "fetch_ats_boards", lambda: [target, non_target])
    monkeypatch.setattr(career_agent.job_sources, "fetch_trackers", lambda: [])
    monkeypatch.setattr(career_agent.linkedin_source, "fetch_linkedin", lambda: ([], "ok"))

    # Bind insert_jobs to a tmp DB so this test never touches the real events.db.
    def fake_insert_jobs(jobs, db_path=None):
        return _REAL_INSERT_JOBS(jobs, db_path=tmp_path / "events.db")

    monkeypatch.setattr(career_agent.job_sources, "insert_jobs", fake_insert_jobs)
    monkeypatch.setattr(career_agent, "_maybe_discover_recruiters", lambda company: [])
    monkeypatch.setattr(career_agent.digest, "run_digest", lambda *a, **k: None)

    new_jobs, recruiters = career_agent.run_jobs_pipeline()

    titles = [j["title"] for j in new_jobs]
    assert "Software Engineer, New Grad" in titles
    assert "Senior Software Engineer" not in titles
    assert recruiters == []


def test_run_jobs_pipeline_stamps_match_score(monkeypatch, tmp_path):
    target = _job(title="Software Engineer, New Grad", url="https://acme.example.com/jobs/3")

    monkeypatch.setattr(career_agent.job_sources, "fetch_ats_boards", lambda: [target])
    monkeypatch.setattr(career_agent.job_sources, "fetch_trackers", lambda: [])
    monkeypatch.setattr(career_agent.linkedin_source, "fetch_linkedin", lambda: ([], "ok"))

    def fake_insert_jobs(jobs, db_path=None):
        return _REAL_INSERT_JOBS(jobs, db_path=tmp_path / "events.db")

    monkeypatch.setattr(career_agent.job_sources, "insert_jobs", fake_insert_jobs)
    monkeypatch.setattr(career_agent, "_maybe_discover_recruiters", lambda company: [])
    monkeypatch.setattr(career_agent.digest, "run_digest", lambda *a, **k: None)

    new_jobs, _ = career_agent.run_jobs_pipeline()

    assert len(new_jobs) == 1
    assert new_jobs[0]["match_score"] == 3  # "new grad" in title -> strength 3


# ── run_jobs_pipeline: LinkedIn status notes surfaced to digest ────────────

def test_run_jobs_pipeline_surfaces_linkedin_status_note(monkeypatch, tmp_path):
    monkeypatch.setattr(career_agent.job_sources, "fetch_ats_boards", lambda: [])
    monkeypatch.setattr(career_agent.job_sources, "fetch_trackers", lambda: [])
    monkeypatch.setattr(career_agent.linkedin_source, "fetch_linkedin", lambda: ([], "throttled"))

    def fake_insert_jobs(jobs, db_path=None):
        return _REAL_INSERT_JOBS(jobs, db_path=tmp_path / "events.db")

    monkeypatch.setattr(career_agent.job_sources, "insert_jobs", fake_insert_jobs)
    monkeypatch.setattr(career_agent, "_maybe_discover_recruiters", lambda company: [])

    captured = {}

    def fake_run_digest(new_jobs, new_recruiters=(), notes=(), db_path=None):
        captured["notes"] = list(notes)

    monkeypatch.setattr(career_agent.digest, "run_digest", fake_run_digest)

    career_agent.run_jobs_pipeline()

    assert captured["notes"] == ["LinkedIn: throttled"]


@pytest.mark.parametrize(
    "status,expected_note",
    [
        ("no-session", "LinkedIn: no session"),
        ("throttled", "LinkedIn: throttled"),
        ("checkpoint", "LinkedIn: checkpoint hit, aborted"),
        ("error", "LinkedIn: error"),
    ],
)
def test_run_jobs_pipeline_note_per_status(monkeypatch, tmp_path, status, expected_note):
    monkeypatch.setattr(career_agent.job_sources, "fetch_ats_boards", lambda: [])
    monkeypatch.setattr(career_agent.job_sources, "fetch_trackers", lambda: [])
    monkeypatch.setattr(career_agent.linkedin_source, "fetch_linkedin", lambda: ([], status))

    def fake_insert_jobs(jobs, db_path=None):
        return _REAL_INSERT_JOBS(jobs, db_path=tmp_path / "events.db")

    monkeypatch.setattr(career_agent.job_sources, "insert_jobs", fake_insert_jobs)
    monkeypatch.setattr(career_agent, "_maybe_discover_recruiters", lambda company: [])

    captured = {}
    monkeypatch.setattr(
        career_agent.digest, "run_digest",
        lambda new_jobs, new_recruiters=(), notes=(), db_path=None: captured.__setitem__("notes", list(notes)),
    )

    career_agent.run_jobs_pipeline()
    assert captured["notes"] == [expected_note]


# ── run_jobs_pipeline: exception isolation across companies ────────────────

def test_run_jobs_pipeline_isolates_per_company_recruiter_discovery_failure(monkeypatch, tmp_path):
    """One company's _maybe_discover_recruiters raising must not abort the loop
    early or prevent digest.run_digest from running -- mirrors the try/except
    isolation already used around fetch_ats_boards()/fetch_trackers()."""
    good_a = _job(title="Software Engineer, New Grad", url="https://a.example.com/jobs/1", company="Alpha")
    bad = _job(title="Software Engineer, New Grad", url="https://b.example.com/jobs/1", company="Beta")
    good_c = _job(title="Software Engineer, New Grad", url="https://c.example.com/jobs/1", company="Gamma")

    monkeypatch.setattr(career_agent.job_sources, "fetch_ats_boards", lambda: [good_a, bad, good_c])
    monkeypatch.setattr(career_agent.job_sources, "fetch_trackers", lambda: [])
    monkeypatch.setattr(career_agent.linkedin_source, "fetch_linkedin", lambda: ([], "ok"))

    def fake_insert_jobs(jobs, db_path=None):
        return _REAL_INSERT_JOBS(jobs, db_path=tmp_path / "events.db")

    monkeypatch.setattr(career_agent.job_sources, "insert_jobs", fake_insert_jobs)

    def fake_maybe_discover(company):
        if company == "Beta":
            raise RuntimeError("boom: LinkedIn blew up for Beta")
        return [{"name": f"Recruiter at {company}", "company": company, "title": "Technical Recruiter",
                  "email": None, "email_confidence": None, "linkedin_url": None}]

    monkeypatch.setattr(career_agent, "_maybe_discover_recruiters", fake_maybe_discover)

    captured = {}

    def fake_run_digest(new_jobs, new_recruiters=(), notes=(), db_path=None):
        captured["called"] = True
        captured["new_jobs"] = list(new_jobs)
        captured["recruiters"] = list(new_recruiters)

    monkeypatch.setattr(career_agent.digest, "run_digest", fake_run_digest)

    new_jobs, recruiters = career_agent.run_jobs_pipeline()

    # digest.run_digest must still run despite Beta's exception.
    assert captured.get("called") is True
    # Alpha and Gamma's recruiters were still collected; Beta's failure just skipped Beta.
    names = {r["name"] for r in recruiters}
    assert names == {"Recruiter at Alpha", "Recruiter at Gamma"}
    # All three companies' jobs were still inserted/returned.
    companies = {j["company"] for j in new_jobs}
    assert companies == {"Alpha", "Beta", "Gamma"}


# ── _maybe_discover_recruiters ──────────────────────────────────────────────

def test_maybe_discover_recruiters_skips_when_fresh_row_exists(monkeypatch, tmp_path):
    # Freshness is tracked in `recruiter_checks` (last ATTEMPT), not in
    # `recruiters.first_seen` -- see the TTL bug fix: discover_recruiters()
    # uses INSERT OR IGNORE, so a stable roster never refreshes first_seen on
    # repeat scrapes. A fresh `recruiter_checks` row must skip on its own.
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    fresh_ts = _iso(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
    _insert_check_row(db_path, "Google", fresh_ts)

    def raise_if_called(*args, **kwargs):
        raise AssertionError("discover_recruiters should not be called when a fresh check exists")

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", raise_if_called)

    result = career_agent._maybe_discover_recruiters("Google")
    assert result == []


def test_maybe_discover_recruiters_triggers_when_no_existing_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    def fake_discover_recruiters(companies=None, max_per_company=10, interactive=True):
        assert companies == [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]
        # Simulate discover_recruiters' real side effect: it upserts rows itself.
        _insert_recruiter_row(db_path, "Google", name="Jane Doe")
        _insert_recruiter_row(db_path, "Google", name="John Smith")
        return 2

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", fake_discover_recruiters)

    result = career_agent._maybe_discover_recruiters("Google")

    assert len(result) == 2
    names = {r["name"] for r in result}
    assert names == {"Jane Doe", "John Smith"}
    for r in result:
        assert set(r.keys()) == {"name", "company", "title", "email", "email_confidence", "linkedin_url"}
        assert r["company"] == "Google"


def test_maybe_discover_recruiters_calls_discover_recruiters_with_interactive_false(monkeypatch, tmp_path):
    """The automated path must never risk blocking on input() in an unattended
    cron run -- discover_recruiters() must be called with interactive=False."""
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    captured_kwargs = {}

    def fake_discover_recruiters(companies=None, max_per_company=10, interactive=True):
        captured_kwargs["companies"] = companies
        captured_kwargs["max_per_company"] = max_per_company
        captured_kwargs["interactive"] = interactive
        return 0

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", fake_discover_recruiters)

    career_agent._maybe_discover_recruiters("Google")

    assert captured_kwargs["companies"] == [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]
    assert captured_kwargs["max_per_company"] == 10
    assert captured_kwargs["interactive"] is False


def test_maybe_discover_recruiters_triggers_when_only_stale_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    stale_ts = _iso(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40))
    _insert_recruiter_row(db_path, "Google", name="Old Recruiter", first_seen=stale_ts)
    _insert_check_row(db_path, "Google", stale_ts)

    def fake_discover_recruiters(companies=None, max_per_company=10, interactive=True):
        _insert_recruiter_row(db_path, "Google", name="New Recruiter")
        return 1

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", fake_discover_recruiters)

    result = career_agent._maybe_discover_recruiters("Google")

    assert len(result) == 1
    assert result[0]["name"] == "New Recruiter"


def test_maybe_discover_recruiters_skips_company_not_in_target_companies(monkeypatch, tmp_path):
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    def raise_if_called(*args, **kwargs):
        raise AssertionError("discover_recruiters should not be called for a company not in TARGET_COMPANIES")

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", raise_if_called)

    result = career_agent._maybe_discover_recruiters("Some Random Startup")
    assert result == []


def test_maybe_discover_recruiters_returns_empty_when_discover_finds_nothing_new(monkeypatch, tmp_path):
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", lambda companies=None, max_per_company=10, interactive=True: 0)

    result = career_agent._maybe_discover_recruiters("Google")
    assert result == []


def test_maybe_discover_recruiters_stable_roster_stays_throttled_after_zero_new(monkeypatch, tmp_path):
    """Reproduces the critical TTL bug directly.

    discover_recruiters() uses INSERT OR IGNORE against a UNIQUE(company,
    name) constraint, so a company with a stable recruiting roster (no
    turnover) will find the SAME recruiters on every scrape and return 0 new
    rows every time -- `recruiters.first_seen` never gets touched on repeat
    finds. Before the fix, that meant the 30-day guard (keyed on
    `recruiters.first_seen`) could never "see" that a check had just
    happened, so every subsequent new job posting at that company would
    re-trigger a live LinkedIn scrape.

    This test simulates exactly that: call #1 finds 0 new recruiters (stable
    roster, already fully discovered) and must still mark the company as
    checked. Call #2, made immediately after (well within the 30-day TTL),
    must skip WITHOUT calling discover_recruiters again -- proven by an
    assertion-raising mock, not just an empty-list return value.
    """
    db_path = tmp_path / "events.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    calls = {"n": 0}

    def fake_discover_recruiters(companies=None, max_per_company=10, interactive=True):
        calls["n"] += 1
        return 0  # stable roster: nothing new found, but a check DID happen

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", fake_discover_recruiters)

    first_result = career_agent._maybe_discover_recruiters("Google")
    assert first_result == []
    assert calls["n"] == 1

    def raise_if_called(*args, **kwargs):
        raise AssertionError(
            "discover_recruiters should not be called again: this company was "
            "checked less than RECRUITER_DISCOVERY_TTL_DAYS ago, even though "
            "that check found zero new recruiters"
        )

    monkeypatch.setattr(recruiter_finder, "discover_recruiters", raise_if_called)

    second_result = career_agent._maybe_discover_recruiters("Google")
    assert second_result == []
