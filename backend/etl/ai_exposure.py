"""
Cleans the JSA Generative AI Capacity Study occupation data.

The source is already published at 4-digit ANZSCO Unit Group level, which
matches the level used by Telosia, so no occupation roll-up is needed.

Output:
    data/processed/ai_exposure_clean.csv

Run:
    python -m etl.ai_exposure_etl
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "datasets" / "jsa_gen_ai_interactive_table_data_pack_20250903.xlsx"
OUTPUT_FILE = ROOT / "data" / "processed" / "ai_exposure_clean.csv"

SHEET_NAME = "Occupation"
HEADER_ROW = 6

CODE_COLUMN = "ANZSCO unit code"
TITLE_COLUMN = "ANZSCO unit title"

# Values used by the source for unavailable data
MISSING_TOKENS = {"-", "", "N/A", "NA", "NP"}

TARGET_ANZSCO_LEVEL = 4

# Rename the source fields used by Telosia
FIELD_MAP = {
    "Occupation matrix group": "occupation_matrix_group",
    "Automation exposure score": "automation_exposure",
    "Automation standard deviation": "automation_sd",
    "Augmentation exposure score": "augmentation_exposure",
    "Augmentation standard deviation": "augmentation_sd",
    "Rate of skill change": "rate_of_skill_change",
    "High-fit transition rate": "high_fit_transition_rate",
    "Share of job ads that are entry level (%)": "entry_level_ad_share",
}

# These values are expected to stay between 0 and 1
SCORE_FIELDS = [
    "automation_exposure",
    "augmentation_exposure",
    "automation_sd",
    "augmentation_sd",
    "high_fit_transition_rate",
    "entry_level_ad_share",
]

EXPECTED_OCCUPATIONS = 357

OUTPUT_COLUMNS = [
    "occupation_code",
    "occupation_title",
    "anzsco_level",
    "occupation_matrix_group",
    "automation_exposure",
    "automation_sd",
    "augmentation_exposure",
    "augmentation_sd",
    "rate_of_skill_change",
    "high_fit_transition_rate",
    "entry_level_ad_share",
]

log = logging.getLogger(__name__)


class AiExposureValidationError(Exception):
    """Raised when the cleaned AI exposure data fails validation."""


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
                .replace("%", "")
            )
        except ValueError:
            return None

    return float(value)


def extract_ai_exposure(path: Path = RAW_FILE) -> pd.DataFrame:
    """Read the Occupation sheet from the source workbook."""
    if not path.exists():
        raise FileNotFoundError(
            f"Gen AI data pack not found at {path}. "
            "Place the downloaded file in datasets/ without renaming it."
        )

    df = pd.read_excel(
        path,
        sheet_name=SHEET_NAME,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype=object,
    )

    log.info(
        "Extracted %d rows from sheet %r",
        len(df),
        SHEET_NAME,
    )

    return df


def transform_ai_exposure(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the occupation-level AI exposure fields used by Telosia."""
    missing_cols = [
        c
        for c in FIELD_MAP
        if c not in df.columns
    ]

    if missing_cols:
        raise AiExposureValidationError(
            f"Sheet is missing expected columns: {missing_cols}. "
            "The publisher may have changed the workbook layout."
        )

    work = df[
        [
            CODE_COLUMN,
            TITLE_COLUMN,
            *FIELD_MAP,
        ]
    ].copy()

    work = work.rename(
        columns={
            CODE_COLUMN: "occupation_code",
            TITLE_COLUMN: "occupation_title",
            **FIELD_MAP,
        }
    )

    work["occupation_code"] = (
        work["occupation_code"]
        .astype(str)
        .str.strip()
    )

    # Remove the footnote row and anything without a valid 4-digit code
    before = len(work)

    work = work[
        work["occupation_code"]
        .str.match(r"^\d{4}$")
    ]

    if before != len(work):
        log.info(
            "Removed %d non-occupation row(s), including the source footnote",
            before - len(work),
        )

    work["anzsco_level"] = (
        work["occupation_code"]
        .str.len()
    )

    for column in FIELD_MAP.values():
        if column == "occupation_matrix_group":
            work[column] = (
                work[column]
                .astype(str)
                .str.strip()
            )
            continue

        work[column] = work[column].map(
            clean_numeric
        )

    result = (
        work[OUTPUT_COLUMNS]
        .sort_values("occupation_code")
        .reset_index(drop=True)
    )

    for column in SCORE_FIELDS + ["rate_of_skill_change"]:
        n_missing = int(
            result[column]
            .isna()
            .sum()
        )

        if n_missing:
            log.info(
                "  %s: %d of %d not published",
                column,
                n_missing,
                len(result),
            )

    log.info(
        "Transformed to %d occupations",
        len(result),
    )

    return result


def validate_ai_exposure(df: pd.DataFrame) -> None:
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
        "Validating AI exposure dataset"
    )

    check(
        f"occupation count == {EXPECTED_OCCUPATIONS}",
        len(df) == EXPECTED_OCCUPATIONS,
        f"got {len(df)}",
    )

    check(
        "occupation_code is unique",
        df["occupation_code"].is_unique,
    )

    check(
        "every code matches ^\\d{4}$",
        df["occupation_code"]
        .str.match(r"^\d{4}$")
        .all(),
    )

    check(
        "codes stored as strings",
        df["occupation_code"]
        .map(type)
        .eq(str)
        .all(),
    )

    check(
        "anzsco_level == 4",
        (
            df["anzsco_level"]
            == TARGET_ANZSCO_LEVEL
        ).all(),
    )

    check(
        "occupation_title populated",
        df["occupation_title"]
        .notna()
        .all(),
    )

    for column in SCORE_FIELDS:
        values = df[
            column
        ].dropna()

        check(
            f"{column} within 0 to 1",
            bool(
                values
                .between(0, 1)
                .all()
            ),
            (
                f"range {values.min()}..{values.max()}"
                if not values.empty
                else "no data"
            ),
        )

    check(
        "automation_exposure fully published",
        df["automation_exposure"]
        .notna()
        .all(),
        f"{int(df['automation_exposure'].isna().sum())} missing",
    )

    check(
        "augmentation_exposure fully published",
        df["augmentation_exposure"]
        .notna()
        .all(),
        f"{int(df['augmentation_exposure'].isna().sum())} missing",
    )

    # Zero is valid for standard deviation, so only check the exposure scores
    exposure_zeros = int(
        (
            df[
                [
                    "automation_exposure",
                    "augmentation_exposure",
                ]
            ]
            == 0
        )
        .sum()
        .sum()
    )

    check(
        "no exposure score was filled with zero",
        exposure_zeros == 0,
        f"{exposure_zeros} exact zeros in the exposure scores",
    )

    skill = df[
        "rate_of_skill_change"
    ].dropna()

    check(
        "rate_of_skill_change is non-negative where present",
        bool(
            (
                skill >= 0
            ).all()
        ),
    )

    check(
        "occupation_matrix_group populated",
        df["occupation_matrix_group"]
        .notna()
        .all(),
    )

    if failures:
        raise AiExposureValidationError(
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

    clean = transform_ai_exposure(
        extract_ai_exposure()
    )

    validate_ai_exposure(clean)

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