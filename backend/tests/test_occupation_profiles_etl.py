import pandas as pd
import pytest

from etl.occupation_profiles_etl import (
    EDUCATION_FIELDS,
    EXPECTED_4DIGIT,
    ProfilesValidationError,
    clean_numeric,
    extract_profiles,
    transform_profiles,
    validate_profiles,
)


@pytest.fixture(scope="module")
def clean():
    overview, education = extract_profiles()
    return transform_profiles(overview, education)


def test_missing_values_stay_null():
    assert clean_numeric("N/A") is None
    assert clean_numeric("NP") is None
    assert clean_numeric("") is None
    assert clean_numeric(None) is None


def test_missing_values_do_not_become_zero():
    for value in ("N/A", "NA", "-", ""):
        assert clean_numeric(value) != 0


def test_numeric_formatting_is_cleaned():
    assert clean_numeric("1,234") == 1234.0
    assert clean_numeric("$980") == 980.0
    assert clean_numeric("45%") == 45.0
    assert clean_numeric(37) == 37.0


def test_only_four_digit_occupations_are_kept(clean):
    assert len(clean) == EXPECTED_4DIGIT
    assert clean["occupation_code"].str.len().eq(4).all()
    assert clean["anzsco_level"].eq(4).all()


def test_occupation_codes_are_unique_strings(clean):
    assert clean["occupation_code"].is_unique
    assert clean["occupation_code"].map(type).eq(str).all()


def test_percentage_fields_are_in_range(clean):
    percentage_columns = [
        "female_share_pct",
        "part_time_share_pct",
        *EDUCATION_FIELDS.values(),
    ]

    for column in percentage_columns:
        values = clean[column].dropna()
        assert values.between(0, 100).all(), column


def test_missing_earnings_stay_null(clean):
    # The 4-digit dataset contains occupations with unpublished earnings
    assert clean["median_weekly_earnings"].isna().sum() == 62
    assert not (clean["median_weekly_earnings"] == 0).any()


def test_female_share_is_preserved(clean):
    assert clean["female_share_pct"].isna().sum() == 11
    assert clean["female_share_pct"].notna().sum() > 300


def test_education_shares_are_plausible(clean):
    education_columns = list(
        EDUCATION_FIELDS.values()
    )

    totals = (
        clean[education_columns]
        .dropna()
        .sum(axis=1)
    )

    assert totals.min() > 80
    assert totals.max() < 100.5


def test_validation_rejects_duplicate_occupation(clean):
    broken = pd.concat(
        [clean, clean.head(1)],
        ignore_index=True,
    )

    with pytest.raises(ProfilesValidationError):
        validate_profiles(broken)


def test_validation_rejects_invalid_percentage(clean):
    broken = clean.copy()

    broken.loc[
        broken.index[0],
        "female_share_pct",
    ] = 140.0

    with pytest.raises(ProfilesValidationError):
        validate_profiles(broken)