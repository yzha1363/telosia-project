import logging
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = (
    ROOT
    / "datasets"
    / "Workers Compensation Injury Frequency Rate detailed data file.xlsx"
)

OUTPUT_FILE = ROOT / "data" / "processed" / "wcifr_clean.csv"

SHEET_NAME = "Table 2.2"
HEADER_ROW = 6

MEASURE_TYPE = "workers_compensation_injury_frequency_rate"
SUPPRESSION_MARKER = "NP"
PRELIMINARY_SUFFIX = "p"

TARGET_ANZSCO_LEVEL = 4

# These counts came from checking the original WCIFR workbook
EXPECTED_OCCUPATIONS = 359
EXPECTED_YEARS = 10
EXPECTED_ROWS = 3590
EXPECTED_SUPPRESSED = 84
EXPECTED_BLANK = 4
EXPECTED_NUMERIC = 3502
EXPECTED_PRELIMINARY_YEAR = "2023-24"

# "nfd" means not further defined
NFD_CODES = {"5910"}

CODE_TITLE_PATTERN = re.compile(r"^\s*(\d+)\s+(.*\S)\s*$")

OUTPUT_COLUMNS = [
    "occupation_code",
    "occupation_title",
    "anzsco_level",
    "financial_year",
    "measure_type",
    "frequency_rate",
    "is_suppressed",
    "is_preliminary",
]

log = logging.getLogger(__name__)


class WcifrValidationError(Exception):
    pass


def extract_wcifr(path: Path = RAW_FILE) -> pd.DataFrame:
    """Read the occupation time-series table from the WCIFR workbook."""

    if not path.exists():
        raise FileNotFoundError(f"WCIFR file not found: {path}")

    df = pd.read_excel(
        path,
        sheet_name=SHEET_NAME,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype=object,
    )

    # The first column contains both the ANZSCO code and occupation title
    df = df.rename(columns={df.columns[0]: "occupation_raw"})

    log.info(
        "Extracted %d rows and %d columns from %s",
        len(df),
        len(df.columns),
        SHEET_NAME,
    )

    return df


def _split_code_title(value: object) -> tuple[str | None, str | None]:
    """Split an occupation value into its code and title."""

    if not isinstance(value, str):
        return None, None

    match = CODE_TITLE_PATTERN.match(value)

    if not match:
        return None, None

    return match.group(1), match.group(2)


def _normalise_financial_year(
    column_name: object,
) -> tuple[str, bool]:
    """Remove the preliminary marker from financial years."""

    year = str(column_name).strip()
    is_preliminary = year.endswith(PRELIMINARY_SUFFIX)

    if is_preliminary:
        year = year[:-1]

    return year, is_preliminary


def _classify_value(
    value: object,
) -> tuple[float | None, bool]:
    """Clean a WCIFR value and identify whether it was suppressed."""

    if isinstance(value, str):
        value = value.strip()

        # NP means the publisher did not release the value
        if value.upper() == SUPPRESSION_MARKER:
            return None, True

        try:
            return float(value), False
        except ValueError as exc:
            raise WcifrValidationError(
                f"Unexpected WCIFR value: {value}"
            ) from exc

    # Blank cells stay as missing values rather than being changed to zero
    if value is None or pd.isna(value):
        return None, False

    return float(value), False


def _report_nfd_occupations(df: pd.DataFrame) -> None:
    nfd_rows = df[df["occupation_code"].isin(NFD_CODES)]

    for _, row in nfd_rows.iterrows():
        log.warning(
            "NFD occupation retained: %s %s",
            row["occupation_code"],
            row["occupation_title"],
        )


def transform_wcifr(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and reshape WCIFR data into occupation-year records."""

    work = df.copy()

    # Separate the ANZSCO code from the occupation title
    parsed = work["occupation_raw"].map(_split_code_title)

    work["occupation_code"] = [
        code for code, _ in parsed
    ]

    work["occupation_title"] = [
        title for _, title in parsed
    ]

    # Removes rows such as the Total row
    work = work[
        work["occupation_code"].notna()
    ].copy()

    work["anzsco_level"] = work["occupation_code"].str.len()

    level_counts = (
        work["anzsco_level"]
        .value_counts()
        .sort_index()
        .to_dict()
    )

    log.info("ANZSCO levels found: %s", level_counts)

    # Telosia uses ANZSCO 4-digit Unit Groups
    work = work[
        work["anzsco_level"] == TARGET_ANZSCO_LEVEL
    ].copy()

    log.info(
        "Retained %d 4-digit occupations",
        len(work),
    )

    _report_nfd_occupations(work)

    year_columns = [
        column
        for column in df.columns
        if column != "occupation_raw"
    ]

    # Change the dataset from one column per year to one row per year
    long_df = work.melt(
        id_vars=[
            "occupation_code",
            "occupation_title",
            "anzsco_level",
        ],
        value_vars=year_columns,
        var_name="financial_year_raw",
        value_name="value_raw",
    )

    year_info = {
        column: _normalise_financial_year(column)
        for column in year_columns
    }

    long_df["financial_year"] = (
        long_df["financial_year_raw"]
        .map(lambda x: year_info[x][0])
    )

    long_df["is_preliminary"] = (
        long_df["financial_year_raw"]
        .map(lambda x: year_info[x][1])
    )

    # Clean numeric, suppressed and missing WCIFR values
    classified = long_df["value_raw"].map(_classify_value)

    long_df["frequency_rate"] = [
        rate for rate, _ in classified
    ]

    long_df["is_suppressed"] = [
        suppressed for _, suppressed in classified
    ]

    long_df["measure_type"] = MEASURE_TYPE

    clean_df = (
        long_df[OUTPUT_COLUMNS]
        .sort_values(
            ["occupation_code", "financial_year"]
        )
        .reset_index(drop=True)
    )

    log.info(
        "Transformed dataset contains %d rows",
        len(clean_df),
    )

    return clean_df


def validate_wcifr(df: pd.DataFrame) -> None:
    """Check that the cleaned WCIFR data has the expected structure."""

    errors = []

    def check(condition: bool, message: str) -> None:
        if condition:
            log.info("PASS: %s", message)
        else:
            log.error("FAIL: %s", message)
            errors.append(message)

    # Basic size checks
    check(
        len(df) == EXPECTED_ROWS,
        f"Expected {EXPECTED_ROWS} rows",
    )

    check(
        df["occupation_code"].nunique() == EXPECTED_OCCUPATIONS,
        f"Expected {EXPECTED_OCCUPATIONS} occupations",
    )

    check(
        df["financial_year"].nunique() == EXPECTED_YEARS,
        f"Expected {EXPECTED_YEARS} financial years",
    )

    # Check occupation codes
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
        (df["anzsco_level"] == TARGET_ANZSCO_LEVEL).all(),
        "ANZSCO level should be 4",
    )

    # Each occupation should only have one row for each year
    duplicates = df.duplicated(
        ["occupation_code", "financial_year"]
    )

    check(
        not duplicates.any(),
        "Occupation/year combinations should be unique",
    )

    # Check injury frequency values
    numeric = df["frequency_rate"].dropna()

    check(
        (numeric >= 0).all(),
        "Frequency rates should not be negative",
    )

    check(
        len(numeric) == EXPECTED_NUMERIC,
        f"Expected {EXPECTED_NUMERIC} numeric values",
    )

    # Check publisher-suppressed values
    suppressed = df[df["is_suppressed"]]

    check(
        len(suppressed) == EXPECTED_SUPPRESSED,
        f"Expected {EXPECTED_SUPPRESSED} suppressed values",
    )

    check(
        suppressed["frequency_rate"].isna().all(),
        "Suppressed values should have a null frequency rate",
    )

    # Check genuinely blank values separately from suppressed values
    blanks = df[
        df["frequency_rate"].isna()
        & ~df["is_suppressed"]
    ]

    check(
        len(blanks) == EXPECTED_BLANK,
        f"Expected {EXPECTED_BLANK} blank values",
    )

    check(
        len(numeric) + len(suppressed) + len(blanks) == len(df),
        "All rows should be numeric, suppressed or blank",
    )

    # 2023-24 is the only preliminary year in this release
    preliminary_years = set(
        df.loc[
            df["is_preliminary"],
            "financial_year",
        ]
    )

    check(
        preliminary_years == {EXPECTED_PRELIMINARY_YEAR},
        "Only 2023-24 should be preliminary",
    )

    check(
        df["financial_year"]
        .str.fullmatch(r"\d{4}-\d{2}")
        .all(),
        "Financial years should use YYYY-YY format",
    )

    check(
        set(df["measure_type"]) == {MEASURE_TYPE},
        "Measure type should be consistent",
    )

    if errors:
        raise WcifrValidationError(
            "WCIFR validation failed:\n- "
            + "\n- ".join(errors)
        )

    log.info("WCIFR validation completed successfully")


def main(write_csv: bool = True) -> pd.DataFrame:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info("Reading WCIFR dataset")

    # Extract the original workbook data
    raw_df = extract_wcifr()

    # Clean and reshape it
    clean_df = transform_wcifr(raw_df)

    # Check the cleaned result before saving
    validate_wcifr(clean_df)

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
            "Saved cleaned data to %s",
            OUTPUT_FILE,
        )

    return clean_df


if __name__ == "__main__":
    main()
    