import sqlite3

import outreach


def _make_db(db_path):
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE recruiters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            company TEXT,
            title TEXT,
            email TEXT,
            email_confidence TEXT,
            linkedin_url TEXT,
            source TEXT,
            status TEXT DEFAULT 'discovered',
            email_draft TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute(
        """INSERT INTO recruiters (name, company, title, email, linkedin_url, status)
           VALUES (?,?,?,?,?,?)""",
        ("Jane Doe", "Google", "Technical Recruiter", "jane.doe@google.com", "https://linkedin.com/in/janedoe", "discovered"),
    )
    con.commit()
    con.close()


def test_get_recruiter_returns_row(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _make_db(db_path)
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    row = outreach._get_recruiter(1)
    assert row is not None
    assert row[1] == "Jane Doe"
    assert row[2] == "Google"
    assert row[5] == "https://linkedin.com/in/janedoe"


def test_get_recruiter_returns_none_for_missing_id(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _make_db(db_path)
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    assert outreach._get_recruiter(999) is None


def test_save_draft_updates_draft_and_status(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _make_db(db_path)
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    outreach.save_draft(1, "Hi Jane, ...")

    row = outreach._get_recruiter(1)
    assert row[6] == "draft_ready"
    assert row[7] == "Hi Jane, ..."


def test_list_recruiters_prints_no_recruiters_message_when_empty(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "test.db"
    _make_db(db_path)
    # empty out the table
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM recruiters")
    con.commit()
    con.close()
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    outreach.list_recruiters()

    captured = capsys.readouterr()
    assert "No recruiters in events.db yet" in captured.out


def test_list_recruiters_prints_rows(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "test.db"
    _make_db(db_path)
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    outreach.list_recruiters()

    captured = capsys.readouterr()
    assert "Jane Doe" in captured.out
    assert "Google" in captured.out


def test_list_recruiters_handles_missing_table(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "test.db"
    # no table created at all -> sqlite3.OperationalError path
    monkeypatch.setattr(outreach, "DB_PATH", db_path)

    outreach.list_recruiters()

    captured = capsys.readouterr()
    assert "No recruiters in events.db yet" in captured.out
