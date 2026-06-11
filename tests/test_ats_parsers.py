import job_sources


def test_parse_greenhouse():
    data = {"jobs": [{
        "title": "Software Engineer, New Grad",
        "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
        "location": {"name": "SF, NYC, or Remote"},
        "updated_at": "2026-06-08T10:00:00-04:00",
    }]}
    jobs = job_sources.parse_greenhouse(data, "Stripe")
    assert jobs == [{
        "title": "Software Engineer, New Grad",
        "company": "Stripe",
        "location": "SF, NYC, or Remote",
        "url": "https://boards.greenhouse.io/stripe/jobs/123",
        "posted_date": "2026-06-08",
        "source": "greenhouse",
    }]


def test_parse_lever():
    data = [{
        "text": "Data Scientist, Entry Level",
        "hostedUrl": "https://jobs.lever.co/plaid/abc",
        "categories": {"location": "San Francisco"},
        "createdAt": 1781136000000,
    }]
    jobs = job_sources.parse_lever(data, "Plaid")
    assert jobs[0]["title"] == "Data Scientist, Entry Level"
    assert jobs[0]["company"] == "Plaid"
    assert jobs[0]["url"] == "https://jobs.lever.co/plaid/abc"
    assert jobs[0]["source"] == "lever"
    assert jobs[0]["posted_date"]  # derived from createdAt epoch ms


def test_parse_ashby():
    data = {"jobs": [{
        "title": "Software Engineer - New Grad (2027)",
        "jobUrl": "https://jobs.ashbyhq.com/ramp/xyz",
        "location": "New York",
        "publishedAt": "2026-06-05T00:00:00Z",
    }]}
    jobs = job_sources.parse_ashby(data, "Ramp")
    assert jobs[0]["url"] == "https://jobs.ashbyhq.com/ramp/xyz"
    assert jobs[0]["posted_date"] == "2026-06-05"
    assert jobs[0]["source"] == "ashby"


def test_parse_handles_missing_fields():
    assert job_sources.parse_greenhouse({"jobs": [{"title": "SWE", "absolute_url": "u"}]}, "X")[0]["location"] == ""
    assert job_sources.parse_ashby({"jobs": [{"title": "SWE"}]}, "X")[0]["url"] == ""
