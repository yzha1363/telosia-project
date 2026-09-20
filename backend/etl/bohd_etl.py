import logging
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = (
    ROOT
    / "datasets"
    / "Beta Occupational Hazards Dataset_Dec2023.xlsx"
)

OUTPUT_FILE = ROOT / "data" / "processed" / "bohd_clean.csv"

DATA_SHEET = "BOHD Dataset"
EXCLUSIONS_SHEET = "Exclusions"

# The first row contains hazard categories and the second row has column names
CATEGORY_ROW = 0
HEADER_ROW = 1

CODE_COLUMN = "ANZSCO code"
TITLE_COLUMN = "Occupation title"

# These categories are not physical/work-context predictors
EXCLUDED_CATEGORIES = {
    "ABS employment data",
    "Workers' compensation claims data",
}

TARGET_ANZSCO_LEVEL = 4

SCORE_MIN = 0.0
SCORE_MAX = 100.0
SCORE_DECIMALS = 2

# Expected values found when inspecting the original workbook
EXPECTED_OCCUPATIONS = 318
EXPECTED_VARIABLES = 57
EXPECTED_ROWS = EXPECTED_OCCUPATIONS * EXPECTED_VARIABLES
EXPECTED_EXCLUSIONS = 40
EXPECTED_CATEGORIES = 13

OUTPUT_COLUMNS = [
    "occupation_code",
    "occupation_title",
    "anzsco_level",
    "hazard_category",
    "hazard_variable",
    "exposure_score",
]

log = logging.getLogger(__name__)


class BohdValidationError(Exception):
    pass


def _read_category_map(path: Path) -> dict[str, str]:
    """Match each hazard variable with its category."""

    banner = pd.read_excel(
        path,
        sheet_name=DATA_SHEET,
        header=None,
        skiprows=CATEGORY_ROW,
        nrows=2,
        engine="openpyxl",
    )

    # Category names are stored in merged cells, so fill them across the row
    categories = banner.iloc[0].ffill()
    variables = banner.iloc[1]

    category_map = {
        str(variable): str(category)
        for category, variable in zip(categories, variables)
        if pd.notna(variable) and pd.notna(category)
    }

    return category_map


def extract_bohd(
    path: Path = RAW_FILE,
) -> tuple[pd.DataFrame, dict[str, str], pd.DataFrame]:
    """Read the BOHD data and exclusions sheets."""

    if not path.exists():
        raise FileNotFoundError(
            f"BOHD workbook not found: {path}"
        )

    df = pd.read_excel(
        path,
        sheet_name=DATA_SHEET,
        header=HEADER_ROW,
        engine="openpyxl",
        dtype={CODE_COLUMN: str},
    )

    category_map = _read_category_map(path)

    exclusions = pd.read_excel(
        path,
        sheet_name=EXCLUSIONS_SHEET,
        header=2,
        engine="openpyxl",
        dtype={"ANZSCO code": str},
    )

    exclusions = exclusions[
        exclusions["ANZSCO code"].notna()
    ].copy()

    log.info(
        "Extracted %d occupations and %d columns",
        len(df),
        len(df.columns),
    )

    log.info(
        "Exclusions sheet contains %d occupations",
        len(exclusions),
    )

    return df, category_map, exclusions


def split_predictor_columns(
    category_map: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Separate hazard predictors from fields that should not be used."""

    safe_columns = []
    excluded_columns = []

    for variable, category in category_map.items():

        if variable in (CODE_COLUMN, TITLE_COLUMN):
            continue

        # Remove employment and workers' compensation outcome fields
        if any(
            category.startswith(excluded)
            for excluded in EXCLUDED_CATEGORIES
        ):
            excluded_columns.append(variable)

        else:
            safe_columns.append(variable)

    return safe_columns, excluded_columns


def transform_bohd(
    df: pd.DataFrame,
    category_map: dict[str, str],
    exclusions: pd.DataFrame,
) -> pd.DataFrame:
    """Clean BOHD and convert hazard columns into long format."""

    work = df.copy()

    work[CODE_COLUMN] = (
        work[CODE_COLUMN]
        .astype(str)
        .str.strip()
    )

    # Remove rows without an occupation code
    work = work[
        (work[CODE_COLUMN] != "nan")
        & work[CODE_COLUMN].notna()
    ].copy()

    safe_columns, excluded_columns = split_predictor_columns(
        category_map
    )

    log.info(
        "Removing %d non-predictor columns: %s",
        len(excluded_columns),
        excluded_columns,
    )

    log.info(
        "Keeping %d work-context variables",
        len(safe_columns),
    )

    # Check the ANZSCO level
    work["anzsco_level"] = (
        work[CODE_COLUMN]
        .str.len()
    )

    level_counts = (
        work["anzsco_level"]
        .value_counts()
        .sort_index()
        .to_dict()
    )

    log.info(
        "ANZSCO code lengths found: %s",
        level_counts,
    )

    # Telosia uses 4-digit ANZSCO Unit Groups
    work = work[
        work["anzsco_level"] == TARGET_ANZSCO_LEVEL
    ].copy()

    # Convert the 57 hazard columns into occupation-hazard rows
    long_df = work.melt(
        id_vars=[
            CODE_COLUMN,
            TITLE_COLUMN,
            "anzsco_level",
        ],
        value_vars=safe_columns,
        var_name="hazard_variable",
        value_name="exposure_score",
    )

    # Add the broader category for each hazard variable
    long_df["hazard_category"] = (
        long_df["hazard_variable"]
        .map(category_map)
    )

    # Convert exposure scores to numbers
    long_df["exposure_score"] = pd.to_numeric(
        long_df["exposure_score"],
        errors="coerce",
    )

    # Remove floating-point artefacts from the source
    long_df["exposure_score"] = (
        long_df["exposure_score"]
        .round(SCORE_DECIMALS)
    )

    long_df = long_df.rename(
        columns={
            CODE_COLUMN: "occupation_code",
            TITLE_COLUMN: "occupation_title",
        }
    )

    clean_df = (
        long_df[OUTPUT_COLUMNS]
        .sort_values(
            [
                "occupation_code",
                "hazard_category",
                "hazard_variable",
            ]
        )
        .reset_index(drop=True)
    )

    # Occupations listed as excluded should not appear with fake zero scores
    excluded_codes = set(
        exclusions["ANZSCO code"]
        .astype(str)
        .str.strip()
    )

    unexpected_codes = (
        excluded_codes
        & set(clean_df["occupation_code"])
    )

    if unexpected_codes:
        raise BohdValidationError(
            "Excluded occupations appeared in cleaned data: "
            f"{sorted(unexpected_codes)}"
        )

    log.info(
        "Confirmed %d excluded occupations are absent",
        len(excluded_codes),
    )

    log.info(
        "Transformed to %d rows (%d occupations x %d hazard variables)",
        len(clean_df),
        clean_df["occupation_code"].nunique(),
        clean_df["hazard_variable"].nunique(),
    )

    return clean_df


def validate_bohd(
    df: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> None:
    """Validate the cleaned BOHD dataset."""

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

    # Check the overall size
    check(
        len(df) == EXPECTED_ROWS,
        f"Expected {EXPECTED_ROWS} rows",
    )

    check(
        df["occupation_code"].nunique()
        == EXPECTED_OCCUPATIONS,
        f"Expected {EXPECTED_OCCUPATIONS} occupations",
    )

    check(
        df["hazard_variable"].nunique()
        == EXPECTED_VARIABLES,
        f"Expected {EXPECTED_VARIABLES} hazard variables",
    )

    check(
        df["hazard_category"].nunique()
        == EXPECTED_CATEGORIES,
        f"Expected {EXPECTED_CATEGORIES} hazard categories",
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
        (
            df["anzsco_level"]
            == TARGET_ANZSCO_LEVEL
        ).all(),
        "ANZSCO level should be 4",
    )

    # Each occupation should only have one row for each hazard
    duplicates = df.duplicated(
        [
            "occupation_code",
            "hazard_variable",
        ]
    )

    check(
        not duplicates.any(),
        "Occupation/hazard combinations should be unique",
    )

    # Every occupation should contain all 57 hazard variables
    variables_per_occupation = (
        df.groupby("occupation_code")
        ["hazard_variable"]
        .nunique()
    )

    check(
        (
            variables_per_occupation
            == EXPECTED_VARIABLES
        ).all(),
        "Every occupation should have all hazard variables",
    )

    # Check exposure scores
    check(
        df["exposure_score"].notna().all(),
        "Exposure scores should not be missing",
    )

    scores = df["exposure_score"].dropna()

    check(
        scores.between(
            SCORE_MIN,
            SCORE_MAX,
        ).all(),
        "Exposure scores should be between 0 and 100",
    )

    # Make sure compensation outcomes were not left in the predictors
    banned_variables = [
        variable
        for variable in df["hazard_variable"].unique()
        if any(
            banned in variable.lower()
            for banned in (
                "claim",
                "incidence rate",
                "frequency rate",
                "employment (",
            )
        )
    ]

    check(
        not banned_variables,
        "Compensation and employment outcome fields should be removed",
    )

    # Check the publisher's exclusion list
    check(
        len(exclusions) == EXPECTED_EXCLUSIONS,
        f"Expected {EXPECTED_EXCLUSIONS} excluded occupations",
    )

    excluded_codes = set(
        exclusions["ANZSCO code"]
        .astype(str)
        .str.strip()
    )

    check(
        not (
            excluded_codes
            & set(df["occupation_code"])
        ),
        "Excluded occupations should not appear in cleaned data",
    )

    if errors:
        raise BohdValidationError(
            "BOHD validation failed:\n- "
            + "\n- ".join(errors)
        )

    log.info(
        "BOHD validation completed successfully"
    )


def main(
    write_csv: bool = True,
) -> pd.DataFrame:

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info(
        "Reading BOHD dataset"
    )

    # Extract the workbook data
    raw_df, category_map, exclusions = extract_bohd()

    # Clean and reshape the data
    clean_df = transform_bohd(
        raw_df,
        category_map,
        exclusions,
    )

    # Check the cleaned result
    validate_bohd(
        clean_df,
        exclusions,
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
            "Saved cleaned data to %s",
            OUTPUT_FILE,
        )

    return clean_df


if __name__ == "__main__":
    main()