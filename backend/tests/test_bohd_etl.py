"""Tests for the BOHD ETL."""

import pandas as pd
import pytest

from etl.bohd_etl import (
    EXPECTED_OCCUPATIONS,
    EXPECTED_VARIABLES,
    BohdValidationError,
    extract_bohd,
    split_predictor_columns,
    transform_bohd,
    validate_bohd,
)


@pytest.fixture(scope="module")
def raw():
    return extract_bohd()


@pytest.fixture(scope="module")
def clean(raw):
    df, category_map, exclusions = raw
    return transform_bohd(df, category_map, exclusions)


def test_leakage_columns_are_identified():
    category_map = {
        "Spend Time Standing": "Body Positioning",
        "Employment ('000)": "ABS employment data",
        "Serious claims": "Workers' compensation claims data (based on 5-year averages)",
        "Frequency rate": "Workers' compensation claims data (based on 5-year averages)",
    }
    safe, leakage = split_predictor_columns(category_map)
    assert safe == ["Spend Time Standing"]
    assert set(leakage) == {"Employment ('000)", "Serious claims", "Frequency rate"}


def test_frequency_rate_never_survives_transform(clean):
    """Frequency rate is the WCIFR target; it must not reach a model."""
    variables = set(clean["hazard_variable"])
    assert "Frequency rate" not in variables
    assert "Incidence rate" not in variables
    assert "Serious claims" not in variables
    assert "Employment ('000)" not in variables


def test_shape_matches_source(clean):
    assert clean["occupation_code"].nunique() == EXPECTED_OCCUPATIONS
    assert clean["hazard_variable"].nunique() == EXPECTED_VARIABLES
    assert len(clean) == EXPECTED_OCCUPATIONS * EXPECTED_VARIABLES


def test_codes_are_four_digit_strings(clean):
    assert clean["occupation_code"].map(type).eq(str).all()
    assert clean["occupation_code"].str.match(r"^\d{4}$").all()


def test_scores_within_published_scale(clean):
    scores = clean["exposure_score"]
    assert scores.notna().all()
    assert scores.between(0, 100).all()


def test_float_artefacts_are_rounded(clean):
    """The source contains values such as 99.50000000000001."""
    decimals = clean["exposure_score"].map(lambda v: len(str(float(v)).split(".")[1]))
    assert decimals.max() <= 2


def test_excluded_occupations_are_absent_not_zero(raw, clean):
    _, _, exclusions = raw
    excluded = set(exclusions["ANZSCO code"].astype(str))
    assert excluded, "exclusions sheet should not be empty"
    assert not excluded & set(clean["occupation_code"])


def test_every_occupation_has_every_variable(clean):
    per_occupation = clean.groupby("occupation_code")["hazard_variable"].nunique()
    assert (per_occupation == EXPECTED_VARIABLES).all()


def test_no_duplicate_occupation_variable_pairs(clean):
    assert not clean.duplicated(["occupation_code", "hazard_variable"]).any()


def test_body_positioning_variables_are_present(clean):
    """These drive the physical demand view, so their loss should fail a test."""
    body = set(clean.loc[clean["hazard_category"] == "Body Positioning", "hazard_variable"])
    assert "Spend Time Standing" in body
    assert "Spend Time Bending or Twisting the Body" in body
    assert "Spend Time Kneeling, Crouching, Stooping, or Crawling" in body
    assert len(body) == 9


def test_validation_rejects_a_leaked_outcome_column(raw, clean):
    _, _, exclusions = raw
    broken = clean.copy()
    broken.loc[broken.index[0], "hazard_variable"] = "Frequency rate"
    with pytest.raises(BohdValidationError):
        validate_bohd(broken, exclusions)


def test_validation_rejects_out_of_range_score(raw, clean):
    _, _, exclusions = raw
    broken = clean.copy()
    broken.loc[broken.index[0], "exposure_score"] = 150.0
    with pytest.raises(BohdValidationError):
        validate_bohd(broken, exclusions)


def test_validation_rejects_missing_occupations(raw, clean):
    _, _, exclusions = raw
    broken = clean[clean["occupation_code"] != clean["occupation_code"].iloc[0]]
    with pytest.raises(BohdValidationError):
        validate_bohd(broken, exclusions)