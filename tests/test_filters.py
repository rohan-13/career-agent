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
