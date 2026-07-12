import datetime
from unittest.mock import MagicMock, patch

import job_sources
import digest


TODAY = datetime.date(2026, 7, 10)


def _job(**overrides):
    job = {
        "title": "Software Engineer, New Grad",
        "company": "Acme",
        "location": "Remote",
        "url": "https://acme.example.com/jobs/1",
        "source": "web",
        "posted_date": "2026-07-09",
        "match_score": 2,
        "status": "new",
    }
    job.update(overrides)
    return job


def _recruiter(**overrides):
    recruiter = {
        "name": "Jane Doe",
        "company": "Acme",
        "title": "Technical Recruiter",
        "email": "jane.doe@acme.example.com",
        "email_confidence": "pattern",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "source": "linkedin-direct",
        "status": "discovered",
        "email_draft": None,
    }
    recruiter.update(overrides)
    return recruiter


# ── score() ──────────────────────────────────────────────────────────────────

def test_score_target_company_bonus():
    target_company = next(iter(job_sources.ATS_BOARDS.keys()))
    in_target = _job(company=target_company, match_score=0, posted_date="", source="web")
    not_in_target = _job(company="Some Random Startup", match_score=0, posted_date="", source="web")
    assert digest.score(in_target, today=TODAY) - digest.score(not_in_target, today=TODAY) == 3


def test_score_includes_match_score_directly():
    low = _job(company="Some Random Startup", match_score=0, posted_date="", source="web")
    high = _job(company="Some Random Startup", match_score=3, posted_date="", source="web")
    assert digest.score(high, today=TODAY) - digest.score(low, today=TODAY) == 3


def test_score_handles_missing_match_score_as_zero():
    job = _job(company="Some Random Startup", posted_date="", source="web")
    del job["match_score"]
    assert digest.score(job, today=TODAY) == 0


def test_score_handles_none_match_score_as_zero():
    job = _job(company="Some Random Startup", posted_date="", source="web", match_score=None)
    assert digest.score(job, today=TODAY) == 0


def test_score_recency_bonus_within_3_days():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="2026-07-08")
    assert digest.score(job, today=TODAY) == 2


def test_score_recency_bonus_within_7_days():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="2026-07-04")
    assert digest.score(job, today=TODAY) == 1


def test_score_no_recency_bonus_past_7_days():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="2026-06-01")
    assert digest.score(job, today=TODAY) == 0


def test_score_no_recency_bonus_for_missing_date():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="")
    assert digest.score(job, today=TODAY) == 0


def test_score_no_recency_bonus_for_missing_date_key():
    job = _job(company="Some Random Startup", match_score=0, source="web")
    del job["posted_date"]
    assert digest.score(job, today=TODAY) == 0


def test_score_handles_malformed_date_without_crashing():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="not-a-date")
    assert digest.score(job, today=TODAY) == 0


def test_score_handles_none_date_without_crashing():
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date=None)
    assert digest.score(job, today=TODAY) == 0


def test_score_handles_future_date_without_bonus():
    # Bad/garbage future-dated posting shouldn't get a recency bonus.
    job = _job(company="Some Random Startup", match_score=0, source="web", posted_date="2026-12-25")
    assert digest.score(job, today=TODAY) == 0


def test_score_direct_ats_source_bonus():
    via_ats = _job(company="Some Random Startup", match_score=0, posted_date="", source="greenhouse")
    via_tracker = _job(company="Some Random Startup", match_score=0, posted_date="", source="simplify")
    assert digest.score(via_ats, today=TODAY) - digest.score(via_tracker, today=TODAY) == 1


def test_score_lever_and_ashby_also_get_ats_bonus():
    for src in ("lever", "ashby"):
        job = _job(company="Some Random Startup", match_score=0, posted_date="", source=src)
        assert digest.score(job, today=TODAY) == 1


def test_score_combines_all_bonuses():
    target_company = next(iter(job_sources.ATS_BOARDS.keys()))
    job = _job(company=target_company, match_score=2, posted_date="2026-07-10", source="greenhouse")
    # target(3) + match_score(2) + recency<=3d(2) + ats source(1) = 8
    assert digest.score(job, today=TODAY) == 8


# ── render_markdown() ────────────────────────────────────────────────────────

def test_render_markdown_orders_by_score_descending_not_input_order():
    # low-scoring job comes first in the input list; the higher scoring
    # job (target company + higher match_score) should render first.
    low = _job(title="Low Score Job", company="Some Random Startup", match_score=0, posted_date="", source="web")
    high = _job(
        title="High Score Job",
        company=next(iter(job_sources.ATS_BOARDS.keys())),
        match_score=3,
        posted_date="2026-07-10",
        source="greenhouse",
        url="https://acme.example.com/jobs/2",
    )
    out = digest.render_markdown([low, high], [], "2026-07-10", today=TODAY)

    assert out.index("High Score Job") < out.index("Low Score Job")


def test_render_markdown_includes_notes_section_when_notes_passed():
    out = digest.render_markdown([], [], "2026-07-10", notes=["LinkedIn throttled: checkpoint saved at co #4"])
    assert "## Notes" in out
    assert "LinkedIn throttled: checkpoint saved at co #4" in out


def test_render_markdown_omits_notes_section_when_no_notes():
    out = digest.render_markdown([], [], "2026-07-10")
    assert "## Notes" not in out


def test_render_markdown_includes_recruiters_section_grouped_by_company():
    r1 = _recruiter(name="Jane Doe", company="Acme")
    r2 = _recruiter(name="John Smith", company="Acme", title="University Recruiter")
    r3 = _recruiter(name="Ada Lovelace", company="Globex")
    out = digest.render_markdown([], [r1, r2, r3], "2026-07-10")

    assert "## Recruiters (3)" in out
    assert "### Acme" in out
    assert "### Globex" in out
    # Both Acme recruiters should appear after the Acme heading and before Globex's.
    acme_idx = out.index("### Acme")
    globex_idx = out.index("### Globex")
    assert acme_idx < out.index("Jane Doe") < globex_idx
    assert acme_idx < out.index("John Smith") < globex_idx
    assert globex_idx < out.index("Ada Lovelace")


def test_render_markdown_handles_no_jobs_or_recruiters():
    out = digest.render_markdown([], [], "2026-07-10")
    assert "No new jobs this run" in out
    assert "No new recruiters this run" in out


# ── send_email() ─────────────────────────────────────────────────────────────

def test_send_email_skips_when_gmail_app_password_unset(monkeypatch):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")

    with patch("digest.smtplib.SMTP_SSL") as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is False
    mock_smtp.assert_not_called()


def test_send_email_skip_path_prints_to_stderr(monkeypatch, capsys):
    # Finding 1: a skipped send (unconfigured) must surface on stdout/stderr,
    # not just via logging.warning (which career_agent.py routes to a file).
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")

    with patch("digest.smtplib.SMTP_SSL") as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is False
    mock_smtp.assert_not_called()
    err = capsys.readouterr().err
    assert "GMAIL_APP_PASSWORD" in err
    assert "skipping" in err.lower()


def test_send_email_smtp_failure_prints_to_stderr(monkeypatch, capsys):
    # Finding 1: an actual SMTP exception must also surface on stdout/stderr.
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")
    monkeypatch.setenv("USER_EMAIL", "me@example.com")

    with patch("digest.smtplib.SMTP_SSL", side_effect=OSError("network unreachable")):
        result = digest.send_email("subject", "body")

    assert result is False
    err = capsys.readouterr().err
    assert "send_email failed" in err
    assert "network unreachable" in err


def test_send_email_skips_when_user_email_unset(monkeypatch, capsys):
    # Finding 2: without USER_EMAIL, send_email must NOT fall back to using
    # the recipient's address as the SMTP login username -- it should skip
    # the send attempt entirely, just like the password/recipient-unset case.
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")
    monkeypatch.delenv("USER_EMAIL", raising=False)

    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server

    with patch("digest.smtplib.SMTP_SSL", return_value=mock_smtp_cm) as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is False
    mock_smtp.assert_not_called()
    mock_server.login.assert_not_called()

    err = capsys.readouterr().err
    assert "USER_EMAIL" in err
    assert "skipping" in err.lower()


def test_send_email_skips_when_digest_to_unset(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    monkeypatch.delenv("DIGEST_TO", raising=False)

    with patch("digest.smtplib.SMTP_SSL") as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is False
    mock_smtp.assert_not_called()


def test_send_email_skips_when_both_unset(monkeypatch):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    with patch("digest.smtplib.SMTP_SSL") as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is False
    mock_smtp.assert_not_called()


def test_send_email_sends_via_smtp_ssl_when_configured(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")
    monkeypatch.setenv("USER_EMAIL", "me@example.com")

    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server

    with patch("digest.smtplib.SMTP_SSL", return_value=mock_smtp_cm) as mock_smtp:
        result = digest.send_email("subject", "body")

    assert result is True
    mock_smtp.assert_called_once_with("smtp.gmail.com", 465)
    mock_server.login.assert_called_once()
    mock_server.sendmail.assert_called_once()


def test_send_email_returns_false_and_does_not_raise_on_smtp_error(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "fake-app-password")
    monkeypatch.setenv("DIGEST_TO", "someone@example.com")
    monkeypatch.setenv("USER_EMAIL", "me@example.com")

    with patch("digest.smtplib.SMTP_SSL", side_effect=OSError("network unreachable")):
        result = digest.send_email("subject", "body")

    assert result is False


# ── run_digest() ─────────────────────────────────────────────────────────────

def test_run_digest_flips_status_to_digested(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path / "digests")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    job = _job(url="https://acme.example.com/jobs/99")
    job_sources.insert_jobs([job], db_path=db)

    digest.run_digest([job], db_path=db)

    import sqlite3
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM jobs WHERE url = ?", (job["url"],)).fetchone()[0]
    con.close()
    assert status == "digested"


def test_run_digest_only_flips_digested_jobs_not_others(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path / "digests")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    job1 = _job(url="https://acme.example.com/jobs/1")
    job2 = _job(url="https://acme.example.com/jobs/2", title="Data Scientist, New Grad")
    job_sources.insert_jobs([job1, job2], db_path=db)

    digest.run_digest([job1], db_path=db)

    import sqlite3
    con = sqlite3.connect(db)
    status1 = con.execute("SELECT status FROM jobs WHERE url = ?", (job1["url"],)).fetchone()[0]
    status2 = con.execute("SELECT status FROM jobs WHERE url = ?", (job2["url"],)).fetchone()[0]
    con.close()
    assert status1 == "digested"
    assert status2 == "new"


def test_run_digest_writes_digest_file(tmp_path, monkeypatch):
    digest_dir = tmp_path / "digests"
    monkeypatch.setattr(digest, "DIGEST_DIR", digest_dir)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    job = _job(url="https://acme.example.com/jobs/100")
    job_sources.insert_jobs([job], db_path=db)

    path = digest.run_digest([job], db_path=db)

    assert path.exists()
    assert path.parent == digest_dir
    assert "Software Engineer, New Grad" in path.read_text()


def test_run_digest_prints_top_10_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path / "digests")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    job = _job(url="https://acme.example.com/jobs/101")
    job_sources.insert_jobs([job], db_path=db)

    digest.run_digest([job], db_path=db)

    out = capsys.readouterr().out
    assert "Job Digest" in out
    assert "Software Engineer, New Grad" in out


def test_run_digest_never_calls_smtp_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path / "digests")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    job = _job(url="https://acme.example.com/jobs/102")
    job_sources.insert_jobs([job], db_path=db)

    with patch("digest.smtplib.SMTP_SSL") as mock_smtp:
        digest.run_digest([job], db_path=db)

    mock_smtp.assert_not_called()


def test_run_digest_handles_no_new_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_DIR", tmp_path / "digests")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DIGEST_TO", raising=False)

    db = tmp_path / "test.db"
    path = digest.run_digest([], db_path=db)

    assert path.exists()
