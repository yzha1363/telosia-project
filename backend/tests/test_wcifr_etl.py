import pandas as pd
import pytest

from etl.wcifr_etl import (
    EXPECTED_BLANK,
    EXPECTED_NUMERIC,
    EXPECTED_OCCUPATIONS,
    EXPECTED_ROWS,
    EXPECTED_SUPPRESSED,
    EXPECTED_YEARS,
    OUTPUT_COLUMNS,
    WcifrValidationError,
    _classify_value,
    _normalise_financial_year,
    _split_code_title,
    extract_wcifr,
    transform_wcifr,
    validate_wcifr,
)


def test_split_code_title():
    code, title = _split_code_title("4231 Aged and disabled carers")

    assert code == "4231"
    assert title == "Aged and disabled carers"


def test_split_code_title_total_returns_none():
    code, title = _split_code_title("Total")

    assert code is None
    assert title is None


def test_normalise_preliminary_financial_year():
    year, preliminary = _normalise_financial_year("2023-24p")

    assert year == "2023-24"
    assert preliminary is True


def test_normalise_standard_financial_year():
    year, preliminary = _normalise_financial_year("2022-23")

    assert year == "2022-23"
    assert preliminary is False


def test_classify_suppressed_value():
    rate, suppressed = _classify_value("NP")

    assert rate is None
    assert suppressed is True


def test_classify_blank_value():
    rate, suppressed = _classify_value(None)

    assert rate is None
    assert suppressed is False


def test_classify_numeric_value():
    rate, suppressed = _classify_value(12.5)

    assert rate == 12.5
    assert suppressed is False


def test_unrecognised_value_raises_error():
    with pytest.raises(WcifrValidationError):
        _classify_value("unexpected-text")


@pytest.fixture(scope="module")
def transformed_wcifr():
    raw = extract_wcifr()
    return transform_wcifr(raw)


def test_output_columns(transformed_wcifr):
    assert list(transformed_wcifr.columns) == OUTPUT_COLUMNS


def test_expected_row_count(transformed_wcifr):
    assert len(transformed_wcifr) == EXPECTED_ROWS


def test_expected_occupation_count(transformed_wcifr):
    assert transformed_wcifr["occupation_code"].nunique() == EXPECTED_OCCUPATIONS


def test_expected_year_count(transformed_wcifr):
    assert transformed_wcifr["financial_year"].nunique() == EXPECTED_YEARS


def test_only_four_digit_anzsco_codes(transformed_wcifr):
    assert transformed_wcifr["occupation_code"].str.fullmatch(r"\d{4}").all()
    assert (transformed_wcifr["anzsco_level"] == 4).all()


def test_occupation_year_rows_are_unique(transformed_wcifr):
    duplicates = transformed_wcifr.duplicated(
        subset=["occupation_code", "financial_year"]
    )

    assert not duplicates.any()


def test_frequency_value_counts(transformed_wcifr):
    numeric_count = transformed_wcifr["frequency_rate"].notna().sum()
    suppressed_count = transformed_wcifr["is_suppressed"].sum()

    blank_count = (
        transformed_wcifr["frequency_rate"].isna()
        & ~transformed_wcifr["is_suppressed"]
    ).sum()

    assert numeric_count == EXPECTED_NUMERIC
    assert suppressed_count == EXPECTED_SUPPRESSED
    assert blank_count == EXPECTED_BLANK


def test_suppressed_values_are_null(transformed_wcifr):
    suppressed = transformed_wcifr[
        transformed_wcifr["is_suppressed"]
    ]

    assert suppressed["frequency_rate"].isna().all()


def test_preliminary_year(transformed_wcifr):
    preliminary = transformed_wcifr[
        transformed_wcifr["is_preliminary"]
    ]

    assert set(preliminary["financial_year"]) == {"2023-24"}


def test_nfd_occupation_is_retained(transformed_wcifr):
    assert "5910" in set(transformed_wcifr["occupation_code"])


def test_complete_validation_passes(transformed_wcifr):
    validate_wcifr(transformed_wcifr)


def test_duplicate_record_fails_validation(transformed_wcifr):
    duplicate = transformed_wcifr.iloc[[0]].copy()

    broken = pd.concat(
        [transformed_wcifr, duplicate],
        ignore_index=True,
    )

    with pytest.raises(WcifrValidationError):
        validate_wcifr(broken)