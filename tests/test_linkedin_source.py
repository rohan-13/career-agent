import datetime

import linkedin_source


# ── job_search_url ──────────────────────────────────────────────────────────

def test_job_search_url_encodes_keywords():
    url = linkedin_source.job_search_url("software engineer new grad")
    assert "keywords=software%20engineer%20new%20grad" in url


def test_job_search_url_filters_entry_level():
    url = linkedin_source.job_search_url("data scientist")
    assert "f_E=2" in url


def test_job_search_url_filters_recent_postings():
    url = linkedin_source.job_search_url("data scientist")
    assert "f_TPR=r604800" in url


def test_job_search_url_defaults_start_to_zero():
    url = linkedin_source.job_search_url("data scientist")
    assert "start=0" in url


def test_job_search_url_uses_given_start_for_pagination():
    url = linkedin_source.job_search_url("data scientist", start=25)
    assert "start=25" in url
    assert "start=0" not in url


def test_job_search_url_escapes_special_characters():
    url = linkedin_source.job_search_url("C++ engineer")
    assert "keywords=C%2B%2B%20engineer" in url


def test_job_search_url_is_https_linkedin_jobs_search():
    url = linkedin_source.job_search_url("data engineer")
    assert url.startswith("https://www.linkedin.com/jobs/search/")


# ── allowed_to_run ───────────────────────────────────────────────────────────

def test_allowed_to_run_true_when_no_last_run_file(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", tmp_path / ".linkedin_last_run")
    assert linkedin_source.allowed_to_run() is True


def test_allowed_to_run_false_within_throttle_window(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)

    now = datetime.datetime(2026, 7, 12, 12, 0, tzinfo=datetime.timezone.utc)
    one_hour_ago = now - datetime.timedelta(hours=1)
    last_run_path.write_text(one_hour_ago.isoformat())

    assert linkedin_source.allowed_to_run(now=now) is False


def test_allowed_to_run_true_after_throttle_window_passes(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)

    now = datetime.datetime(2026, 7, 12, 12, 0, tzinfo=datetime.timezone.utc)
    thirteen_hours_ago = now - datetime.timedelta(hours=13)
    last_run_path.write_text(thirteen_hours_ago.isoformat())

    assert linkedin_source.allowed_to_run(now=now) is True


def test_allowed_to_run_true_at_exact_twelve_hour_boundary(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)

    now = datetime.datetime(2026, 7, 12, 12, 0, tzinfo=datetime.timezone.utc)
    exactly_twelve_hours_ago = now - datetime.timedelta(hours=12)
    last_run_path.write_text(exactly_twelve_hours_ago.isoformat())

    assert linkedin_source.allowed_to_run(now=now) is True


def test_allowed_to_run_false_just_under_twelve_hours(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)

    now = datetime.datetime(2026, 7, 12, 12, 0, tzinfo=datetime.timezone.utc)
    just_under_twelve_hours_ago = now - datetime.timedelta(hours=11, minutes=59)
    last_run_path.write_text(just_under_twelve_hours_ago.isoformat())

    assert linkedin_source.allowed_to_run(now=now) is False


def test_allowed_to_run_true_when_file_content_is_garbage(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)
    last_run_path.write_text("not-a-timestamp")

    assert linkedin_source.allowed_to_run() is True


def test_record_run_writes_a_timestamp_allowed_to_run_can_read(tmp_path, monkeypatch):
    last_run_path = tmp_path / ".linkedin_last_run"
    monkeypatch.setattr(linkedin_source, "LAST_RUN_PATH", last_run_path)

    now = datetime.datetime(2026, 7, 12, 12, 0, tzinfo=datetime.timezone.utc)
    linkedin_source._record_run(now=now)

    assert last_run_path.exists()
    assert linkedin_source.allowed_to_run(now=now) is False
    assert linkedin_source.allowed_to_run(now=now + datetime.timedelta(hours=13)) is True
