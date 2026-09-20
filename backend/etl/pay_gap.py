"""
Cleans the JSA Occupational Gender Pay Gap Dashboard data.

The source is at 6-digit ANZSCO level, while Telosia mainly uses 4-digit
Unit Groups. The 6-digit values are kept because the published figures are
medians and should not be averaged to create a 4-digit result.

Output:
    data/processed/pay_gap_clean.csv

Run:
    python -m etl.pay_gap_etl
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "datasets" / "Gender Pay Gap Dashboard_0.xlsx"
OUTPUT_FILE = ROOT / "data" / "processed" / "pay_gap_clean.csv"

SHEET_NAME = "Table_1"
HEADER_ROW = 6

CODE_COLUMN = "ANZSCO Code"
TITLE_COLUMN = "Occupation (ANZSCO 6-digit)"
COHORT_COLUMN = "Cohort Filter"

# Values used by the source for unavailable data
MISSING_TOKENS = {"-", "", "N/A", "NA", "NP"}

SOURCE_CODE_LENGTH = 6
PARENT_CODE_LENGTH = 4

# Rename source fields to simpler database-friendly names
FIELD_MAP = {
    "Gender segregation intensity": "segregation_intensity",
    "Female annual income (median)": "female_income_median",
    "Male annual income (median)": "male_income_median",
    "Gender pay gap (%, median)": "gender_pay_gap",
    "Gender differences in hours worked (%, median)": "hours_difference",
    "10-year gender pay gap (%, median)": "ten_year_pay_gap",
}

NUMERIC_FIELDS = [
    "female_income_median",
    "male_income_median",
    "gender_pay_gap",
    "hours_difference",
    "ten_year_pay_gap",
]

# These are stored as proportions in the workbook
PROPORTION_FIELDS = [
    "gender_pay_gap",
    "hours_difference",
    "ten_year_pay_gap",
]

HEADLINE_COHORT = "Whole workforce"

# Expected values from the current workbook
EXPECTED_ROWS = 3440
EXPECTED_OCCUPATIONS = 688
EXPECTED_COHORTS = 5
EXPECTED_PARENTS = 340

OUTPUT_COLUMNS = [
    "occupation_code",
    "parent_occupation_code",
    "occupation_title",
    "is_sole_child_of_parent",
    "cohort",
    "is_headline_cohort",
    "segregation_intensity",
    "female_income_median",
    "male_income_median",
    "gender_pay_gap",
    "hours_difference",
    "ten_year_pay_gap",
]

log = logging.getLogger(__name__)


class PayGapValidationError(Exception):
    """Raised when the cleaned pay gap data fails validation."""


def clean_numeric(value: object) -> float | None:
    """Convert numeric source values to floats and keep missing values as NULL."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, str):
        text = value.strip()

        if text.upper() in MISSING_TOKENS:
            return None

        try:
            return float(
                text
                .replace(",", "")
                .replace("$", "")
                .replace("%", "")
            )
        except ValueError:
            return None

    return float(value)


def extract_pay_gap(path: Path = RAW_FILE) -> pd.DataFrame:
    """Read the pay gap table from the workbook."""
    if not path.exists():
        raise FileNotFoundError(
            f"Gender Pay Gap Dashboard not found at {path}. "
            "Place the downloaded file in datasets/ without renaming it."
        )

    df = pd.read_excel(
        path,
        sheet_name=SHEET_NAME,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype={CODE_COLUMN: str},
    )

    log.info(
        "Extracted %d rows from sheet %r",
        len(df),
        SHEET_NAME,
    )

    return df


def transform_pay_gap(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the source data while keeping the original 6-digit grain."""
    missing_cols = [
        c
        for c in FIELD_MAP
        if c not in df.columns
    ]

    if missing_cols:
        raise PayGapValidationError(
            f"Sheet is missing expected columns: {missing_cols}. "
            "The publisher may have changed the workbook layout."
        )

    work = df[
        [
            CODE_COLUMN,
            TITLE_COLUMN,
            COHORT_COLUMN,
            *FIELD_MAP,
        ]
    ].copy()

    work = work.rename(
        columns={
            CODE_COLUMN: "occupation_code",
            TITLE_COLUMN: "occupation_title",
            COHORT_COLUMN: "cohort",
            **FIELD_MAP,
        }
    )

    work["occupation_code"] = (
        work["occupation_code"]
        .astype(str)
        .str.strip()
    )

    # Keep only valid 6-digit occupation records
    before = len(work)

    work = work[
        work["occupation_code"].str.match(
            rf"^\d{{{SOURCE_CODE_LENGTH}}}$"
        )
    ]

    if before != len(work):
        log.info(
            "Removed %d row(s) without a %d-digit code",
            before - len(work),
            SOURCE_CODE_LENGTH,
        )

    work["cohort"] = (
        work["cohort"]
        .astype(str)
        .str.strip()
    )

    work["is_headline_cohort"] = (
        work["cohort"] == HEADLINE_COHORT
    )

    log.info(
        "Cohorts present: %s",
        sorted(work["cohort"].unique()),
    )

    work["segregation_intensity"] = (
        work["segregation_intensity"]
        .astype(str)
        .str.strip()
    )

    for column in NUMERIC_FIELDS:
        work[column] = work[column].map(
            clean_numeric
        )

    # Keep the 4-digit parent code for linking back to Telosia occupations
    work["parent_occupation_code"] = (
        work["occupation_code"]
        .str[:PARENT_CODE_LENGTH]
    )

    headline = work[
        work["is_headline_cohort"]
    ]

    children = (
        headline
        .groupby("parent_occupation_code")[
            "occupation_code"
        ]
        .nunique()
    )

    sole = set(
        children[
            children == 1
        ].index
    )

    work["is_sole_child_of_parent"] = (
        work["parent_occupation_code"]
        .isin(sole)
    )

    log.info(
        "Parent unit groups: %d (%d with a single 6-digit child, "
        "%d with several)",
        len(children),
        len(sole),
        len(children) - len(sole),
    )

    log.info(
        "Medians are NOT aggregated to 4-digit: "
        "a median of medians is not a median."
    )

    result = (
        work[OUTPUT_COLUMNS]
        .sort_values(
            [
                "occupation_code",
                "cohort",
            ]
        )
        .reset_index(drop=True)
    )

    for column in NUMERIC_FIELDS:
        n_missing = int(
            result[column]
            .isna()
            .sum()
        )

        if n_missing:
            log.info(
                "  %s: %d of %d withheld by the publisher",
                column,
                n_missing,
                len(result),
            )

    return result


def validate_pay_gap(df: pd.DataFrame) -> None:
    """Run structural and value checks on the cleaned dataset."""
    failures: list[str] = []

    def check(
        label: str,
        condition: bool,
        detail: str = "",
    ) -> None:
        if condition:
            log.info(
                "  PASS  %s",
                label,
            )
        else:
            log.error(
                "  FAIL  %s%s",
                label,
                f" - {detail}" if detail else "",
            )

            failures.append(label)

    log.info(
        "Validating gender pay gap dataset"
    )

    check(
        f"row count == {EXPECTED_ROWS}",
        len(df) == EXPECTED_ROWS,
        f"got {len(df)}",
    )

    n_occ = df[
        "occupation_code"
    ].nunique()

    check(
        f"occupations == {EXPECTED_OCCUPATIONS}",
        n_occ == EXPECTED_OCCUPATIONS,
        f"got {n_occ}",
    )

    n_cohort = df[
        "cohort"
    ].nunique()

    check(
        f"cohorts == {EXPECTED_COHORTS}",
        n_cohort == EXPECTED_COHORTS,
        f"got {n_cohort}",
    )

    n_parent = df[
        "parent_occupation_code"
    ].nunique()

    check(
        f"parent unit groups == {EXPECTED_PARENTS}",
        n_parent == EXPECTED_PARENTS,
        f"got {n_parent}",
    )

    check(
        "every occupation_code matches ^\\d{6}$",
        df["occupation_code"]
        .str.match(r"^\d{6}$")
        .all(),
    )

    check(
        "every parent_occupation_code matches ^\\d{4}$",
        df["parent_occupation_code"]
        .str.match(r"^\d{4}$")
        .all(),
    )

    check(
        "codes stored as strings",
        df["occupation_code"]
        .map(type)
        .eq(str)
        .all()
        and
        df["parent_occupation_code"]
        .map(type)
        .eq(str)
        .all(),
    )

    dupes = df[
        df.duplicated(
            [
                "occupation_code",
                "cohort",
            ],
            keep=False,
        )
    ]

    check(
        "(occupation_code, cohort) is unique",
        dupes.empty,
        f"{len(dupes)} duplicated rows",
    )

    per_occ = (
        df
        .groupby("occupation_code")[
            "cohort"
        ]
        .nunique()
    )

    check(
        "every occupation has all cohorts",
        bool(
            (
                per_occ == EXPECTED_COHORTS
            ).all()
        ),
        f"min {per_occ.min()}, max {per_occ.max()}",
    )

    headline = df[
        df["is_headline_cohort"]
    ]

    check(
        f"headline cohort rows == {EXPECTED_OCCUPATIONS}",
        len(headline) == EXPECTED_OCCUPATIONS,
        f"got {len(headline)}",
    )

    for column in (
        "female_income_median",
        "male_income_median",
    ):
        values = df[
            column
        ].dropna()

        check(
            f"{column} is positive where present",
            bool(
                (
                    values > 0
                ).all()
            ),
            (
                f"min {values.min()}"
                if not values.empty
                else "no data"
            ),
        )

    # Gender pay gap cannot be greater than 1
    gap = df[
        "gender_pay_gap"
    ].dropna()

    check(
        "gender_pay_gap does not exceed 1",
        bool(
            (
                gap <= 1
            ).all()
        ),
        (
            f"max {gap.max()}"
            if not gap.empty
            else "no data"
        ),
    )

    # Some small cohorts can have large negative proportional differences
    for column in (
        "hours_difference",
        "ten_year_pay_gap",
    ):
        values = df[
            column
        ].dropna()

        check(
            f"{column} within -3 to 1",
            bool(
                values
                .between(-3, 1)
                .all()
            ),
            (
                f"range {values.min()}..{values.max()}"
                if not values.empty
                else "no data"
            ),
        )

    # Missing income must remain NULL rather than being changed to zero
    check(
        "no withheld income was filled with zero",
        not (
            (
                df[
                    [
                        "female_income_median",
                        "male_income_median",
                    ]
                ]
                == 0
            )
            .sum()
            .sum()
        ),
        "a zero median income would be implausible",
    )

    check(
        "segregation_intensity populated",
        df[
            "segregation_intensity"
        ]
        .notna()
        .all()
        and
        (
            df[
                "segregation_intensity"
            ]
            != ""
        )
        .all(),
    )

    check(
        "sole-child flag is consistent within a parent",
        bool(
            df
            .groupby(
                "parent_occupation_code"
            )[
                "is_sole_child_of_parent"
            ]
            .nunique()
            .eq(1)
            .all()
        ),
    )

    if failures:
        raise PayGapValidationError(
            f"{len(failures)} validation check(s) failed:\n  - "
            + "\n  - ".join(failures)
        )

    log.info(
        "All validation checks passed"
    )


def main(write_csv: bool = True) -> pd.DataFrame:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    log.info(
        "Reading %s",
        RAW_FILE.name,
    )

    clean = transform_pay_gap(
        extract_pay_gap()
    )

    validate_pay_gap(clean)

    if write_csv:
        OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        clean.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        log.info(
            "Wrote %s (%d rows)",
            OUTPUT_FILE,
            len(clean),
        )

    return clean


if __name__ == "__main__":
    main()