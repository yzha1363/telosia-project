
import pandas as pd
import pytest

import etl.ai_exposure as ai_etl


def make_source_data():
    return pd.DataFrame(
        {
            "ANZSCO unit code": [
                "1111",
                "2222",
                "Source: Jobs and Skills Australia",
            ],
            "ANZSCO unit title": [
                "Occupation One",
                "Occupation Two",
                "Footnote",
            ],
            "Occupation matrix group": [
                "Management",
                "Health",
                "",
            ],
            "Automation exposure score": [
                0.30,
                0.60,
                None,
            ],
            "Automation standard deviation": [
                0.10,
                0.20,
                None,
            ],
            "Augmentation exposure score": [
                0.70,
                0.50,
                None,
            ],
            "Augmentation standard deviation": [
                0.10,
                0.15,
                None,
            ],
            "Rate of skill change": [
                3.2,
                "-",
                None,
            ],
            "High-fit transition rate": [
                0.40,
                0.30,
                None,
            ],
            "Share of job ads that are entry level (%)": [
                0.20,
                0.25,
                None,
            ],
        }
    )


def test_clean_numeric_handles_missing_values():
    assert ai_etl.clean_numeric(None) is None
    assert ai_etl.clean_numeric("-") is None
    assert ai_etl.clean_numeric("N/A") is None
    assert ai_etl.clean_numeric("") is None


def test_clean_numeric_converts_numbers():
    assert ai_etl.clean_numeric("0.45") == pytest.approx(0.45)
    assert ai_etl.clean_numeric(0.72) == pytest.approx(0.72)


def test_transform_keeps_only_four_digit_occupations():
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    assert len(result) == 2
    assert result["occupation_code"].tolist() == [
        "1111",
        "2222",
    ]


def test_transform_sets_anzsco_level():
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    assert (
        result["anzsco_level"] == 4
    ).all()


def test_transform_keeps_expected_columns():
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    assert result.columns.tolist() == (
        ai_etl.OUTPUT_COLUMNS
    )


def test_transform_keeps_missing_numeric_as_null():
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    row = result[
        result["occupation_code"] == "2222"
    ].iloc[0]

    assert pd.isna(
        row["rate_of_skill_change"]
    )


def test_transform_rejects_missing_source_column():
    source = make_source_data().drop(
        columns=["Automation exposure score"]
    )

    with pytest.raises(
        ai_etl.AiExposureValidationError
    ):
        ai_etl.transform_ai_exposure(source)


def test_validation_passes_for_valid_clean_data(
    monkeypatch,
):
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    monkeypatch.setattr(
        ai_etl,
        "EXPECTED_OCCUPATIONS",
        2,
    )

    ai_etl.validate_ai_exposure(result)


def test_validation_rejects_duplicate_occupation(
    monkeypatch,
):
    result = ai_etl.transform_ai_exposure(
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
        ai_etl,
        "EXPECTED_OCCUPATIONS",
        3,
    )

    with pytest.raises(
        ai_etl.AiExposureValidationError
    ):
        ai_etl.validate_ai_exposure(
            duplicate
        )


def test_validation_rejects_out_of_range_score(
    monkeypatch,
):
    result = ai_etl.transform_ai_exposure(
        make_source_data()
    )

    result.loc[
        result.index[0],
        "automation_exposure",
    ] = 1.20

    monkeypatch.setattr(
        ai_etl,
        "EXPECTED_OCCUPATIONS",
        2,
    )

    with pytest.raises(
        ai_etl.AiExposureValidationError
    ):
        ai_etl.validate_ai_exposure(
            result
        )


def test_real_ai_workbook_when_available():
    if not ai_etl.RAW_FILE.exists():
        pytest.skip(
            "AI exposure workbook is not available locally"
        )

    result = ai_etl.main(
        write_csv=False
    )

    assert len(result) == 357
    assert result[
        "occupation_code"
    ].is_unique

    assert (
        result[
            "automation_exposure"
        ]
        .between(0, 1)
        .all()
    )

    assert (
        result[
            "augmentation_exposure"
        ]
        .between(0, 1)
        .all()
    )
