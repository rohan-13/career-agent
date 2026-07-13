import sqlite3

import pytest

import recruiter_finder


# ── title keyword matching ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title",
    [
        "Technical Recruiter",
        "University Recruiting Lead",
        "Talent Acquisition Partner",
        "Campus Recruiting Coordinator",
        "Early Career Programs Manager",
        "New Grad Hiring Manager",
        "Software Engineering Hiring Manager",
    ],
)
def test_is_recruiter_matches_known_titles(title):
    assert recruiter_finder._is_recruiter(title) is True


@pytest.mark.parametrize(
    "title",
    ["Software Engineer", "Product Manager", "Data Scientist", "", None],
)
def test_is_recruiter_rejects_non_recruiter_titles(title):
    assert recruiter_finder._is_recruiter(title) is False


# ── email pattern generation ────────────────────────────────────────────────

def test_generate_email_prefers_hunter_pattern_over_domain_pattern():
    # google.com has a known domain pattern of {first}.{last}@{domain};
    # a differing Hunter pattern must win.
    email, conf = recruiter_finder.generate_email(
        "Jane Doe", "google.com", hunter_pattern="{first}@{domain}"
    )
    assert email == "jane@google.com"
    assert conf == "hunter-pattern"


def test_generate_email_uses_domain_pattern_when_no_hunter_pattern():
    email, conf = recruiter_finder.generate_email("Jane Doe", "google.com")
    assert email == "jane.doe@google.com"
    assert conf == "pattern"


def test_generate_email_falls_back_to_generic_guess():
    email, conf = recruiter_finder.generate_email("Jane Doe", "unknown-co.com")
    assert email == "jane.doe@unknown-co.com"
    assert conf == "guessed"


def test_generate_email_single_word_name_returns_none_none():
    assert recruiter_finder.generate_email("Cher", "google.com") == (None, None)


# ── DB dedup ─────────────────────────────────────────────────────────────────

def test_init_db_dedupes_on_company_and_name(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    con = recruiter_finder.init_db()
    con.execute(
        """INSERT OR IGNORE INTO recruiters (name, company, title, email, email_confidence, linkedin_url, source)
           VALUES (?,?,?,?,?,?,?)""",
        ("Jane Doe", "Google", "Technical Recruiter", "jane.doe@google.com", "pattern", "https://linkedin.com/in/janedoe", "linkedin-direct"),
    )
    con.execute(
        """INSERT OR IGNORE INTO recruiters (name, company, title, email, email_confidence, linkedin_url, source)
           VALUES (?,?,?,?,?,?,?)""",
        ("Jane Doe", "Google", "Technical Recruiter", "jane.doe@google.com", "pattern", "https://linkedin.com/in/janedoe", "linkedin-direct"),
    )
    con.commit()

    count = con.execute(
        "SELECT COUNT(*) FROM recruiters WHERE company = ? AND name = ?", ("Google", "Jane Doe")
    ).fetchone()[0]
    con.close()
    assert count == 1


def test_init_db_allows_same_name_different_company(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)

    con = recruiter_finder.init_db()
    for company in ("Google", "Apple"):
        con.execute(
            """INSERT OR IGNORE INTO recruiters (name, company, title, email, email_confidence, linkedin_url, source)
               VALUES (?,?,?,?,?,?,?)""",
            ("Jane Doe", company, "Technical Recruiter", "jane.doe@example.com", "pattern", "https://linkedin.com/in/janedoe", "linkedin-direct"),
        )
    con.commit()

    count = con.execute("SELECT COUNT(*) FROM recruiters WHERE name = ?", ("Jane Doe",)).fetchone()[0]
    con.close()
    assert count == 2


# ── scrape_company_people ───────────────────────────────────────────────────

def test_scrape_company_people_filters_to_recruiter_titles(monkeypatch):
    canned = [
        {"name": "Jane Doe", "title": "Technical Recruiter", "url": "https://linkedin.com/in/janedoe"},
        {"name": "John Smith", "title": "Software Engineer", "url": "https://linkedin.com/in/johnsmith"},
    ]

    async def fake_playwright_people(slug, search_terms, max_results, interactive=True):
        return canned

    monkeypatch.setattr(recruiter_finder, "_playwright_people", fake_playwright_people)

    result = recruiter_finder.scrape_company_people("google", max_results=15)
    assert result == [canned[0]]


def test_scrape_company_people_falls_back_to_all_when_no_recruiter_titles(monkeypatch):
    canned = [
        {"name": "John Smith", "title": "Software Engineer", "url": "https://linkedin.com/in/johnsmith"},
    ]

    async def fake_playwright_people(slug, search_terms, max_results, interactive=True):
        return canned

    monkeypatch.setattr(recruiter_finder, "_playwright_people", fake_playwright_people)

    result = recruiter_finder.scrape_company_people("google", max_results=15)
    assert result == canned


def test_scrape_company_people_returns_empty_on_playwright_error(monkeypatch):
    async def raising_playwright_people(slug, search_terms, max_results, interactive=True):
        raise RuntimeError("boom")

    monkeypatch.setattr(recruiter_finder, "_playwright_people", raising_playwright_people)

    result = recruiter_finder.scrape_company_people("google", max_results=15)
    assert result == []


# ── discover_recruiters ──────────────────────────────────────────────────────

def test_discover_recruiters_inserts_new_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)

    canned = [{"name": "Jane Doe", "title": "Technical Recruiter", "url": "https://linkedin.com/in/janedoe"}]

    def fake_scrape_company_people(slug, max_results=10, interactive=True):
        return canned

    monkeypatch.setattr(recruiter_finder, "scrape_company_people", fake_scrape_company_people)
    monkeypatch.setattr(recruiter_finder.time, "sleep", lambda *_: None)

    companies = [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]
    total_new = recruiter_finder.discover_recruiters(companies=companies, max_per_company=10)

    assert total_new == 1
    con = sqlite3.connect(db_path)
    row = con.execute("SELECT name, company, email FROM recruiters").fetchone()
    con.close()
    assert row == ("Jane Doe", "Google", "jane.doe@google.com")


def test_discover_recruiters_does_not_duplicate_on_rerun(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)

    canned = [{"name": "Jane Doe", "title": "Technical Recruiter", "url": "https://linkedin.com/in/janedoe"}]
    monkeypatch.setattr(recruiter_finder, "scrape_company_people", lambda slug, max_results=10, interactive=True: canned)
    monkeypatch.setattr(recruiter_finder.time, "sleep", lambda *_: None)

    companies = [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]
    recruiter_finder.discover_recruiters(companies=companies, max_per_company=10)
    total_new_second_run = recruiter_finder.discover_recruiters(companies=companies, max_per_company=10)

    assert total_new_second_run == 0
    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM recruiters").fetchone()[0]
    con.close()
    assert count == 1


def test_discover_recruiters_uses_hunter_email_when_api_key_present(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)
    monkeypatch.setenv("HUNTER_API_KEY", "fake-key")

    canned = [{"name": "Jane Doe", "title": "Technical Recruiter", "url": "https://linkedin.com/in/janedoe"}]
    monkeypatch.setattr(recruiter_finder, "scrape_company_people", lambda slug, max_results=10, interactive=True: canned)
    monkeypatch.setattr(recruiter_finder, "hunter_domain_pattern", lambda domain, api_key: None)
    monkeypatch.setattr(recruiter_finder, "hunter_find_email", lambda first, last, domain, api_key: ("jane.doe@hunter-verified.com", "95"))
    monkeypatch.setattr(recruiter_finder.time, "sleep", lambda *_: None)

    companies = [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]
    recruiter_finder.discover_recruiters(companies=companies, max_per_company=10)

    con = sqlite3.connect(db_path)
    email, conf = con.execute("SELECT email, email_confidence FROM recruiters").fetchone()
    con.close()
    assert email == "jane.doe@hunter-verified.com"
    assert conf == "95"


def test_discover_recruiters_defaults_interactive_true_but_threads_false_when_passed(tmp_path, monkeypatch):
    """The manual `--recruiter` CLI path calls discover_recruiters() without an
    `interactive` kwarg and must keep behaving as an interactive (human-present)
    run by default. The automated career_agent path explicitly passes
    interactive=False -- confirm discover_recruiters() threads whatever it's
    given straight through to scrape_company_people()."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(recruiter_finder, "DB_PATH", db_path)
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)

    captured = []

    def fake_scrape_company_people(slug, max_results=10, interactive=True):
        captured.append(interactive)
        return []

    monkeypatch.setattr(recruiter_finder, "scrape_company_people", fake_scrape_company_people)
    monkeypatch.setattr(recruiter_finder.time, "sleep", lambda *_: None)

    companies = [{"name": "Google", "domain": "google.com", "linkedin_slug": "google"}]

    # Manual-CLI-style call: no interactive kwarg passed -> defaults to True.
    recruiter_finder.discover_recruiters(companies=companies, max_per_company=10)
    assert captured[-1] is True

    # Automated career_agent-style call: explicit interactive=False must be threaded through.
    recruiter_finder.discover_recruiters(companies=companies, max_per_company=10, interactive=False)
    assert captured[-1] is False
