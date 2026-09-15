import datetime

import job_sources


def test_workday_posted_to_date_days_ago():
    today = datetime.date.today()
    assert job_sources._workday_posted_to_date("Posted 6 Days Ago") == (today - datetime.timedelta(days=6)).isoformat()


def test_workday_posted_to_date_today():
    today = datetime.date.today()
    assert job_sources._workday_posted_to_date("Posted Today") == today.isoformat()


def test_workday_posted_to_date_plus_form():
    today = datetime.date.today()
    assert job_sources._workday_posted_to_date("Posted 30+ Days Ago") == (today - datetime.timedelta(days=30)).isoformat()


def test_workday_posted_to_date_unrecognized_returns_empty():
    assert job_sources._workday_posted_to_date("") == ""
    assert job_sources._workday_posted_to_date("Some other text") == ""


def test_fetch_workday_boards_paginates_and_builds_urls(monkeypatch):
    monkeypatch.setattr(job_sources, "WORKDAY_BOARDS", {
        "DraftKings": ("draftkings", "draftkings.wd1.myworkdayjobs.com", "campus_career_portal"),
    })

    pages = [
        {
            "total": 3,
            "jobPostings": [
                {
                    "title": "Data Science Engineer (December 2026 and May 2027 Grads)",
                    "externalPath": "/job/Boston-MA/Data-Science-Engineer_JR14959",
                    "locationsText": "Boston, MA",
                    "postedOn": "Posted 6 Days Ago",
                },
                {
                    "title": "Software Engineer Intern (Summer 2027)",
                    "externalPath": "/job/Boston-MA/Software-Engineer-Intern_JR14929",
                    "locationsText": "Boston, MA",
                    "postedOn": "Posted 14 Days Ago",
                },
            ],
        },
        {
            "total": 3,
            "jobPostings": [
                {
                    "title": "Analyst Intern (Summer 2027)",
                    "externalPath": "/job/Boston-MA/Analyst-Intern_JR14927",
                    "locationsText": "Boston, MA",
                    "postedOn": "Posted Today",
                },
            ],
        },
    ]

    calls = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_post(url, timeout=None, headers=None, json=None):
        calls.append((url, json["offset"], json["limit"], json["searchText"]))
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(job_sources.requests, "post", fake_post)

    jobs = job_sources.fetch_workday_boards()

    assert len(calls) == 2  # stopped once offset (2, then 3) reached total=3
    assert all(c[3] == " " for c in calls)  # searchText is a space, not ""
    assert all(c[2] <= 20 for c in calls)   # limit never exceeds Workday's cap

    assert len(jobs) == 3
    assert jobs[0]["company"] == "DraftKings"
    assert jobs[0]["title"] == "Data Science Engineer (December 2026 and May 2027 Grads)"
    assert jobs[0]["url"] == (
        "https://draftkings.wd1.myworkdayjobs.com/en-US/campus_career_portal"
        "/job/Boston-MA/Data-Science-Engineer_JR14959"
    )
    assert jobs[0]["source"] == "workday"
    today = datetime.date.today()
    assert jobs[0]["posted_date"] == (today - datetime.timedelta(days=6)).isoformat()
    assert jobs[2]["posted_date"] == today.isoformat()
