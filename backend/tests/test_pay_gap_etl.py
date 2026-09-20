import pandas as pd
import pytest

import etl.pay_gap as pay_gap_etl


def make_source_data():
    rows = []

    occupations = [
        (
            "111111",
            "Occupation One",
            "Male dominated",
        ),
        (
            "111112",
            "Occupation Two",
            "Balanced",
        ),
        (
            "222211",
            "Occupation Three",
            "Female dominated",
        ),
    ]

    cohorts = [
        "Whole workforce",
        "20-24 year olds",
    ]

    for code, title, segregation in occupations:
        for cohort in cohorts:
            rows.append(
                {
                    "ANZSCO Code": code,
                    "Occupation (ANZSCO 6-digit)":
                        title,
                    "Cohort Filter": cohort,
                    "Gender segregation intensity":
                        segregation,
                    "Female annual income (median)":
                        60000,
                    "Male annual income (median)":
                        70000,
                    "Gender pay gap (%, median)":
                        0.14,
                    "Gender differences in hours worked (%, median)":
                        -0.05,
                    "10-year gender pay gap (%, median)":
                        0.18,
                }
            )

    return pd.DataFrame(rows)


def test_clean_numeric_handles_missing_values():
    assert pay_gap_etl.clean_numeric(None) is None
    assert pay_gap_etl.clean_numeric("-") is None
    assert pay_gap_etl.clean_numeric("NP") is None
    assert pay_gap_etl.clean_numeric("") is None


def test_clean_numeric_converts_numbers():
    assert pay_gap_etl.clean_numeric(
        "$60,000"
    ) == pytest.approx(60000)

    assert pay_gap_etl.clean_numeric(
        "0.165"
    ) == pytest.approx(0.165)


def test_transform_keeps_six_digit_grain():
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    assert (
        result[
            "occupation_code"
        ]
        .str.len()
        .eq(6)
        .all()
    )

    assert len(result) == 6


def test_transform_creates_parent_codes():
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    parents = dict(
        zip(
            result["occupation_code"],
            result[
                "parent_occupation_code"
            ],
        )
    )

    assert parents["111111"] == "1111"
    assert parents["111112"] == "1111"
    assert parents["222211"] == "2222"


def test_transform_marks_sole_child_parent():
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    first_parent = result[
        result[
            "parent_occupation_code"
        ] == "1111"
    ]

    second_parent = result[
        result[
            "parent_occupation_code"
        ] == "2222"
    ]

    assert not first_parent[
        "is_sole_child_of_parent"
    ].any()

    assert second_parent[
        "is_sole_child_of_parent"
    ].all()


def test_transform_marks_headline_cohort():
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    headline = result[
        result["is_headline_cohort"]
    ]

    assert len(headline) == 3

    assert (
        headline["cohort"]
        == "Whole workforce"
    ).all()


def test_transform_keeps_missing_values_as_null():
    source = make_source_data()

    source["Female annual income (median)"] = (
        source["Female annual income (median)"]
        .astype(object)
    )

    source.loc[
        0,
        "Female annual income (median)",
    ] = "-"

    result = pay_gap_etl.transform_pay_gap(
        source
    )

    row = result[
        (
            result["occupation_code"]
            == "111111"
        )
        &
        (
            result["cohort"]
            == "Whole workforce"
        )
    ].iloc[0]

    assert pd.isna(
        row["female_income_median"]
    )

def test_transform_keeps_expected_columns():
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    assert result.columns.tolist() == (
        pay_gap_etl.OUTPUT_COLUMNS
    )


def test_transform_rejects_missing_source_column():
    source = make_source_data().drop(
        columns=["Gender pay gap (%, median)"]
    )

    with pytest.raises(
        pay_gap_etl.PayGapValidationError
    ):
        pay_gap_etl.transform_pay_gap(
            source
        )


def test_validation_passes_for_valid_clean_data(
    monkeypatch,
):
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_ROWS",
        6,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_OCCUPATIONS",
        3,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_COHORTS",
        2,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_PARENTS",
        2,
    )

    pay_gap_etl.validate_pay_gap(
        result
    )


def test_validation_rejects_duplicate_business_key(
    monkeypatch,
):
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    duplicate = pd.concat(
        [
            result,
            result.iloc[[0]],
        ],
        ignore_index=True,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_ROWS",
        7,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_OCCUPATIONS",
        3,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_COHORTS",
        2,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_PARENTS",
        2,
    )

    with pytest.raises(
        pay_gap_etl.PayGapValidationError
    ):
        pay_gap_etl.validate_pay_gap(
            duplicate
        )


def test_validation_rejects_impossible_pay_gap(
    monkeypatch,
):
    result = pay_gap_etl.transform_pay_gap(
        make_source_data()
    )

    result.loc[
        result.index[0],
        "gender_pay_gap",
    ] = 1.2

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_ROWS",
        6,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_OCCUPATIONS",
        3,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_COHORTS",
        2,
    )

    monkeypatch.setattr(
        pay_gap_etl,
        "EXPECTED_PARENTS",
        2,
    )

    with pytest.raises(
        pay_gap_etl.PayGapValidationError
    ):
        pay_gap_etl.validate_pay_gap(
            result
        )


def test_real_pay_gap_workbook_when_available():
    if not pay_gap_etl.RAW_FILE.exists():
        pytest.skip(
            "Gender pay gap workbook is not available locally"
        )

    result = pay_gap_etl.main(
        write_csv=False
    )

    assert len(result) == 3440

    assert (
        result[
            "occupation_code"
        ].nunique()
        == 688
    )

    assert (
        result[
            "parent_occupation_code"
        ].nunique()
        == 340
    )

    assert (
        result[
            "cohort"
        ].nunique()
        == 5
    )

    assert not result.duplicated(
        [
            "occupation_code",
            "cohort",
        ]
    ).any()
