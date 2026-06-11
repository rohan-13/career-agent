import sqlite3

import job_sources


JOB = {
    "title": "Software Engineer, New Grad",
    "company": "Stripe",
    "location": "San Francisco",
    "url": "https://stripe.com/jobs/listing/123",
    "source": "greenhouse",
    "posted_date": "2026-06-08",
    "match_score": 3,
}


def test_insert_returns_new_jobs(tmp_path):
    db = tmp_path / "test.db"
    new = job_sources.insert_jobs([JOB], db_path=db)
    assert len(new) == 1


def test_same_url_not_reinserted(tmp_path):
    db = tmp_path / "test.db"
    job_sources.insert_jobs([JOB], db_path=db)
    new = job_sources.insert_jobs([JOB], db_path=db)
    assert new == []


def test_fuzzy_title_duplicate_skipped(tmp_path):
    db = tmp_path / "test.db"
    job_sources.insert_jobs([JOB], db_path=db)
    near_dup = dict(JOB, url="https://simplify.jobs/p/abc", title="New Grad Software Engineer")
    new = job_sources.insert_jobs([near_dup], db_path=db)
    assert new == []


def test_different_role_same_company_inserted(tmp_path):
    db = tmp_path / "test.db"
    job_sources.insert_jobs([JOB], db_path=db)
    other = dict(JOB, url="https://stripe.com/jobs/listing/456", title="Data Scientist, New Grad")
    new = job_sources.insert_jobs([other], db_path=db)
    assert len(new) == 1


def test_status_defaults_to_new(tmp_path):
    db = tmp_path / "test.db"
    job_sources.insert_jobs([JOB], db_path=db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT status FROM jobs").fetchone()[0] == "new"
