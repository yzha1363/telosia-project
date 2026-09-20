import logging
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = ROOT / "datasets" / "occupation_flows.xlsx"
OUTPUT_FILE = ROOT / "data" / "processed" / "mobility_clean.csv"

SHEET_NAME = "Occupation Flows"

COL_YEAR = "Financial year"
COL_ORIGIN = "Previous year occupation"
COL_DESTINATION = "Recent year occupation"
COL_COUNT = "Count"
COL_ORIGIN_TITLE = "Previous year occupation title"
COL_DESTINATION_TITLE = "Recent year occupation title"

# These values do not represent actual occupations
SENTINEL_CODES = {
    "UNKNOWN",
    "NO_ITR",
    "NULL",
}

SOURCE_CODE_LENGTH = 6
TARGET_ANZSCO_LEVEL = 4

# Values found when inspecting the original workbook
EXPECTED_AGGREGATED_ROWS = 125371
EXPECTED_YEARS = 10
EXPECTED_COUNT_SUM = 95719060

OUTPUT_COLUMNS = [
    "financial_year",
    "source_occupation_code",
    "source_occupation_title",
    "destination_occupation_code",
    "destination_occupation_title",
    "worker_count",
    "is_self_transition",
    "source_rows_merged",
]

log = logging.getLogger(__name__)


class MobilityValidationError(Exception):
    pass


def normalise_financial_year(value: str) -> str:
    """Convert 2020_2021 into 2020-21."""

    text = str(value).strip()
    parts = text.split("_")

    if len(parts) != 2:
        raise MobilityValidationError(
            f"Unexpected financial year: {value}"
        )

    if not all(part.isdigit() for part in parts):
        raise MobilityValidationError(
            f"Unexpected financial year: {value}"
        )

    return f"{parts[0]}-{parts[1][-2:]}"


def extract_mobility(
    path: Path = RAW_FILE,
) -> pd.DataFrame:
    """Read the JSA occupation flows workbook."""

    if not path.exists():
        raise FileNotFoundError(
            f"Occupation flows file not found: {path}"
        )

    df = pd.read_excel(
        path,
        sheet_name=SHEET_NAME,
        engine="openpyxl",
        dtype={
            COL_ORIGIN: str,
            COL_DESTINATION: str,
            COL_YEAR: str,
        },
    )

    log.info(
        "Extracted %d rows from %s",
        len(df),
        SHEET_NAME,
    )

    return df


def remove_sentinels(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Remove rows that do not contain real occupations."""

    origin = (
        df[COL_ORIGIN]
        .astype(str)
        .str.strip()
    )

    destination = (
        df[COL_DESTINATION]
        .astype(str)
        .str.strip()
    )

    invalid_rows = (
        origin.isin(SENTINEL_CODES)
        | destination.isin(SENTINEL_CODES)
    )

    for code in sorted(SENTINEL_CODES):

        count = int(
            (
                origin.eq(code)
                | destination.eq(code)
            ).sum()
        )

        if count:
            log.info(
                "Removing %d rows containing %s",
                count,
                code,
            )

    clean = df[~invalid_rows].copy()

    log.info(
        "Removed %d sentinel rows, %d usable rows remain",
        int(invalid_rows.sum()),
        len(clean),
    )

    return clean


def _build_unit_group_titles(
    df: pd.DataFrame,
) -> dict[str, str]:
    """
    Create a temporary readable title for each 4-digit group.

    The mobility source only provides 6-digit titles, so the title from the
    largest contributing 6-digit occupation is used for now. Later this can
    be replaced with the official 4-digit title from JSA occupation profiles.
    """

    title_frames = []

    for code_column, title_column in (
        (COL_ORIGIN, COL_ORIGIN_TITLE),
        (COL_DESTINATION, COL_DESTINATION_TITLE),
    ):

        part = df[
            [
                code_column,
                title_column,
                "worker_count",
            ]
        ].copy()

        part.columns = [
            "code6",
            "title",
            "worker_count",
        ]

        title_frames.append(part)

    combined = pd.concat(
        title_frames,
        ignore_index=True,
    )

    combined["code4"] = (
        combined["code6"]
        .str[:TARGET_ANZSCO_LEVEL]
    )

    title_totals = (
        combined
        .groupby(
            ["code4", "title"],
            as_index=False,
        )["worker_count"]
        .sum()
        .sort_values(
            "worker_count",
            ascending=False,
        )
    )

    titles = (
        title_totals
        .drop_duplicates("code4")
        .set_index("code4")["title"]
        .to_dict()
    )

    return titles


def transform_mobility(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Clean occupation transitions and roll them up to 4-digit ANZSCO."""

    work = df.copy()

    work[COL_ORIGIN] = (
        work[COL_ORIGIN]
        .astype(str)
        .str.strip()
    )

    work[COL_DESTINATION] = (
        work[COL_DESTINATION]
        .astype(str)
        .str.strip()
    )

    # Remove UNKNOWN, NO_ITR and other non-occupation values
    work = remove_sentinels(work)

    # Remaining occupation codes should all be 6-digit ANZSCO
    invalid_codes = work[
        ~work[COL_ORIGIN].str.fullmatch(
            rf"\d{{{SOURCE_CODE_LENGTH}}}"
        )
        |
        ~work[COL_DESTINATION].str.fullmatch(
            rf"\d{{{SOURCE_CODE_LENGTH}}}"
        )
    ]

    if not invalid_codes.empty:
        raise MobilityValidationError(
            f"{len(invalid_codes)} rows contain invalid occupation codes"
        )

    # Clean financial year
    work["financial_year"] = (
        work[COL_YEAR]
        .map(normalise_financial_year)
    )

    # Worker count must remain numeric
    work["worker_count"] = pd.to_numeric(
        work[COL_COUNT],
        errors="raise",
    )

    # Roll 6-digit occupations up to 4-digit Unit Groups
    work["source_occupation_code"] = (
        work[COL_ORIGIN]
        .str[:TARGET_ANZSCO_LEVEL]
    )

    work["destination_occupation_code"] = (
        work[COL_DESTINATION]
        .str[:TARGET_ANZSCO_LEVEL]
    )

    worker_count_before = int(
        work["worker_count"].sum()
    )

    rows_before = len(work)

    # Several 6-digit transitions can become the same 4-digit transition.
    # Their worker counts therefore need to be summed.
    grouped = (
        work
        .groupby(
            [
                "financial_year",
                "source_occupation_code",
                "destination_occupation_code",
            ],
            as_index=False,
        )
        .agg(
            worker_count=(
                "worker_count",
                "sum",
            ),
            source_rows_merged=(
                "worker_count",
                "size",
            ),
        )
    )

    log.info(
        "Aggregated %d source rows into %d occupation transitions",
        rows_before,
        len(grouped),
    )

    worker_count_after = int(
        grouped["worker_count"].sum()
    )

    # Make sure aggregation did not lose any workers
    if worker_count_before != worker_count_after:
        raise MobilityValidationError(
            "Worker counts changed during aggregation: "
            f"{worker_count_before} before, "
            f"{worker_count_after} after"
        )

    log.info(
        "Worker count preserved after aggregation: %d",
        worker_count_after,
    )

    # Temporary readable titles until the profile ETL supplies official
    # 4-digit occupation titles
    titles = _build_unit_group_titles(work)

    grouped["source_occupation_title"] = (
        grouped["source_occupation_code"]
        .map(titles)
    )

    grouped["destination_occupation_title"] = (
        grouped["destination_occupation_code"]
        .map(titles)
    )

    # A transition can occur between two different 6-digit jobs that belong
    # to the same 4-digit Unit Group
    grouped["is_self_transition"] = (
        grouped["source_occupation_code"]
        == grouped["destination_occupation_code"]
    )

    log.info(
        "Found %d self-transition rows",
        int(
            grouped["is_self_transition"].sum()
        ),
    )

    clean_df = (
        grouped[OUTPUT_COLUMNS]
        .sort_values(
            [
                "financial_year",
                "source_occupation_code",
                "destination_occupation_code",
            ]
        )
        .reset_index(drop=True)
    )

    log.info(
        "Transformed mobility dataset contains %d rows",
        len(clean_df),
    )

    return clean_df


def validate_mobility(
    df: pd.DataFrame,
) -> None:
    """Validate the cleaned mobility dataset."""

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

    # Check overall size
    check(
        len(df) == EXPECTED_AGGREGATED_ROWS,
        f"Expected {EXPECTED_AGGREGATED_ROWS} rows",
    )

    check(
        df["financial_year"].nunique()
        == EXPECTED_YEARS,
        f"Expected {EXPECTED_YEARS} financial years",
    )

    # Check financial year format
    check(
        df["financial_year"]
        .str.fullmatch(r"\d{4}-\d{2}")
        .all(),
        "Financial years should use YYYY-YY format",
    )

    # Check source occupation codes
    check(
        df["source_occupation_code"]
        .str.fullmatch(r"\d{4}")
        .all(),
        "Source occupation codes should be 4 digits",
    )

    check(
        df["source_occupation_code"]
        .map(type)
        .eq(str)
        .all(),
        "Source occupation codes should be strings",
    )

    # Check destination occupation codes
    check(
        df["destination_occupation_code"]
        .str.fullmatch(r"\d{4}")
        .all(),
        "Destination occupation codes should be 4 digits",
    )

    check(
        df["destination_occupation_code"]
        .map(type)
        .eq(str)
        .all(),
        "Destination occupation codes should be strings",
    )

    # Each year/origin/destination combination should be unique
    duplicates = df.duplicated(
        [
            "financial_year",
            "source_occupation_code",
            "destination_occupation_code",
        ]
    )

    check(
        not duplicates.any(),
        "Year/source/destination combinations should be unique",
    )

    # Worker counts should remain positive
    check(
        (df["worker_count"] >= 0).all(),
        "Worker counts should not be negative",
    )

    check(
        (df["worker_count"] > 0).all(),
        "Worker counts should not be zero",
    )

    # Check total worker count was preserved
    total_workers = int(
        df["worker_count"].sum()
    )

    check(
        total_workers == EXPECTED_COUNT_SUM,
        f"Expected total worker count of {EXPECTED_COUNT_SUM}",
    )

    # Sentinel values should be gone
    remaining_codes = (
        set(df["source_occupation_code"])
        | set(df["destination_occupation_code"])
    )

    check(
        not (
            remaining_codes
            & SENTINEL_CODES
        ),
        "Sentinel occupation codes should be removed",
    )

    check(
        (
            df["source_rows_merged"]
            >= 1
        ).all(),
        "Every row should record how many source rows were merged",
    )

    check(
        df["source_occupation_title"]
        .notna()
        .all(),
        "Source occupation titles should be populated",
    )

    check(
        df["destination_occupation_title"]
        .notna()
        .all(),
        "Destination occupation titles should be populated",
    )

    if errors:
        raise MobilityValidationError(
            "Mobility validation failed:\n- "
            + "\n- ".join(errors)
        )

    log.info(
        "Mobility validation completed successfully"
    )


def main(
    write_csv: bool = True,
) -> pd.DataFrame:

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info(
        "Reading occupation mobility dataset"
    )

    # Extract the original JSA flows
    raw_df = extract_mobility()

    # Clean, roll up and aggregate
    clean_df = transform_mobility(raw_df)

    # Validate the result
    validate_mobility(clean_df)

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
            "Saved cleaned mobility data to %s",
            OUTPUT_FILE,
        )

    return clean_df


if __name__ == "__main__":
    main()