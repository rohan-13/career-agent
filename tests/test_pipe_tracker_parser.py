import datetime

import job_sources

# SAMPLE mimics vanshb03/New-Grad-2027's README format: a markdown pipe table
# with Company / Role / Location / Application-Link / Date-Posted columns,
# link+company wrapped in HTML anchor/strong tags.
VANSH_SAMPLE = """
## The List

| Company | Role | Location | Application/Link | Date Posted |
| --- | --- | --- | :---: | :---: |
| **Quora** | New Grad: Software Engineer | Remote | <a href="https://jobs.ashbyhq.com/quora/abc"><img src="apply.png" alt="Apply"></a> | Aug 05 |
| **Chicago Trading Company** | New Grad 2027: Associate Engineer | Chicago, IL</br>New York, NY | <a href="https://job-boards.greenhouse.io/ctc/1"><img src="apply.png" alt="Apply"></a> | Aug 01 |
| **Locked Co** | SWE New Grad | Austin | 🔒 | Jul 24 |
"""

# SAMPLE mimics speedyapply/2027-SWE-College-Jobs: two tables in one file with
# DIFFERENT column layouts (FAANG+ has a Salary column, Other does not), plus
# a relative "Age" column ("0d", "1d") instead of a bare date.
SPEEDY_SAMPLE = """
### FAANG+

| Company | Position | Location | Salary | Posting | Age |
|---|---|---|---|---|---|
| <a href="https://stripe.com"><strong>Stripe</strong></a> | Software Engineer - New Grad | San Francisco, CA | $207k/yr | <a href="https://stripe.com/jobs/8128744"><img src="apply.png" alt="Apply" width="70"/></a> | 0d |

### Other

| Company | Position | Location | Posting | Age |
|---|---|---|---|---|
| <a href="https://acme.dev"><strong>Acme</strong></a> | Junior Data Engineer | Remote | <a href="https://acme.dev/jobs/9"><img src="apply.png" alt="Apply" width="70"/></a> | 3d |
"""


def test_vansh_format_parses_company_role_link():
    jobs = job_sources.parse_tracker_pipe_markdown(VANSH_SAMPLE, "vansh")
    assert jobs[0]["company"] == "Quora"
    assert jobs[0]["title"] == "New Grad: Software Engineer"
    assert jobs[0]["url"] == "https://jobs.ashbyhq.com/quora/abc"
    assert jobs[0]["source"] == "vansh"


def test_vansh_location_html_break_stripped():
    jobs = job_sources.parse_tracker_pipe_markdown(VANSH_SAMPLE, "vansh")
    assert jobs[1]["location"] == "Chicago, ILNew York, NY"


def test_vansh_locked_row_skipped():
    jobs = job_sources.parse_tracker_pipe_markdown(VANSH_SAMPLE, "vansh")
    assert len(jobs) == 2  # the 🔒 row has no link and is dropped


def test_vansh_monthday_date_converted():
    jobs = job_sources.parse_tracker_pipe_markdown(VANSH_SAMPLE, "vansh")
    today = datetime.date.today()
    year = today.year if datetime.date(today.year, 8, 5) <= today else today.year - 1
    assert jobs[0]["posted_date"] == datetime.date(year, 8, 5).isoformat()


def test_speedy_faang_and_other_tables_both_parsed_despite_different_columns():
    jobs = job_sources.parse_tracker_pipe_markdown(SPEEDY_SAMPLE, "speedyapply")
    assert len(jobs) == 2
    assert jobs[0]["company"] == "Stripe"
    assert jobs[1]["company"] == "Acme"
    assert jobs[1]["title"] == "Junior Data Engineer"


def test_speedy_age_column_converted_via_existing_age_parser():
    jobs = job_sources.parse_tracker_pipe_markdown(SPEEDY_SAMPLE, "speedyapply")
    today = datetime.date.today()
    assert jobs[0]["posted_date"] == today.isoformat()
    assert jobs[1]["posted_date"] == (today - datetime.timedelta(days=3)).isoformat()


def test_monthday_to_date_rolls_back_year_for_future_dates():
    # A "Dec 31" date should never resolve to a future date.
    result = job_sources._monthday_to_date("Dec 31")
    assert result <= datetime.date.today().isoformat()


def test_monthday_to_date_invalid_input_returns_empty():
    assert job_sources._monthday_to_date("not a date") == ""
    assert job_sources._monthday_to_date("Xyz 05") == ""


def test_fetch_trackers_dispatches_html_and_pipe_parsers(monkeypatch):
    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    html_sample = """
<tr>
<td><strong>Stripe</strong></td>
<td>SWE New Grad</td>
<td>SF</td>
<td><a href="https://stripe.com/jobs/1">Apply</a></td>
<td>1d</td>
</tr>
"""
    responses = {
        "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md": html_sample,
        "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/dev/README.md": VANSH_SAMPLE,
        "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md": SPEEDY_SAMPLE,
        # speedyapply's separate AI/DS/ML new-grad repo uses the same pipe
        # format as its SWE repo, so the SPEEDY_SAMPLE fixture doubles for both.
        "https://raw.githubusercontent.com/speedyapply/2027-AI-College-Jobs/main/NEW_GRAD_USA.md": SPEEDY_SAMPLE,
    }

    def fake_get(url, timeout=None, headers=None):
        return FakeResponse(responses[url])

    monkeypatch.setattr(job_sources.requests, "get", fake_get)
    jobs = job_sources.fetch_trackers()
    sources = {j["source"] for j in jobs}
    assert sources == {"simplify", "vansh", "speedyapply", "speedyapply-ai"}
    assert len(jobs) == 1 + 2 + 2 + 2  # simplify + vansh + speedyapply + speedyapply-ai sample counts
