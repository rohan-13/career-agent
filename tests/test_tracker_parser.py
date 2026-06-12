import datetime

import job_sources

# SAMPLE uses the HTML <tr><td> format that SimplifyJobs/New-Grad-Positions actually uses.
# Each <tr> block has 5 <td> lines: company, title, location, apply, age.
SAMPLE = """
<table>
<tbody>
<tr>
<td><strong><a href="https://stripe.com">Stripe</a></strong></td>
<td>Software Engineer, New Grad</td>
<td>SF</td>
<td><div align="center"><a href="https://stripe.com/jobs/listing/123"><img src="apply.svg" alt="Apply"></a></div></td>
<td>2d</td>
</tr>
<tr>
<td>↳</td>
<td>Data Scientist, New Grad</td>
<td>NYC</td>
<td><div align="center"><a href="https://stripe.com/jobs/listing/456"><img src="apply.svg" alt="Apply"></a></div></td>
<td>5d</td>
</tr>
<tr>
<td><strong>Acme</strong></td>
<td>Junior ML Engineer</td>
<td>Remote</td>
<td><a href="https://acme.dev/jobs/789">Apply</a></td>
<td>Jun 01</td>
</tr>
<tr>
<td><strong>Locked</strong></td>
<td>SWE New Grad</td>
<td>Austin</td>
<td>🔒</td>
<td>1d</td>
</tr>
</tbody>
</table>
"""


def test_parses_rows_with_html_links():
    jobs = job_sources.parse_tracker_markdown(SAMPLE, "simplify")
    assert jobs[0]["company"] == "Stripe"
    assert jobs[0]["title"] == "Software Engineer, New Grad"
    assert jobs[0]["url"] == "https://stripe.com/jobs/listing/123"
    assert jobs[0]["source"] == "simplify"


def test_arrow_inherits_previous_company():
    jobs = job_sources.parse_tracker_markdown(SAMPLE, "simplify")
    assert jobs[1]["company"] == "Stripe"
    assert jobs[1]["title"] == "Data Scientist, New Grad"


def test_markdown_link_in_apply_cell():
    jobs = job_sources.parse_tracker_markdown(SAMPLE, "simplify")
    assert jobs[2]["url"] == "https://acme.dev/jobs/789"


def test_row_without_url_skipped():
    jobs = job_sources.parse_tracker_markdown(SAMPLE, "simplify")
    assert len(jobs) == 3  # the 🔒 (closed) row is dropped


def test_age_cell_converted_to_date():
    jobs = job_sources.parse_tracker_markdown(SAMPLE, "simplify")
    expected = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    assert jobs[0]["posted_date"] == expected
