import pandas as pd
import pytest

import etl.nds as nds_etl


@pytest.fixture(scope="module")
def real_nds():
    if not nds_etl.RAW_FILE.exists():
        pytest.skip(
            "NDS workbook is not available locally"
        )

    return nds_etl.extract_nds(
        nds_etl.RAW_FILE
    )


def test_split_code_label():
    code, label = nds_etl.split_code_label(
        "42 Carers and aides"
    )

    assert code == "42"
    assert label == "Carers and aides"


def test_split_total():
    code, label = nds_etl.split_code_label(
        "Total"
    )

    assert code == "TOTAL"
    assert label == "Total"


def test_normalise_preliminary_year():
    year, preliminary = nds_etl.normalise_year(
        "2023-24p"
    )

    assert year == "2023-24"
    assert preliminary is True


def test_normalise_standard_year():
    year, preliminary = nds_etl.normalise_year(
        "2022-23"
    )

    assert year == "2022-23"
    assert preliminary is False


def test_normalise_rejects_bad_year():
    with pytest.raises(
        nds_etl.NdsValidationError
    ):
        nds_etl.normalise_year(
            "2024"
        )


def test_clean_value_keeps_np_separate():
    value, is_not_published = (
        nds_etl.clean_value("NP")
    )

    assert value is None
    assert is_not_published is True


def test_clean_value_keeps_blank_separate():
    value, is_not_published = (
        nds_etl.clean_value(None)
    )

    assert value is None
    assert is_not_published is False


def test_clean_value_converts_numbers():
    value, is_not_published = (
        nds_etl.clean_value("12,532")
    )

    assert value == pytest.approx(
        12532
    )
    assert is_not_published is False


def test_industry_category_levels():
    level, parent, is_nfd, current = (
        nds_etl.classify_category(
            "industry",
            "A",
            "Agriculture, forestry and fishing",
            None,
        )
    )

    assert level == "division"
    assert parent is None
    assert is_nfd is False
    assert current == "A"

    level, parent, is_nfd, _ = (
        nds_etl.classify_category(
            "industry",
            "A0",
            "Agriculture, forestry and fishing, nfd",
            "A",
        )
    )

    assert level == "division_nfd"
    assert parent == "A"
    assert is_nfd is True


def test_occupation_category_levels():
    level, parent, is_nfd, _ = (
        nds_etl.classify_category(
            "occupation",
            "4",
            "Community and personal service workers",
            None,
        )
    )

    assert level == "major_group"
    assert parent is None
    assert is_nfd is False

    level, parent, is_nfd, _ = (
        nds_etl.classify_category(
            "occupation",
            "42",
            "Carers and aides",
            "4",
        )
    )

    assert level == "sub_major_group"
    assert parent == "4"
    assert is_nfd is False


def test_occupation_nfd_is_flagged():
    level, parent, is_nfd, _ = (
        nds_etl.classify_category(
            "occupation",
            "40",
            "Community and personal service workers, nfd",
            "4",
        )
    )

    assert level == "sub_major_group_nfd"
    assert parent == "4"
    assert is_nfd is True


def test_real_workbook_counts(real_nds):
    categories, claims = real_nds

    assert len(categories) == 186
    assert len(claims) == 9300

    assert (
        categories[
            "dimension"
        ]
        .value_counts()
        .to_dict()
        == {
            "industry": 126,
            "occupation": 60,
        }
    )


def test_real_workbook_has_all_five_measures(
    real_nds,
):
    _, claims = real_nds

    assert set(
        claims["measure"]
    ) == {
        "claim_count",
        "frequency_rate",
        "incidence_rate",
        "median_compensation",
        "median_time_lost",
    }

    for measure in nds_etl.MEASURES.values():
        measure_name = measure[0]

        assert len(
            claims[
                (
                    claims["dimension"]
                    == "industry"
                )
                & (
                    claims["measure"]
                    == measure_name
                )
            ]
        ) == 1260

        assert len(
            claims[
                (
                    claims["dimension"]
                    == "occupation"
                )
                & (
                    claims["measure"]
                    == measure_name
                )
            ]
        ) == 600


def test_real_workbook_preserves_missing_states(
    real_nds,
):
    _, claims = real_nds

    assert int(
        claims[
            "is_not_published"
        ].sum()
    ) == 1705

    genuine_blanks = claims[
        claims["value"].isna()
        & ~claims["is_not_published"]
    ]

    assert len(
        genuine_blanks
    ) == 2

    assert set(
        genuine_blanks[
            "category_code"
        ]
    ) == {
        "99"
    }

    assert set(
        genuine_blanks[
            "measure"
        ]
    ) == {
        "frequency_rate",
        "incidence_rate",
    }


def test_real_workbook_preliminary_year(
    real_nds,
):
    _, claims = real_nds

    preliminary = claims[
        claims["is_preliminary"]
    ]

    assert len(
        preliminary
    ) == 930

    assert set(
        preliminary[
            "financial_year"
        ]
    ) == {
        "2023-24"
    }


def test_carers_and_aides_category(
    real_nds,
):
    categories, _ = real_nds

    carers = categories[
        (
            categories["dimension"]
            == "occupation"
        )
        & (
            categories["category_code"]
            == "42"
        )
    ]

    assert len(
        carers
    ) == 1

    row = carers.iloc[0]

    assert row[
        "category_label"
    ] == "Carers and aides"

    assert row[
        "level"
    ] == "sub_major_group"

    assert row[
        "parent_code"
    ] == "4"


def test_carers_and_aides_2022_23_claims(
    real_nds,
):
    _, claims = real_nds

    rows = claims[
        (
            claims["dimension"]
            == "occupation"
        )
        & (
            claims["category_code"]
            == "42"
        )
        & (
            claims["financial_year"]
            == "2022-23"
        )
    ]

    values = dict(
        zip(
            rows["measure"],
            rows["value"],
        )
    )

    assert values[
        "claim_count"
    ] == pytest.approx(
        12532
    )

    assert values[
        "frequency_rate"
    ] == pytest.approx(
        14.005,
        abs=0.01,
    )

    assert values[
        "incidence_rate"
    ] == pytest.approx(
        17.995,
        abs=0.01,
    )

    assert values[
        "median_compensation"
    ] == pytest.approx(
        9297,
        abs=1,
    )

    assert values[
        "median_time_lost"
    ] == pytest.approx(
        5.926,
        abs=0.01,
    )


def test_real_workbook_validation_passes(
    real_nds,
):
    categories, claims = real_nds

    nds_etl.validate_nds(
        categories,
        claims,
    )


def test_validation_rejects_duplicate_claim_key(
    real_nds,
):
    categories, claims = real_nds

    duplicate = pd.concat(
        [
            claims,
            claims.iloc[[0]],
        ],
        ignore_index=True,
    )

    with pytest.raises(
        nds_etl.NdsValidationError
    ):
        nds_etl.validate_nds(
            categories,
            duplicate,
        )
