"""
Clean Jobs and Skills Australia's NERO regional employment data.

The raw NERO file contains monthly employment estimates for
4-digit ANZSCO occupations across Australian SA4 regions.

For Telosia we keep:
- the latest employment estimate
- the estimate one year earlier
- the estimate five years earlier
- percentage changes over those periods

Outputs:
    data/processed/nero_region_clean.csv
    data/processed/nero_employment_clean.csv

Run:
    python -m etl.nero
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = ROOT / "datasets" / "2026-08_shiny_df.csv"

REGION_OUTPUT = (
    ROOT
    / "data"
    / "processed"
    / "nero_region_clean.csv"
)

EMPLOYMENT_OUTPUT = (
    ROOT
    / "data"
    / "processed"
    / "nero_employment_clean.csv"
)

CHUNK_SIZE = 250_000


EXPECTED_REGIONS = 88
EXPECTED_OCCUPATIONS = 355
EXPECTED_LATEST_ROWS = 31_240


REQUIRED_COLUMNS = [
    "state_name",
    "sa4_code",
    "sa4_name",
    "anzsco4_code",
    "anzsco4_name",
    "date",
    "nsc_emp",
]


class NeroValidationError(Exception):
    """Raised when cleaned NERO data fails validation."""


def get_available_dates(path):
    """Read the date column and find all available monthly periods."""

    dates = set()

    for chunk in pd.read_csv(
        path,
        usecols=["date"],
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        parsed = pd.to_datetime(
            chunk["date"],
            errors="coerce",
        )

        if parsed.isna().any():
            raise NeroValidationError(
                "Invalid dates were found in the NERO file."
            )

        dates.update(
            parsed.tolist()
        )

    if not dates:
        raise NeroValidationError(
            "No dates were found in the NERO file."
        )

    return sorted(dates)


def get_target_dates(dates):
    """Choose the latest, one-year and five-year dates."""

    latest_date = max(dates)

    one_year_date = (
        latest_date
        - pd.DateOffset(years=1)
    )

    five_year_date = (
        latest_date
        - pd.DateOffset(years=5)
    )

    if one_year_date not in dates:
        raise NeroValidationError(
            f"One-year comparison date missing: {one_year_date.date()}"
        )

    if five_year_date not in dates:
        raise NeroValidationError(
            f"Five-year comparison date missing: {five_year_date.date()}"
        )

    return (
        latest_date,
        one_year_date,
        five_year_date,
    )


def clean_chunk(chunk):
    """Clean only the NERO fields used by Telosia."""

    missing = (
        set(REQUIRED_COLUMNS)
        - set(chunk.columns)
    )

    if missing:
        raise NeroValidationError(
            "Missing required NERO columns: "
            + ", ".join(sorted(missing))
        )

    data = chunk[
        REQUIRED_COLUMNS
    ].copy()

    text_columns = [
        "state_name",
        "sa4_code",
        "sa4_name",
        "anzsco4_code",
        "anzsco4_name",
    ]

    for column in text_columns:
        data[column] = (
            data[column]
            .astype("string")
            .str.strip()
        )

    data["date"] = pd.to_datetime(
        data["date"],
        errors="coerce",
    )

    data["nsc_emp"] = pd.to_numeric(
        data["nsc_emp"],
        errors="coerce",
    )

    if data["date"].isna().any():
        raise NeroValidationError(
            "Invalid dates found in NERO."
        )

    if data["nsc_emp"].isna().any():
        raise NeroValidationError(
            "Missing or invalid employment values found in NERO."
        )

    if (
        ~data["sa4_code"]
        .str.fullmatch(r"\d{3}")
    ).any():
        raise NeroValidationError(
            "Invalid SA4 code found."
        )

    if (
        ~data["anzsco4_code"]
        .str.fullmatch(r"\d{4}")
    ).any():
        raise NeroValidationError(
            "Invalid ANZSCO 4-digit code found."
        )

    if (
        data["nsc_emp"] < 0
    ).any():
        raise NeroValidationError(
            "Negative employment estimate found."
        )

    return data


def read_target_periods(
    path,
    target_dates,
):
    """Read only the three monthly periods required by Telosia."""

    pieces = []

    for chunk in pd.read_csv(
        path,
        dtype={
            "state_name": str,
            "sa4_code": str,
            "sa4_name": str,
            "anzsco4_code": str,
            "anzsco4_name": str,
        },
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        chunk = clean_chunk(
            chunk
        )

        selected = chunk[
            chunk["date"].isin(
                target_dates
            )
        ]

        if not selected.empty:
            pieces.append(
                selected
            )

    if not pieces:
        raise NeroValidationError(
            "No rows found for selected NERO dates."
        )

    return pd.concat(
        pieces,
        ignore_index=True,
    )


def calculate_change(
    current,
    previous,
):
    """Calculate percentage change without dividing by zero."""

    result = pd.Series(
        pd.NA,
        index=current.index,
        dtype="Float64",
    )

    valid = (
        current.notna()
        & previous.notna()
        & (previous != 0)
    )

    result.loc[valid] = (
        (
            current.loc[valid]
            - previous.loc[valid]
        )
        / previous.loc[valid]
        * 100
    )

    return result.round(2)


def transform_nero(
    path=RAW_FILE,
):
    """Build the region table and regional employment snapshot."""

    if not path.exists():
        raise FileNotFoundError(
            f"NERO file not found: {path}"
        )

    dates = get_available_dates(
        path
    )

    (
        latest_date,
        one_year_date,
        five_year_date,
    ) = get_target_dates(
        dates
    )

    print(
        "Latest date:",
        latest_date.date(),
    )

    print(
        "One-year comparison:",
        one_year_date.date(),
    )

    print(
        "Five-year comparison:",
        five_year_date.date(),
    )

    data = read_target_periods(
        path,
        {
            latest_date,
            one_year_date,
            five_year_date,
        },
    )

    latest = data[
        data["date"] == latest_date
    ].copy()

    one_year = data[
        data["date"] == one_year_date
    ].copy()

    five_year = data[
        data["date"] == five_year_date
    ].copy()

    key = [
        "sa4_code",
        "anzsco4_code",
    ]

    if latest.duplicated(
        key
    ).any():
        raise NeroValidationError(
            "Duplicate occupation-region rows "
            "found in latest NERO period."
        )

    one_year = one_year[
        [
            "sa4_code",
            "anzsco4_code",
            "nsc_emp",
        ]
    ].rename(
        columns={
            "nsc_emp":
                "employment_1y_ago"
        }
    )

    five_year = five_year[
        [
            "sa4_code",
            "anzsco4_code",
            "nsc_emp",
        ]
    ].rename(
        columns={
            "nsc_emp":
                "employment_5y_ago"
        }
    )

    latest = latest.merge(
        one_year,
        on=key,
        how="left",
    )

    latest = latest.merge(
        five_year,
        on=key,
        how="left",
    )

    latest = latest.rename(
        columns={
            "anzsco4_code":
                "occupation_code",

            "anzsco4_name":
                "occupation_title",

            "date":
                "reference_date",

            "nsc_emp":
                "estimated_employment",
        }
    )

    latest[
        "one_year_reference_date"
    ] = one_year_date

    latest[
        "five_year_reference_date"
    ] = five_year_date

    latest[
        "one_year_change_pct"
    ] = calculate_change(
        latest[
            "estimated_employment"
        ],
        latest[
            "employment_1y_ago"
        ],
    )

    latest[
        "five_year_change_pct"
    ] = calculate_change(
        latest[
            "estimated_employment"
        ],
        latest[
            "employment_5y_ago"
        ],
    )

    regions = (
        latest[
            [
                "state_name",
                "sa4_code",
                "sa4_name",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "state_name",
                "sa4_code",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    employment = latest[
        [
            "state_name",
            "sa4_code",
            "sa4_name",
            "occupation_code",
            "occupation_title",
            "reference_date",
            "estimated_employment",
            "one_year_reference_date",
            "employment_1y_ago",
            "one_year_change_pct",
            "five_year_reference_date",
            "employment_5y_ago",
            "five_year_change_pct",
        ]
    ].copy()

    employment = (
        employment
        .sort_values(
            [
                "state_name",
                "sa4_code",
                "occupation_code",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    return (
        regions,
        employment,
    )


def validate_nero(
    regions,
    employment,
):
    """Check the cleaned NERO output against the August 2026 source."""

    if len(regions) != EXPECTED_REGIONS:
        raise NeroValidationError(
            "Expected "
            f"{EXPECTED_REGIONS} regions, "
            f"found {len(regions)}."
        )

    occupation_count = (
        employment[
            "occupation_code"
        ]
        .nunique()
    )

    if (
        occupation_count
        != EXPECTED_OCCUPATIONS
    ):
        raise NeroValidationError(
            "Expected "
            f"{EXPECTED_OCCUPATIONS} occupations, "
            f"found {occupation_count}."
        )

    if (
        len(employment)
        != EXPECTED_LATEST_ROWS
    ):
        raise NeroValidationError(
            "Expected "
            f"{EXPECTED_LATEST_ROWS} employment rows, "
            f"found {len(employment)}."
        )

    expected_grid = (
        EXPECTED_REGIONS
        * EXPECTED_OCCUPATIONS
    )

    if (
        len(employment)
        != expected_grid
    ):
        raise NeroValidationError(
            "NERO occupation-region grid "
            "is incomplete."
        )

    if regions[
        "sa4_code"
    ].duplicated().any():
        raise NeroValidationError(
            "Duplicate SA4 codes found."
        )

    if employment.duplicated(
        [
            "sa4_code",
            "occupation_code",
        ]
    ).any():
        raise NeroValidationError(
            "Duplicate occupation-region "
            "records found."
        )

    if employment[
        "estimated_employment"
    ].isna().any():
        raise NeroValidationError(
            "Latest employment contains NULL values."
        )

    if (
        employment[
            "estimated_employment"
        ] < 0
    ).any():
        raise NeroValidationError(
            "Negative employment estimates found."
        )

    print()
    print("NERO validation passed")
    print("----------------------")
    print(
        "Regions:",
        len(regions),
    )
    print(
        "Occupations:",
        occupation_count,
    )
    print(
        "Employment rows:",
        len(employment),
    )
    print(
        "Reference date:",
        employment[
            "reference_date"
        ].iloc[0].date(),
    )


def main():
    print(
        "Reading NERO regional employment data..."
    )

    regions, employment = (
        transform_nero()
    )

    validate_nero(
        regions,
        employment,
    )

    REGION_OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    regions.to_csv(
        REGION_OUTPUT,
        index=False,
    )

    employment.to_csv(
        EMPLOYMENT_OUTPUT,
        index=False,
    )

    print()
    print(
        "Saved:",
        REGION_OUTPUT,
    )

    print(
        "Saved:",
        EMPLOYMENT_OUTPUT,
    )


if __name__ == "__main__":
    main()