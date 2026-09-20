import pandas as pd
import pytest

from etl.mobility_etl import (
    COL_COUNT,
    COL_DESTINATION,
    COL_DESTINATION_TITLE,
    COL_ORIGIN,
    COL_ORIGIN_TITLE,
    COL_YEAR,
    EXPECTED_AGGREGATED_ROWS,
    EXPECTED_COUNT_SUM,
    MobilityValidationError,
    extract_mobility,
    normalise_financial_year,
    remove_sentinels,
    transform_mobility,
    validate_mobility,
)


def make_test_data(rows):
    return pd.DataFrame(
        rows,
        columns=[
            COL_YEAR,
            COL_ORIGIN,
            COL_DESTINATION,
            COL_COUNT,
            COL_ORIGIN_TITLE,
            COL_DESTINATION_TITLE,
        ],
    )


def test_financial_year_is_cleaned():
    assert normalise_financial_year("2020_2021") == "2020-21"
    assert normalise_financial_year("2011_2012") == "2011-12"

    with pytest.raises(MobilityValidationError):
        normalise_financial_year("2020-2021")


def test_sentinel_codes_are_removed():
    df = make_test_data([
        ("2020_2021", "423111", "254411", 10, "A", "B"),
        ("2020_2021", "UNKNOWN", "254411", 20, "A", "B"),
        ("2020_2021", "423111", "NO_ITR", 30, "A", "B"),
        ("2020_2021", "NULL", "254411", 40, "A", "B"),
    ])

    clean = remove_sentinels(df)

    assert len(clean) == 1
    assert clean.iloc[0][COL_ORIGIN] == "423111"


def test_rollup_sums_worker_counts():
    # These three 6-digit transitions become one 4-digit transition
    df = make_test_data([
        ("2020_2021", "423111", "254411", 10, "Aged Carer", "Nurse"),
        ("2020_2021", "423112", "254412", 20, "Support Worker", "Nurse"),
        ("2020_2021", "423113", "254499", 30, "Carer", "Nurse"),
    ])

    clean = transform_mobility(df)

    assert len(clean) == 1

    row = clean.iloc[0]

    assert row["source_occupation_code"] == "4231"
    assert row["destination_occupation_code"] == "2544"
    assert row["worker_count"] == 60
    assert row["source_rows_merged"] == 3


def test_different_years_stay_separate():
    df = make_test_data([
        ("2019_2020", "423111", "254411", 10, "A", "B"),
        ("2020_2021", "423111", "254411", 25, "A", "B"),
    ])

    clean = transform_mobility(df)

    assert len(clean) == 2
    assert set(clean["financial_year"]) == {
        "2019-20",
        "2020-21",
    }

    assert clean["worker_count"].sum() == 35


def test_self_transitions_are_kept_and_flagged():
    df = make_test_data([
        ("2020_2021", "423111", "423112", 10, "A", "B"),
        ("2020_2021", "423111", "254411", 5, "A", "C"),
    ])

    clean = transform_mobility(df)

    self_transitions = clean[
        clean["is_self_transition"]
    ]

    assert len(self_transitions) == 1
    assert (
        self_transitions.iloc[0]["source_occupation_code"]
        == "4231"
    )

    assert self_transitions.iloc[0]["worker_count"] == 10


def test_invalid_code_length_is_rejected():
    df = make_test_data([
        ("2020_2021", "4231", "254411", 10, "A", "B")
    ])

    with pytest.raises(MobilityValidationError):
        transform_mobility(df)


def test_worker_counts_are_preserved_during_rollup():
    df = make_test_data([
        ("2020_2021", "423111", "254411", 100, "A", "B"),
        ("2020_2021", "423112", "254412", 200, "A", "B"),
        ("2020_2021", "423113", "254499", 300, "A", "B"),
    ])

    before = df[COL_COUNT].sum()
    clean = transform_mobility(df)
    after = clean["worker_count"].sum()

    assert before == after


def test_validation_rejects_negative_worker_count():
    df = make_test_data([
        ("2020_2021", "423111", "254411", 10, "A", "B")
    ])

    clean = transform_mobility(df)

    broken = clean.copy()
    broken.loc[broken.index[0], "worker_count"] = -5

    with pytest.raises(MobilityValidationError):
        validate_mobility(broken)


def test_full_dataset_matches_expected_totals():
    raw = extract_mobility()
    clean = transform_mobility(raw)

    assert len(clean) == EXPECTED_AGGREGATED_ROWS

    assert (
        int(clean["worker_count"].sum())
        == EXPECTED_COUNT_SUM
    )

    key = [
        "financial_year",
        "source_occupation_code",
        "destination_occupation_code",
    ]

    assert not clean.duplicated(key).any()