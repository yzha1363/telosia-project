import logging
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = (
    ROOT
    / "datasets"
    / "ANZSCO Occupation data - February 2026.xlsx"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "processed"
    / "occupation_profiles_clean.csv"
)

OVERVIEW_SHEET = "Table_1"
EDUCATION_SHEET = "Table_8"

HEADER_ROW = 6

CODE_COLUMN = "ANZSCO Code"
TITLE_COLUMN = "Occupation"

TARGET_ANZSCO_LEVEL = 4

MISSING_TOKENS = {
    "N/A",
    "NA",
    "NP",
    "-",
    "",
}

OVERVIEW_FIELDS = {
    "Employed": "employed",
    "Part-time share (%)": "part_time_share_pct",
    "Female share (%)": "female_share_pct",
    "Median weekly earnings ($)": "median_weekly_earnings",
    "Median age": "median_age",
    "Annual employment growth": "annual_employment_growth",
}

EDUCATION_FIELDS = {
    "Post Graduate/ Graduate Diploma or Graduate Certificate \n(%)":
        "postgrad_share_pct",

    "Bachelor degree\n(%)":
        "bachelor_share_pct",

    "Advanced Diploma/ Diploma \n(%)":
        "diploma_share_pct",

    "Certificate III/ IV \n(%)":
        "certificate_share_pct",

    "Year 12\n (%)":
        "year12_share_pct",

    "Year 11 \n(%)":
        "year11_share_pct",

    "Year 10 and below \n(%)":
        "year10_or_below_share_pct",
}

PERCENTAGE_FIELDS = [
    "female_share_pct",
    "part_time_share_pct",
    *EDUCATION_FIELDS.values(),
]

EXPECTED_TOTAL_ROWS = 1236
EXPECTED_4DIGIT = 358
EXPECTED_6DIGIT = 878

OUTPUT_COLUMNS = [
    "occupation_code",
    "occupation_title",
    "anzsco_level",
    "employed",
    "female_share_pct",
    "part_time_share_pct",
    "median_age",
    "median_weekly_earnings",
    "annual_employment_growth",
    "postgrad_share_pct",
    "bachelor_share_pct",
    "diploma_share_pct",
    "certificate_share_pct",
    "year12_share_pct",
    "year11_share_pct",
    "year10_or_below_share_pct",
]

log = logging.getLogger(__name__)


class ProfilesValidationError(Exception):
    pass


def clean_numeric(value):
    """Convert workbook values to numbers while keeping missing values null."""

    if value is None:
        return None

    if isinstance(value, float) and pd.isna(value):
        return None

    if isinstance(value, str):
        text = value.strip()

        if text.upper() in MISSING_TOKENS:
            return None

        text = (
            text
            .replace(",", "")
            .replace("$", "")
            .replace("%", "")
        )

        try:
            return float(text)
        except ValueError:
            return None

    return float(value)


def extract_profiles(
    path: Path = RAW_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the workforce overview and education sheets."""

    if not path.exists():
        raise FileNotFoundError(
            f"JSA occupation workbook not found: {path}"
        )

    overview = pd.read_excel(
        path,
        sheet_name=OVERVIEW_SHEET,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype={CODE_COLUMN: str},
    )

    education = pd.read_excel(
        path,
        sheet_name=EDUCATION_SHEET,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype={CODE_COLUMN: str},
    )

    log.info(
        "Extracted %d overview rows",
        len(overview),
    )

    log.info(
        "Extracted %d education rows",
        len(education),
    )

    return overview, education


def prepare_sheet(
    df: pd.DataFrame,
    fields: dict[str, str],
    sheet_name: str,
) -> pd.DataFrame:
    """Keep only the fields needed by Telosia and clean their values."""

    missing_columns = [
        column
        for column in fields
        if column not in df.columns
    ]

    if missing_columns:
        raise ProfilesValidationError(
            f"{sheet_name} is missing columns: "
            f"{missing_columns}"
        )

    work = df[
        [
            CODE_COLUMN,
            TITLE_COLUMN,
            *fields.keys(),
        ]
    ].copy()

    work = work.rename(
        columns={
            CODE_COLUMN: "occupation_code",
            TITLE_COLUMN: "occupation_title",
            **fields,
        }
    )

    work["occupation_code"] = (
        work["occupation_code"]
        .astype(str)
        .str.strip()
    )

    # Remove rows that do not contain a numeric ANZSCO code
    work = work[
        work["occupation_code"]
        .str.fullmatch(r"\d+")
    ].copy()

    for column in fields.values():
        work[column] = (
            work[column]
            .map(clean_numeric)
        )

    return work


def transform_profiles(
    overview: pd.DataFrame,
    education: pd.DataFrame,
) -> pd.DataFrame:
    """Clean the two sheets and keep 4-digit ANZSCO Unit Groups."""

    overview_clean = prepare_sheet(
        overview,
        OVERVIEW_FIELDS,
        OVERVIEW_SHEET,
    )

    education_clean = prepare_sheet(
        education,
        EDUCATION_FIELDS,
        EDUCATION_SHEET,
    )

    overview_levels = (
        overview_clean["occupation_code"]
        .str.len()
        .value_counts()
        .sort_index()
        .to_dict()
    )

    log.info(
        "ANZSCO code lengths found: %s",
        overview_levels,
    )

    if len(overview_clean) != EXPECTED_TOTAL_ROWS:
        raise ProfilesValidationError(
            "Unexpected number of occupation rows: "
            f"{len(overview_clean)}"
        )

    four_digit_count = int(
        (
            overview_clean["occupation_code"].str.len()
            == TARGET_ANZSCO_LEVEL
        ).sum()
    )

    six_digit_count = int(
        (
            overview_clean["occupation_code"].str.len()
            == 6
        ).sum()
    )

    if four_digit_count != EXPECTED_4DIGIT:
        raise ProfilesValidationError(
            "Unexpected number of 4-digit occupations: "
            f"{four_digit_count}"
        )

    if six_digit_count != EXPECTED_6DIGIT:
        raise ProfilesValidationError(
            "Unexpected number of 6-digit occupations: "
            f"{six_digit_count}"
        )

    # Telosia uses the common 4-digit Unit Group level
    overview_clean = overview_clean[
        overview_clean["occupation_code"].str.len()
        == TARGET_ANZSCO_LEVEL
    ].copy()

    education_clean = education_clean[
        education_clean["occupation_code"].str.len()
        == TARGET_ANZSCO_LEVEL
    ].copy()

    log.info(
        "Retained %d four-digit occupations",
        len(overview_clean),
    )

    # Join workforce measures with education characteristics
    merged = overview_clean.merge(
        education_clean.drop(
            columns=["occupation_title"]
        ),
        on="occupation_code",
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    unmatched = int(
        (merged["_merge"] != "both").sum()
    )

    log.info(
        "Occupations without matching education data: %d",
        unmatched,
    )

    if unmatched:
        raise ProfilesValidationError(
            f"{unmatched} occupations did not match education data"
        )

    merged = merged.drop(
        columns=["_merge"]
    )

    merged["anzsco_level"] = (
        merged["occupation_code"]
        .str.len()
    )

    clean_df = (
        merged[OUTPUT_COLUMNS]
        .sort_values("occupation_code")
        .reset_index(drop=True)
    )

    # Report missing values rather than replacing them with zero
    numeric_columns = [
        "employed",
        "female_share_pct",
        "part_time_share_pct",
        "median_age",
        "median_weekly_earnings",
        "annual_employment_growth",
        *EDUCATION_FIELDS.values(),
    ]

    for column in numeric_columns:
        missing = int(
            clean_df[column]
            .isna()
            .sum()
        )

        if missing:
            log.info(
                "%s: %d missing values",
                column,
                missing,
            )

    return clean_df


def validate_profiles(
    df: pd.DataFrame,
) -> None:
    """Check the cleaned occupation profile data."""

    errors = []

    def check(
        condition: bool,
        message: str,
    ) -> None:

        if condition:
            log.info(
                "PASS: %s",
                message,
            )

        else:
            log.error(
                "FAIL: %s",
                message,
            )

            errors.append(message)

    check(
        len(df) == EXPECTED_4DIGIT,
        f"Expected {EXPECTED_4DIGIT} occupations",
    )

    check(
        df["occupation_code"].is_unique,
        "Occupation codes should be unique",
    )

    check(
        df["occupation_code"]
        .str.fullmatch(r"\d{4}")
        .all(),
        "Occupation codes should be 4 digits",
    )

    check(
        df["occupation_code"]
        .map(type)
        .eq(str)
        .all(),
        "Occupation codes should be strings",
    )

    check(
        (
            df["anzsco_level"]
            == TARGET_ANZSCO_LEVEL
        ).all(),
        "ANZSCO level should be 4",
    )

    check(
        df["occupation_title"]
        .notna()
        .all(),
        "Occupation titles should be populated",
    )

    # Percentage fields should stay on their published 0-100 scale
    for column in PERCENTAGE_FIELDS:

        values = (
            df[column]
            .dropna()
        )

        check(
            values.between(
                0,
                100,
            ).all(),
            f"{column} should be between 0 and 100",
        )

    employed = (
        df["employed"]
        .dropna()
    )

    check(
        (employed >= 0).all(),
        "Employment should not be negative",
    )

    ages = (
        df["median_age"]
        .dropna()
    )

    check(
        ages.between(
            15,
            80,
        ).all(),
        "Median age should be between 15 and 80",
    )

    earnings = (
        df["median_weekly_earnings"]
        .dropna()
    )

    check(
        (earnings > 0).all(),
        "Median weekly earnings should be positive where available",
    )

    # Missing values must stay null instead of being converted to zero
    check(
        not (
            df["median_weekly_earnings"]
            .fillna(-1)
            .eq(0)
            .any()
        ),
        "Missing earnings should not be converted to zero",
    )

    # These seven education categories do not cover exactly 100% because
    # JSA does not include every qualification category in this table
    education = (
        df[
            list(
                EDUCATION_FIELDS.values()
            )
        ]
        .dropna()
    )

    if not education.empty:

        education_totals = (
            education
            .sum(axis=1)
        )

        check(
            education_totals
            .between(
                80,
                100.5,
            )
            .all(),
            "Education shares should form a plausible partial distribution",
        )

    if errors:
        raise ProfilesValidationError(
            "Occupation profiles validation failed:\n- "
            + "\n- ".join(errors)
        )

    log.info(
        "Occupation profiles validation completed successfully"
    )


def main(
    write_csv: bool = True,
) -> pd.DataFrame:

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info(
        "Reading JSA occupation profiles"
    )

    overview, education = extract_profiles()

    clean_df = transform_profiles(
        overview,
        education,
    )

    validate_profiles(
        clean_df
    )

    if write_csv:

        OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        clean_df.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        log.info(
            "Saved cleaned occupation profiles to %s",
            OUTPUT_FILE,
        )

    return clean_df


if __name__ == "__main__":
    main()