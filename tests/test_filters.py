import filters


def test_new_grad_title_is_target():
    assert filters.is_target("Software Engineer, New Grad (2027)")


def test_entry_level_title_is_target():
    assert filters.is_target("Entry Level Data Engineer")


def test_early_career_with_role_is_target():
    assert filters.is_target("Machine Learning Engineer, Early Career")


def test_senior_excluded_even_with_2027():
    assert not filters.is_target("Senior Software Engineer (2027 start)")


def test_internship_excluded():
    assert not filters.is_target("Software Engineering Internship 2027")


def test_years_requirement_in_description_excluded():
    assert not filters.is_target(
        "Software Engineer, Early Career",
        "Requires 3+ years of professional experience",
    )


def test_senior_in_description_does_not_exclude():
    # "work with senior engineers" in a JD must not disqualify the role
    assert filters.is_target(
        "Software Engineer, New Grad",
        "You will work closely with senior engineers.",
    )


def test_non_eng_role_excluded():
    assert not filters.is_target("New Grad Account Executive")


def test_generic_title_without_signal_excluded():
    assert not filters.is_target("Software Engineer")


def test_match_strength_ordering():
    assert filters.match_strength("Software Engineer, New Grad 2027") == 3
    assert filters.match_strength("Entry Level Software Engineer") == 2
    assert filters.match_strength("Junior Data Engineer") == 1
    assert filters.match_strength("Software Engineer") == 0


def test_software_developer_is_target():
    assert filters.is_target("Software Developer, Early Career")


def test_mle_abbreviation_is_target():
    assert filters.is_target("MLE - New Grad")


def test_generic_engineer_title_with_signal_is_target():
    assert filters.is_target("Site Reliability Engineer I")


def test_include_signal_in_description_only():
    # tracker rows / JD bodies often carry the signal, not the title
    assert filters.is_target("Software Engineer", "New grad role. 0-2 years preferred.")


def test_non_software_engineering_excluded():
    assert not filters.is_target("New Grad Mechanical Engineer")
    assert not filters.is_target("Sales Engineer, Entry Level")


# ── Location filtering (added 2026-09-14) ───────────────────────────────────

def test_is_us_or_remote_us_state_true():
    assert filters.is_us_or_remote("Boston, MA")


def test_is_us_or_remote_usa_literal_true():
    assert filters.is_us_or_remote("Remote - USA")
    assert filters.is_us_or_remote("Some Office, United States")


def test_is_us_or_remote_bare_remote_true():
    assert filters.is_us_or_remote("Remote")


def test_is_us_or_remote_missing_location_true():
    assert filters.is_us_or_remote("")
    assert filters.is_us_or_remote(None)


def test_is_us_or_remote_ambiguous_city_code_true():
    # No state/country signal at all -- these show up constantly in ATS data
    # (SF, NYC, LA) and are effectively always US roles in this pipeline.
    assert filters.is_us_or_remote("SF")
    assert filters.is_us_or_remote("NYC")


def test_is_us_or_remote_canada_only_false():
    assert not filters.is_us_or_remote("Toronto, ON, Canada")
    assert not filters.is_us_or_remote("Burnaby, BC, Canada")


def test_is_us_or_remote_remote_canada_false():
    assert not filters.is_us_or_remote("Remote - Canada")


def test_is_us_or_remote_remote_canada_no_separator_false():
    # Regression: Greenhouse renders this as "Remote Canada" (space, no dash)
    # -- found live 2026-09-14 on an Affirm posting that slipped past the
    # dash-required version of this check.
    assert not filters.is_us_or_remote("Remote Canada")


def test_is_us_or_remote_uk_only_false():
    assert not filters.is_us_or_remote("London, UK")


def test_is_us_or_remote_other_country_false():
    assert not filters.is_us_or_remote("Remote - Ukraine")
    assert not filters.is_us_or_remote("Bengaluru, India")


def test_is_target_excludes_canada_only_location():
    assert not filters.is_target(
        "Software Engineer New Grad - 2027 Graduate", location="Burnaby, BC, Canada"
    )


def test_is_target_excludes_uk_only_location():
    assert not filters.is_target(
        "Software Engineer New Grad", location="London, UK"
    )


def test_is_target_keeps_us_location():
    assert filters.is_target(
        "Software Engineer New Grad", location="Boston, MA"
    )


def test_is_target_keeps_remote():
    assert filters.is_target("Software Engineer New Grad", location="Remote")


def test_is_target_missing_location_not_excluded():
    # Backward compatible: callers (and older tests) that don't pass a
    # location at all must not have jobs silently excluded.
    assert filters.is_target("Software Engineer New Grad")
