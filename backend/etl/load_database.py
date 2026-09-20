import logging
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from database.connection import engine


ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"

PROFILES_FILE = (
    PROCESSED
    / "occupation_profiles_clean.csv"
)

WCIFR_FILE = (
    PROCESSED
    / "wcifr_clean.csv"
)

BOHD_FILE = (
    PROCESSED
    / "bohd_clean.csv"
)

MOBILITY_FILE = (
    PROCESSED
    / "mobility_clean.csv"
)

ALIASES_FILE = (
    PROCESSED
    / "anzsco_alias_clean.csv"
)

PAY_GAP_FILE = (
    PROCESSED
    / "pay_gap_clean.csv"
)

AI_EXPOSURE_FILE = (
    PROCESSED
    / "ai_exposure_clean.csv"
)

DESCRIPTIONS_FILE = (
    PROCESSED
    / "occupation_descriptions_clean.csv"
)

TASKS_FILE = (
    PROCESSED
    / "occupation_tasks_clean.csv"
)

NDS_CATEGORY_FILE = (
    PROCESSED
    / "nds_category_clean.csv"
)

NDS_CLAIMS_FILE = (
    PROCESSED
    / "nds_claims_clean.csv"
)

NERO_REGION_FILE = (
    PROCESSED
    / "nero_region_clean.csv"
)

NERO_EMPLOYMENT_FILE = (
    PROCESSED
    / "nero_employment_clean.csv"
)

BATCH_SIZE = 5000


SOURCES = {
    "profiles": {
        "publisher": "Jobs and Skills Australia",
        "dataset_title":
            "ANZSCO Occupation data - February 2026",
        "dataset_url":
            "https://www.jobsandskills.gov.au/data/"
            "occupation-and-industry-profiles",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Jobs and Skills Australia, "
            "ANZSCO Occupation data, February 2026.",
        "update_frequency":
            "Approximately six-monthly",
        "plain_language_note":
            "Employment, female share, earnings, "
            "workforce characteristics and qualifications "
            "for Australian occupations.",
        # A point-in-time release, not a date range - the same
        # "February 2026" already named in dataset_title above, just in
        # a real DATE column too. Not derived from any loaded data
        # (nothing in occupation_profile/occupation_task carries its own
        # date), so this is the one place that date has to be typed out.
        "coverage_period_start": date(2026, 2, 1),
        "coverage_period_end": date(2026, 2, 1),
    },

    "wcifr": {
        "publisher": "Safe Work Australia",
        "dataset_title":
            "Workers' Compensation Injury Frequency Rate "
            "detailed data file",
        "dataset_url":
            "https://data.safeworkaustralia.gov.au/"
            "our-datasets/workers-compensation-data",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Safe Work Australia, Workers' Compensation "
            "Injury Frequency Rate.",
        "update_frequency": "Annual",
        "plain_language_note":
            "Lost time claims per million hours worked "
            "by occupation. This is all-worker data and "
            "is not sex-disaggregated.",
    },

    "bohd": {
        "publisher": "Safe Work Australia",
        "dataset_title":
            "Beta Occupational Hazards Dataset - December 2023",
        "dataset_url":
            "https://data.safeworkaustralia.gov.au/"
            "about-our-datasets/"
            "beta-occupational-hazards-dataset",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Safe Work Australia, "
            "Beta Occupational Hazards Dataset, "
            "December 2023.",
        "update_frequency":
            "Beta release, no scheduled update",
        "plain_language_note":
            "Occupation work-context exposure scores. "
            "Compensation outcome fields are excluded "
            "from Telosia predictors.",
        # Point-in-time release, same reasoning as "profiles" above -
        # hazard_exposure carries no date of its own to derive this from.
        "coverage_period_start": date(2023, 12, 1),
        "coverage_period_end": date(2023, 12, 1),
    },

    "mobility": {
        "publisher": "Jobs and Skills Australia",
        "dataset_title":
            "Data on Occupation Mobility - Occupation Flows",
        "dataset_url":
            "https://www.jobsandskills.gov.au/publications/"
            "data-occupation-mobility-unpacking-workers-movements",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Jobs and Skills Australia, "
            "Data on Occupation Mobility.",
        "update_frequency": "Periodic",
        "plain_language_note":
            "Observed occupation transitions. "
            "The dataset covers workers generally and "
            "does not support claims that women specifically "
            "made these transitions.",
    },

    "aliases": {
        "publisher": "Australian Bureau of Statistics",
        "dataset_title":
            "ANZSCO 2022 Index of Principal Titles, "
            "Alternative Titles and Specialisations",
        "dataset_url":
            "https://www.abs.gov.au/statistics/classifications/"
            "anzsco-australian-and-new-zealand-standard-"
            "classification-occupations/2022",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Australian Bureau of Statistics, "
            "ANZSCO 2022 Index of Principal Titles, "
            "Alternative Titles and Specialisations.",
        "update_frequency": "Updated with each ANZSCO revision",
        "plain_language_note":
            "Official alternative names and specialisations for "
            "each occupation, used so a plain-language search can "
            "match a job even when it's not called by its official "
            "title. Covers formal alternative titles, not informal "
            "slang - some everyday terms are not in this index.",
    },

    "pay_gap": {
        "publisher": "Jobs and Skills Australia",
        "dataset_title":
            "Occupational Gender Pay Gap Dashboard",
        "dataset_url":
            "https://www.jobsandskills.gov.au/research/studies/"
            "gender-economic-equality-study/"
            "occupational-gender-pay-gap",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Jobs and Skills Australia, "
            "Gender Economic Equality Study, 2025. "
            "(c) Commonwealth of Australia.",
        "update_frequency": "Periodic",
        "plain_language_note":
            "Female and male median annual income and the gender "
            "pay gap by occupation and age cohort. Published at "
            "ANZSCO 6-digit. Medians are not aggregated to 4-digit.",
    },

    "ai_exposure": {
        "publisher": "Jobs and Skills Australia",
        "dataset_title":
            "Generative AI Capacity Study - Interactive Tables "
            "Data Pack",
        "dataset_url":
            "https://www.jobsandskills.gov.au/research/studies/"
            "generative-artificial-intelligence-capacity-study",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Jobs and Skills Australia, "
            "Generative AI Capacity Study, 2025. "
            "(c) Commonwealth of Australia.",
        "update_frequency": "Periodic",
        "plain_language_note":
            "Automation and augmentation exposure scores per "
            "occupation. Automation exposure indicates potential "
            "for tasks to be performed by AI rather than a person. "
            "Not sex-disaggregated.",
    },

    "nds": {
        "publisher": "Safe Work Australia",
        "dataset_title":
            "National Dataset for Compensation Based Statistics "
            "detailed data file",
        "dataset_url":
            "https://data.safeworkaustralia.gov.au/"
            "about-our-datasets/workers-compensation-data",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Safe Work Australia, National Dataset for "
            "Compensation Based Statistics.",
        "update_frequency": "Annual",
        "plain_language_note":
            "National workers' compensation claim statistics "
            "published by industry and occupation group. "
            "Occupation figures are published at broader ANZSCO "
            "group levels rather than Telosia's 4-digit Unit Group.",
    },

    "nero": {
        "publisher": "Jobs and Skills Australia",
        "dataset_title":
            "Nowcast of Employment by Region and Occupation (NERO)",
        "dataset_url":
            "https://www.jobsandskills.gov.au/data/nero",
        "licence": "CC BY 4.0",
        "attribution_text":
            "Jobs and Skills Australia, "
            "Nowcast of Employment by Region and Occupation (NERO).",
        "update_frequency": "Monthly",
        "plain_language_note":
            "Monthly estimated employment by 4-digit ANZSCO occupation "
            "and SA4 region. These are employment estimates, not job "
            "vacancies. Regional estimates are based on where employed "
            "people live rather than where the business is located.",
    },
}


EXPECTED_COUNTS = {
    "occupation": 401,
    "occupation_profile": 358,
    "injury_frequency": 3590,
    "hazard_variable": 57,
    "hazard_exposure": 18126,
    "mobility_flow": 125371,
    "occupation_task": 3037,
    "nds_category": 186,
    "nds_claim_statistic": 9300,
    "occupation_nds_link": 401,
    "region": 88,
    "regional_employment": 31240,
    "ai_exposure": 357,
}


log = logging.getLogger(__name__)


class LoadError(Exception):
    pass


def optional_float(value):
    if value is None or pd.isna(value):
        return None

    return float(value)


def optional_text(value):
    if value is None or pd.isna(value):
        return None

    text_value = str(value).strip()

    if not text_value:
        return None

    return text_value


def to_bool(value):
    if isinstance(value, bool):
        return value

    if pd.isna(value):
        return False

    return (
        str(value)
        .strip()
        .lower()
        in {
            "true",
            "1",
            "yes",
        }
    )


def read_csv(path: Path, dtype=None):
    if not path.exists():
        raise FileNotFoundError(
            f"Cleaned dataset not found: {path}. "
            "Run the ETL scripts first."
        )

    return pd.read_csv(
        path,
        dtype=dtype,
    )


def execute_batches(
    connection,
    statement,
    rows,
):
    for start in range(
        0,
        len(rows),
        BATCH_SIZE,
    ):
        batch = rows[
            start:start + BATCH_SIZE
        ]

        connection.execute(
            statement,
            batch,
        )


def get_source_reference(
    connection,
    source_key,
):
    meta = SOURCES[source_key]

    # coverage_period_start/end are only set here for the sources with a
    # fixed, point-in-time release date already recorded in SOURCES (see
    # "profiles"/"bohd" above) - everything else's real coverage period
    # is derived from the data itself once it's loaded, in
    # update_coverage_periods() below, not guessed at here before a
    # single row exists.
    params = {
        **meta,
        "coverage_period_start": meta.get("coverage_period_start"),
        "coverage_period_end": meta.get("coverage_period_end"),
    }

    statement = text(
        """
        INSERT INTO telosia.source_reference (
            publisher,
            dataset_title,
            dataset_url,
            licence,
            attribution_text,
            retrieval_date,
            plain_language_note,
            update_frequency,
            coverage_period_start,
            coverage_period_end
        )
        VALUES (
            :publisher,
            :dataset_title,
            :dataset_url,
            :licence,
            :attribution_text,
            CURRENT_DATE,
            :plain_language_note,
            :update_frequency,
            :coverage_period_start,
            :coverage_period_end
        )
        ON CONFLICT (
            publisher,
            dataset_title
        )
        DO UPDATE SET
            dataset_url =
                EXCLUDED.dataset_url,

            licence =
                EXCLUDED.licence,

            attribution_text =
                EXCLUDED.attribution_text,

            retrieval_date =
                EXCLUDED.retrieval_date,

            plain_language_note =
                EXCLUDED.plain_language_note,

            update_frequency =
                EXCLUDED.update_frequency,

            coverage_period_start =
                COALESCE(EXCLUDED.coverage_period_start, telosia.source_reference.coverage_period_start),

            coverage_period_end =
                COALESCE(EXCLUDED.coverage_period_end, telosia.source_reference.coverage_period_end)

        RETURNING source_reference_id
        """
    )

    source_id = connection.execute(
        statement,
        params,
    ).scalar_one()

    log.info(
        "Registered source: %s",
        meta["dataset_title"],
    )

    return int(source_id)


def _financial_year_start(financial_year: str) -> date:
    """'2014-15' -> 1 July 2014, the first day of the Australian
    financial year that string names."""
    return date(int(financial_year[:4]), 7, 1)


def _financial_year_end(financial_year: str) -> date:
    """'2014-15' -> 30 June 2015, the last day of the Australian
    financial year that string names."""
    return date(int(financial_year[:4]) + 1, 6, 30)


def update_coverage_periods(connection, source_ids):
    """Fills in coverage_period_start/end for the sources whose real
    range can be read straight from the data that was just loaded in
    this same run, instead of typed out from memory of what the
    publisher's page says. Must run after load_wcifr/load_mobility/
    load_nds_claims/load_regional_employment, in the same transaction.

    Three sources are deliberately left alone here (and stay null,
    unless "profiles"/"bohd" set a fixed point-in-time date in SOURCES):
    pay_gap, ai_exposure and aliases carry no year or date column
    anywhere in what gets loaded from them, so there's nothing real to
    derive a period from - a guess at their collection window would be
    exactly the kind of unverified figure this project doesn't publish.
    """
    bounds = connection.execute(
        text(
            """
            SELECT
                (SELECT MIN(financial_year) FROM telosia.injury_frequency) AS wcifr_min,
                (SELECT MAX(financial_year) FROM telosia.injury_frequency) AS wcifr_max,
                (SELECT MIN(financial_year) FROM telosia.mobility_flow) AS mobility_min,
                (SELECT MAX(financial_year) FROM telosia.mobility_flow) AS mobility_max,
                (SELECT MIN(financial_year) FROM telosia.nds_claim_statistic) AS nds_min,
                (SELECT MAX(financial_year) FROM telosia.nds_claim_statistic) AS nds_max,
                (SELECT MIN(reference_date) FROM telosia.regional_employment) AS nero_min,
                (SELECT MAX(reference_date) FROM telosia.regional_employment) AS nero_max
            """
        )
    ).mappings().one()

    updates = [
        (
            source_ids["wcifr"],
            _financial_year_start(bounds["wcifr_min"]),
            _financial_year_end(bounds["wcifr_max"]),
        ),
        (
            source_ids["mobility"],
            _financial_year_start(bounds["mobility_min"]),
            _financial_year_end(bounds["mobility_max"]),
        ),
        (
            source_ids["nds"],
            _financial_year_start(bounds["nds_min"]),
            _financial_year_end(bounds["nds_max"]),
        ),
        # NERO is a monthly nowcast, not a multi-year series - every row
        # loaded shares the same single reference_date, so start and end
        # are the same real date, not a range.
        (source_ids["nero"], bounds["nero_min"], bounds["nero_max"]),
    ]

    for source_id, start, end in updates:
        connection.execute(
            text(
                """
                UPDATE telosia.source_reference
                SET
                    coverage_period_start = :start,
                    coverage_period_end = :end
                WHERE source_reference_id = :source_id
                """
            ),
            {"source_id": source_id, "start": start, "end": end},
        )

    log.info(
        "Updated coverage periods for %d sources from their loaded data",
        len(updates),
    )


def collect_occupation_codes(
    profiles,
    wcifr,
    bohd,
    mobility,
):
    log.info(
        "Building occupation universe"
    )

    profile_codes = set(
        profiles[
            "occupation_code"
        ].astype(str)
    )

    frames = [
        profiles[
            [
                "occupation_code",
                "occupation_title",
            ]
        ].assign(priority=0),

        wcifr[
            [
                "occupation_code",
                "occupation_title",
            ]
        ].assign(priority=1),

        bohd[
            [
                "occupation_code",
                "occupation_title",
            ]
        ].assign(priority=2),

        mobility.rename(
            columns={
                "source_occupation_code":
                    "occupation_code",

                "source_occupation_title":
                    "occupation_title",
            }
        )[
            [
                "occupation_code",
                "occupation_title",
            ]
        ].assign(priority=3),

        mobility.rename(
            columns={
                "destination_occupation_code":
                    "occupation_code",

                "destination_occupation_title":
                    "occupation_title",
            }
        )[
            [
                "occupation_code",
                "occupation_title",
            ]
        ].assign(priority=3),
    ]

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    combined = combined.dropna(
        subset=[
            "occupation_code",
            "occupation_title",
        ]
    )

    combined["occupation_code"] = (
        combined["occupation_code"]
        .astype(str)
        .str.strip()
    )

    combined["occupation_title"] = (
        combined["occupation_title"]
        .astype(str)
        .str.strip()
    )

    occupations = (
        combined
        .sort_values(
            [
                "occupation_code",
                "priority",
            ],
            kind="stable",
        )
        .drop_duplicates(
            "occupation_code",
            keep="first",
        )
        .drop(
            columns="priority"
        )
        .sort_values(
            "occupation_code"
        )
        .reset_index(
            drop=True
        )
    )

    occupations[
        "is_profile_occupation"
    ] = (
        occupations[
            "occupation_code"
        ].isin(profile_codes)
    )

    bad_codes = occupations[
        ~occupations[
            "occupation_code"
        ].str.fullmatch(
            r"\d{4}"
        )
    ]

    if not bad_codes.empty:
        raise LoadError(
            "Occupation universe contains "
            "non-4-digit codes: "
            f"{bad_codes['occupation_code'].tolist()[:10]}"
        )

    log.info(
        "Profiles contribute %d codes",
        profiles[
            "occupation_code"
        ].nunique(),
    )

    log.info(
        "WCIFR contributes %d codes",
        wcifr[
            "occupation_code"
        ].nunique(),
    )

    log.info(
        "BOHD contributes %d codes",
        bohd[
            "occupation_code"
        ].nunique(),
    )

    mobility_codes = (
        set(
            mobility[
                "source_occupation_code"
            ]
        )
        |
        set(
            mobility[
                "destination_occupation_code"
            ]
        )
    )

    log.info(
        "Mobility contributes %d codes",
        len(mobility_codes),
    )

    log.info(
        "Occupation universe contains %d codes",
        len(occupations),
    )

    log.info(
        "Profile-backed occupations: %d",
        int(
            occupations[
                "is_profile_occupation"
            ].sum()
        ),
    )

    log.info(
        "Source-only occupations: %d",
        int(
            (
                ~occupations[
                    "is_profile_occupation"
                ]
            ).sum()
        ),
    )

    if len(occupations) != 401:
        raise LoadError(
            "Expected 401 occupation codes "
            f"across all sources, found {len(occupations)}"
        )

    return occupations


def load_occupations(
    connection,
    occupations,
):
    log.info(
        "Loading occupations"
    )

    rows = []

    for row in occupations.itertuples(
        index=False
    ):
        rows.append(
            {
                "code":
                    str(
                        row.occupation_code
                    ),

                "title":
                    str(
                        row.occupation_title
                    ),

                "level":
                    4,

                "is_profile":
                    bool(
                        row.is_profile_occupation
                    ),
            }
        )

    statement = text(
        """
        INSERT INTO telosia.occupation (
            anzsco_code,
            occupation_title,
            anzsco_level,
            is_profile_occupation
        )
        VALUES (
            :code,
            :title,
            :level,
            :is_profile
        )
        ON CONFLICT (
            anzsco_code
        )
        DO UPDATE SET
            occupation_title =
                EXCLUDED.occupation_title,

            anzsco_level =
                EXCLUDED.anzsco_level,

            is_profile_occupation =
                EXCLUDED.is_profile_occupation,

            updated_at =
                CURRENT_TIMESTAMP
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    results = connection.execute(
        text(
            """
            SELECT
                anzsco_code,
                occupation_id
            FROM telosia.occupation
            """
        )
    ).all()

    occupation_map = {
        str(code): int(occupation_id)
        for code, occupation_id in results
    }

    log.info(
        "Loaded %d occupations",
        len(occupation_map),
    )

    return occupation_map


def resolve_occupation(
    code,
    occupation_map,
    dataset_name,
):
    occupation_id = (
        occupation_map.get(
            str(code)
        )
    )

    if occupation_id is None:
        raise LoadError(
            f"{dataset_name} references "
            f"occupation code {code}, "
            "but it is missing from the "
            "occupation table."
        )

    return occupation_id


def find_column(dataframe, names, dataset_name):
    for name in names:
        if name in dataframe.columns:
            return name

    raise LoadError(
        f"{dataset_name} is missing a required column. "
        f"Expected one of: {', '.join(names)}"
    )


# Occupation content must use 4-digit ANZSCO codes
def validate_occupation_codes(dataframe, dataset_name):
    if "occupation_code" not in dataframe.columns:
        raise LoadError(
            f"{dataset_name} is missing occupation_code."
        )

    codes = dataframe["occupation_code"].astype(str).str.strip()
    bad_codes = codes[~codes.str.fullmatch(r"\d{4}")]

    if not bad_codes.empty:
        raise LoadError(
            f"{dataset_name} contains invalid occupation codes: "
            f"{bad_codes.tolist()[:10]}"
        )


def load_descriptions(
    connection,
    descriptions,
    occupation_map,
):
    log.info("Loading occupation descriptions")

    validate_occupation_codes(
        descriptions,
        "Occupation descriptions",
    )

    description_column = find_column(
        descriptions,
        [
            "occupation_description",
            "description",
        ],
        "Occupation descriptions",
    )

    if len(descriptions) != 358:
        raise LoadError(
            "Expected 358 occupation descriptions, "
            f"found {len(descriptions)}"
        )

    if descriptions["occupation_code"].nunique() != 358:
        raise LoadError(
            "Occupation descriptions must contain "
            "358 unique occupation codes."
        )

    rows = []

    for row in descriptions[
        [
            "occupation_code",
            description_column,
        ]
    ].itertuples(index=False, name=None):
        code, description = row

        if pd.isna(description) or not str(description).strip():
            raise LoadError(
                f"Blank description found for occupation {code}."
            )

        rows.append(
            {
                "occupation_id":
                    resolve_occupation(
                        code,
                        occupation_map,
                        "Occupation descriptions",
                    ),
                "description":
                    str(description).strip(),
            }
        )

    # Clear old descriptions before loading the current cleaned values
    connection.execute(
        text(
            """
            UPDATE telosia.occupation
            SET occupation_description = NULL
            WHERE is_profile_occupation = TRUE
            """
        )
    )

    statement = text(
        """
        UPDATE telosia.occupation
        SET
            occupation_description = :description,
            updated_at = CURRENT_TIMESTAMP
        WHERE occupation_id = :occupation_id
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d occupation descriptions",
        len(rows),
    )


# Load the ordered task list for each occupation
def load_tasks(
    connection,
    tasks,
    occupation_map,
    source_id,
):
    log.info("Loading occupation tasks")

    validate_occupation_codes(
        tasks,
        "Occupation tasks",
    )

    task_column = find_column(
        tasks,
        [
            "task_text",
            "task",
        ],
        "Occupation tasks",
    )

    working = tasks.copy()

    working["occupation_code"] = (
        working["occupation_code"]
        .astype(str)
        .str.strip()
    )

    if len(working) != 3037:
        raise LoadError(
            "Expected 3037 occupation task rows, "
            f"found {len(working)}"
        )

    if working["occupation_code"].nunique() != 358:
        raise LoadError(
            "Expected task data for 358 occupations."
        )

    # Create task order from file order if it is not already present
    if "task_order" not in working.columns:
        working["task_order"] = (
            working
            .groupby(
                "occupation_code",
                sort=False,
            )
            .cumcount()
            + 1
        )
    else:
        working["task_order"] = pd.to_numeric(
            working["task_order"],
            errors="raise",
        ).astype(int)

    if (working["task_order"] < 1).any():
        raise LoadError(
            "task_order must start at 1."
        )

    duplicates = working.duplicated(
        subset=[
            "occupation_code",
            "task_order",
        ]
    )

    if duplicates.any():
        raise LoadError(
            "Duplicate task order found for an occupation."
        )

    rows = []

    for row in working[
        [
            "occupation_code",
            "task_order",
            task_column,
        ]
    ].itertuples(index=False, name=None):
        code, task_order, task_text = row

        if pd.isna(task_text) or not str(task_text).strip():
            raise LoadError(
                f"Blank task found for occupation {code}."
            )

        rows.append(
            {
                "occupation_id":
                    resolve_occupation(
                        code,
                        occupation_map,
                        "Occupation tasks",
                    ),
                "task_order": int(task_order),
                "task_text": str(task_text).strip(),
                "source_reference_id": source_id,
            }
        )

    # Replace tasks from this JSA source so stale rows are not kept
    connection.execute(
        text(
            """
            DELETE FROM telosia.occupation_task
            WHERE source_reference_id = :source_id
            """
        ),
        {
            "source_id": source_id,
        },
    )

    statement = text(
        """
        INSERT INTO telosia.occupation_task (
            occupation_id,
            task_order,
            task_text,
            source_reference_id
        )
        VALUES (
            :occupation_id,
            :task_order,
            :task_text,
            :source_reference_id
        )
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d occupation tasks",
        len(rows),
    )


def load_profiles(
    connection,
    profiles,
    occupation_map,
    source_id,
):
    log.info(
        "Loading occupation profiles"
    )

    numeric_fields = [
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

    rows = []

    for row in profiles.itertuples(
        index=False
    ):
        record = {
            "occupation_id":
                resolve_occupation(
                    row.occupation_code,
                    occupation_map,
                    "Occupation Profiles",
                ),

            "source_reference_id":
                source_id,
        }

        for field in numeric_fields:
            record[field] = (
                optional_float(
                    getattr(
                        row,
                        field,
                    )
                )
            )

        rows.append(record)

    columns = [
        "occupation_id",
        *numeric_fields,
        "source_reference_id",
    ]

    placeholders = ", ".join(
        f":{column}"
        for column in columns
    )

    updates = ",\n".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column != "occupation_id"
    )

    statement = text(
        f"""
        INSERT INTO telosia.occupation_profile (
            {", ".join(columns)}
        )
        VALUES (
            {placeholders}
        )
        ON CONFLICT (
            occupation_id
        )
        DO UPDATE SET
            {updates}
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d occupation profiles",
        len(rows),
    )


def load_wcifr(
    connection,
    wcifr,
    occupation_map,
    source_id,
):
    log.info(
        "Loading WCIFR"
    )

    rows = []

    for row in wcifr.itertuples(
        index=False
    ):
        rows.append(
            {
                "occupation_id":
                    resolve_occupation(
                        row.occupation_code,
                        occupation_map,
                        "WCIFR",
                    ),

                "financial_year":
                    str(
                        row.financial_year
                    ),

                "measure_type":
                    str(
                        row.measure_type
                    ),

                "frequency_rate":
                    optional_float(
                        row.frequency_rate
                    ),

                "is_suppressed":
                    to_bool(
                        row.is_suppressed
                    ),

                "is_preliminary":
                    to_bool(
                        row.is_preliminary
                    ),

                "source_reference_id":
                    source_id,
            }
        )

    contradictory = [
        row
        for row in rows
        if (
            row["is_suppressed"]
            and
            row["frequency_rate"]
            is not None
        )
    ]

    if contradictory:
        raise LoadError(
            f"{len(contradictory)} WCIFR rows "
            "are suppressed but also contain "
            "a frequency rate."
        )

    statement = text(
        """
        INSERT INTO telosia.injury_frequency (
            occupation_id,
            financial_year,
            measure_type,
            frequency_rate,
            is_suppressed,
            is_preliminary,
            source_reference_id
        )
        VALUES (
            :occupation_id,
            :financial_year,
            :measure_type,
            :frequency_rate,
            :is_suppressed,
            :is_preliminary,
            :source_reference_id
        )
        ON CONFLICT (
            occupation_id,
            financial_year,
            measure_type
        )
        DO UPDATE SET
            frequency_rate =
                EXCLUDED.frequency_rate,

            is_suppressed =
                EXCLUDED.is_suppressed,

            is_preliminary =
                EXCLUDED.is_preliminary,

            source_reference_id =
                EXCLUDED.source_reference_id
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    suppressed = sum(
        1
        for row in rows
        if row["is_suppressed"]
    )

    genuine_blanks = sum(
        1
        for row in rows
        if (
            row["frequency_rate"] is None
            and
            not row["is_suppressed"]
        )
    )

    log.info(
        "Loaded %d WCIFR rows",
        len(rows),
    )

    log.info(
        "WCIFR suppressed rows: %d",
        suppressed,
    )

    log.info(
        "WCIFR genuine blank rows: %d",
        genuine_blanks,
    )


def load_hazards(
    connection,
    bohd,
    occupation_map,
    source_id,
):
    log.info(
        "Loading BOHD hazard variables"
    )

    category_counts = (
        bohd
        .groupby(
            "hazard_variable"
        )[
            "hazard_category"
        ]
        .nunique()
    )

    conflicts = category_counts[
        category_counts > 1
    ]

    if not conflicts.empty:
        raise LoadError(
            "Some hazard variables map "
            "to more than one category: "
            f"{conflicts.index.tolist()}"
        )

    variables = (
        bohd[
            [
                "hazard_variable",
                "hazard_category",
            ]
        ]
        .drop_duplicates()
    )

    banned = [
        variable
        for variable
        in variables[
            "hazard_variable"
        ]
        if any(
            term in variable.lower()
            for term in (
                "claim",
                "incidence rate",
                "frequency rate",
            )
        )
    ]

    if banned:
        raise LoadError(
            "BOHD outcome variables would "
            "be loaded as predictors: "
            f"{banned}"
        )

    variable_rows = []

    for row in variables.itertuples(
        index=False
    ):
        variable_rows.append(
            {
                "hazard_variable":
                    str(
                        row.hazard_variable
                    ),

                "hazard_category":
                    str(
                        row.hazard_category
                    ),
            }
        )

    statement = text(
        """
        INSERT INTO telosia.hazard_variable (
            hazard_variable,
            hazard_category
        )
        VALUES (
            :hazard_variable,
            :hazard_category
        )
        ON CONFLICT (
            hazard_variable
        )
        DO UPDATE SET
            hazard_category =
                EXCLUDED.hazard_category
        """
    )

    execute_batches(
        connection,
        statement,
        variable_rows,
    )

    results = connection.execute(
        text(
            """
            SELECT
                hazard_variable,
                hazard_variable_id
            FROM telosia.hazard_variable
            """
        )
    ).all()

    hazard_map = {
        str(variable): int(variable_id)
        for variable, variable_id
        in results
    }

    log.info(
        "Loaded %d hazard variables",
        len(hazard_map),
    )

    exposure_rows = []

    for row in bohd.itertuples(
        index=False
    ):
        variable_name = str(
            row.hazard_variable
        )

        exposure_rows.append(
            {
                "occupation_id":
                    resolve_occupation(
                        row.occupation_code,
                        occupation_map,
                        "BOHD",
                    ),

                "hazard_variable_id":
                    hazard_map[
                        variable_name
                    ],

                "exposure_score":
                    float(
                        row.exposure_score
                    ),

                "source_reference_id":
                    source_id,
            }
        )

    exposure_statement = text(
        """
        INSERT INTO telosia.hazard_exposure (
            occupation_id,
            hazard_variable_id,
            exposure_score,
            source_reference_id
        )
        VALUES (
            :occupation_id,
            :hazard_variable_id,
            :exposure_score,
            :source_reference_id
        )
        ON CONFLICT (
            occupation_id,
            hazard_variable_id
        )
        DO UPDATE SET
            exposure_score =
                EXCLUDED.exposure_score,

            source_reference_id =
                EXCLUDED.source_reference_id
        """
    )

    execute_batches(
        connection,
        exposure_statement,
        exposure_rows,
    )

    log.info(
        "Loaded %d hazard exposure rows",
        len(exposure_rows),
    )


def load_mobility(
    connection,
    mobility,
    occupation_map,
    source_id,
):
    log.info(
        "Loading occupation mobility"
    )

    rows = []

    for row in mobility.itertuples(
        index=False
    ):
        source_occupation_id = (
            resolve_occupation(
                row.source_occupation_code,
                occupation_map,
                "Mobility source",
            )
        )

        destination_occupation_id = (
            resolve_occupation(
                row.destination_occupation_code,
                occupation_map,
                "Mobility destination",
            )
        )

        rows.append(
            {
                "source_occupation_id":
                    source_occupation_id,

                "destination_occupation_id":
                    destination_occupation_id,

                "financial_year":
                    str(
                        row.financial_year
                    ),

                "worker_count":
                    int(
                        row.worker_count
                    ),

                "is_self_transition":
                    to_bool(
                        row.is_self_transition
                    ),

                "source_rows_merged":
                    int(
                        row.source_rows_merged
                    ),

                "source_reference_id":
                    source_id,
            }
        )

    mismatched = [
        row
        for row in rows
        if (
            row["is_self_transition"]
            !=
            (
                row["source_occupation_id"]
                ==
                row["destination_occupation_id"]
            )
        )
    ]

    if mismatched:
        raise LoadError(
            f"{len(mismatched)} mobility rows "
            "have an incorrect self-transition flag."
        )

    statement = text(
        """
        INSERT INTO telosia.mobility_flow (
            source_occupation_id,
            destination_occupation_id,
            financial_year,
            worker_count,
            is_self_transition,
            source_rows_merged,
            source_reference_id
        )
        VALUES (
            :source_occupation_id,
            :destination_occupation_id,
            :financial_year,
            :worker_count,
            :is_self_transition,
            :source_rows_merged,
            :source_reference_id
        )
        ON CONFLICT (
            financial_year,
            source_occupation_id,
            destination_occupation_id
        )
        DO UPDATE SET
            worker_count =
                EXCLUDED.worker_count,

            is_self_transition =
                EXCLUDED.is_self_transition,

            source_rows_merged =
                EXCLUDED.source_rows_merged,

            source_reference_id =
                EXCLUDED.source_reference_id
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    total_workers = sum(
        row["worker_count"]
        for row in rows
    )

    log.info(
        "Loaded %d mobility rows",
        len(rows),
    )

    log.info(
        "Mobility worker total: %d",
        total_workers,
    )


def load_pay_gap(
    connection,
    gap,
    occupation_map,
    source_id,
):
    log.info("Loading gender pay gap")

    rows = []
    unresolved = set()
    skipped_rows = 0

    for row in gap.itertuples(index=False):
        parent_code = str(
            row.parent_occupation_code
        ).strip()

        parent_id = occupation_map.get(
            parent_code
        )

        if parent_id is None:
            unresolved.add(parent_code)
            skipped_rows += 1
            continue

        rows.append(
            {
                "parent_occupation_id":
                    parent_id,
                "anzsco_6digit_code":
                    str(
                        row.occupation_code
                    ).strip(),
                "anzsco_6digit_title":
                    str(
                        row.occupation_title
                    ).strip(),
                "is_sole_child_of_parent":
                    to_bool(
                        row.is_sole_child_of_parent
                    ),
                "cohort":
                    str(
                        row.cohort
                    ).strip(),
                "is_headline_cohort":
                    to_bool(
                        row.is_headline_cohort
                    ),
                "segregation_intensity":
                    str(
                        row.segregation_intensity
                    ).strip(),
                "female_income_median":
                    optional_float(
                        row.female_income_median
                    ),
                "male_income_median":
                    optional_float(
                        row.male_income_median
                    ),
                "gender_pay_gap":
                    optional_float(
                        row.gender_pay_gap
                    ),
                "hours_difference":
                    optional_float(
                        row.hours_difference
                    ),
                "ten_year_pay_gap":
                    optional_float(
                        row.ten_year_pay_gap
                    ),
                "source_reference_id":
                    source_id,
            }
        )

    if unresolved:
        log.info(
            "Skipped %d pay gap row(s) from %d parent unit group(s) "
            "not in the occupation universe: %s",
            skipped_rows,
            len(unresolved),
            sorted(unresolved)[:5],
        )

    if not rows:
        raise LoadError(
            "No gender pay gap rows could be linked "
            "to the occupation table."
        )

    columns = list(rows[0])

    placeholders = ", ".join(
        f":{column}"
        for column in columns
    )

    updates = ",\n".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in (
            "anzsco_6digit_code",
            "cohort",
        )
    )

    statement = text(
        f"""
        INSERT INTO telosia.pay_gap (
            {", ".join(columns)}
        )
        VALUES (
            {placeholders}
        )
        ON CONFLICT (
            anzsco_6digit_code,
            cohort
        )
        DO UPDATE SET
            {updates}
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d pay gap rows",
        len(rows),
    )

    return len(rows)


def load_ai_exposure(
    connection,
    ai,
    occupation_map,
    source_id,
):
    log.info("Loading AI exposure")

    fields = [
        "occupation_matrix_group",
        "automation_exposure",
        "automation_sd",
        "augmentation_exposure",
        "augmentation_sd",
        "rate_of_skill_change",
        "high_fit_transition_rate",
        "entry_level_ad_share",
    ]

    rows = []

    for row in ai.itertuples(index=False):
        record = {
            "occupation_id":
                resolve_occupation(
                    row.occupation_code,
                    occupation_map,
                    "AI exposure",
                ),
            "source_reference_id":
                source_id,
        }

        for field in fields:
            if field == "occupation_matrix_group":
                record[field] = str(
                    getattr(row, field)
                ).strip()
            else:
                record[field] = optional_float(
                    getattr(row, field)
                )

        rows.append(record)

    columns = [
        "occupation_id",
        *fields,
        "source_reference_id",
    ]

    placeholders = ", ".join(
        f":{column}"
        for column in columns
    )

    updates = ",\n".join(
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column != "occupation_id"
    )

    statement = text(
        f"""
        INSERT INTO telosia.ai_exposure (
            {", ".join(columns)}
        )
        VALUES (
            {placeholders}
        )
        ON CONFLICT (
            occupation_id
        )
        DO UPDATE SET
            {updates}
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d AI exposure rows",
        len(rows),
    )


def load_occupation_aliases(
    connection,
    aliases,
    occupation_map,
):
    """Load ANZSCO alternative titles/specialisations as occupation_alias
    rows.

    No source_reference_id here - occupation_alias has no such column in
    the schema (it's not a fact table like the others). The dataset is
    still registered in source_reference (see SOURCES["aliases"] and its
    call in main()) so it's visible via GET /sources, just not linked
    from individual alias rows via foreign key.

    Unlike the other load_* functions, an alias row whose anzsco_code
    isn't in occupation_map is expected and NOT an error - the ANZSCO
    index covers every Australian occupation, not just the 401 this
    project has loaded from the other four datasets. Skip those quietly
    and report the count, rather than raising like resolve_occupation()
    does for the other datasets (where every code SHOULD already exist).
    """

    log.info(
        "Loading occupation aliases"
    )

    rows = []
    skipped = 0

    for row in aliases.itertuples(
        index=False
    ):
        occupation_id = occupation_map.get(
            str(row.anzsco_code)
        )

        if occupation_id is None:
            skipped += 1
            continue

        rows.append(
            {
                "occupation_id": occupation_id,
                "alias_text": str(row.alias_text),
                "is_primary": row.category == "Principal Title",
            }
        )

    statement = text(
        """
        INSERT INTO telosia.occupation_alias (
            occupation_id,
            alias_text,
            is_primary
        )
        VALUES (
            :occupation_id,
            :alias_text,
            :is_primary
        )
        ON CONFLICT (
            occupation_id,
            alias_text
        )
        DO NOTHING
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d occupation aliases (%d skipped - "
        "not one of this project's 401 loaded occupations)",
        len(rows),
        skipped,
    )


# Genuine informal/slang job terms that the official ANZSCO alias index
# (VALID_CATEGORIES in anzsco_alias_etl.py) does NOT recognise as an
# alternative title - confirmed by checking, not assumed. This is
# team-curated, not sourced from a dataset, and is kept small and
# reviewable on purpose rather than guessed at length. Every entry here
# has a reason, found through actual testing, not invented in advance:
#
# - "cop" -> Police: adding this doesn't remove the coincidental
#   substring matches search already returns for "cop" (Copywriter,
#   Copyist, Copy Lathe Operator, Helicopter Pilot, Photocopier
#   Technician - all genuinely contain "cop" as letters). It does put
#   the actually correct answer at rank 1 (exact alias match), ahead of
#   those at rank 2/3, which is the practical fix for what search
#   testing found: "cop" returned zero results before the ANZSCO load,
#   and 6 wrong results after it (since more alias text = more
#   coincidental short-string collisions).
# - "coder" -> Software and Applications Programmers: checked the
#   official ANZSCO index directly for this - it only has "Clinical
#   Coder" (a medical records job, unrelated), not "coder" for
#   programming. "developer" and "programmer" ARE in the official index
#   already (loaded via anzsco_alias_etl.py) and don't need duplicating
#   here.
CURATED_ALIASES = [
    {"anzsco_code": "4413", "alias_text": "cop"},
    {"anzsco_code": "2613", "alias_text": "coder"},
]


def load_curated_aliases(
    connection,
    occupation_map,
):
    log.info(
        "Loading curated (non-ANZSCO-sourced) aliases"
    )

    rows = []

    for entry in CURATED_ALIASES:
        occupation_id = resolve_occupation(
            entry["anzsco_code"],
            occupation_map,
            "Curated alias",
        )

        rows.append(
            {
                "occupation_id": occupation_id,
                "alias_text": entry["alias_text"],
                "is_primary": False,
            }
        )

    statement = text(
        """
        INSERT INTO telosia.occupation_alias (
            occupation_id,
            alias_text,
            is_primary
        )
        VALUES (
            :occupation_id,
            :alias_text,
            :is_primary
        )
        ON CONFLICT (
            occupation_id,
            alias_text
        )
        DO NOTHING
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d curated aliases",
        len(rows),
    )


def load_nds_categories(
    connection,
    categories,
):
    log.info("Loading NDS categories")

    if len(categories) != 186:
        raise LoadError(
            "Expected 186 NDS categories, "
            f"found {len(categories)}"
        )

    duplicate_keys = categories.duplicated(
        [
            "dimension",
            "category_code",
        ]
    )

    if duplicate_keys.any():
        raise LoadError(
            "Duplicate NDS category key found."
        )

    rows = []

    for row in categories.itertuples(
        index=False
    ):
        rows.append(
            {
                "dimension":
                    str(row.dimension).strip(),

                "classification":
                    str(row.classification).strip(),

                "category_code":
                    str(row.category_code).strip(),

                "category_label":
                    str(row.category_label).strip(),

                "level":
                    str(row.level).strip(),

                "parent_code":
                    optional_text(
                        row.parent_code
                    ),

                "is_nfd":
                    to_bool(
                        row.is_nfd
                    ),
            }
        )

    statement = text(
        """
        INSERT INTO telosia.nds_category (
            dimension,
            classification,
            category_code,
            category_label,
            level,
            parent_code,
            is_nfd
        )
        VALUES (
            :dimension,
            :classification,
            :category_code,
            :category_label,
            :level,
            :parent_code,
            :is_nfd
        )
        ON CONFLICT (
            dimension,
            category_code
        )
        DO UPDATE SET
            classification =
                EXCLUDED.classification,
            category_label =
                EXCLUDED.category_label,
            level =
                EXCLUDED.level,
            parent_code =
                EXCLUDED.parent_code,
            is_nfd =
                EXCLUDED.is_nfd
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    results = connection.execute(
        text(
            """
            SELECT
                dimension,
                category_code,
                nds_category_id
            FROM telosia.nds_category
            """
        )
    ).all()

    category_map = {
        (
            str(dimension),
            str(category_code),
        ): int(category_id)

        for (
            dimension,
            category_code,
            category_id,
        ) in results
    }

    log.info(
        "Loaded %d NDS categories",
        len(rows),
    )

    return category_map


def load_nds_claims(
    connection,
    claims,
    category_map,
    source_id,
):
    log.info("Loading NDS claim statistics")

    if len(claims) != 9300:
        raise LoadError(
            "Expected 9300 NDS claim rows, "
            f"found {len(claims)}"
        )

    duplicate_keys = claims.duplicated(
        [
            "dimension",
            "category_code",
            "financial_year",
            "measure",
        ]
    )

    if duplicate_keys.any():
        raise LoadError(
            "Duplicate NDS claim statistic key found."
        )

    rows = []

    for row in claims.itertuples(
        index=False
    ):
        category_key = (
            str(row.dimension).strip(),
            str(row.category_code).strip(),
        )

        category_id = category_map.get(
            category_key
        )

        if category_id is None:
            raise LoadError(
                "NDS claim references missing category "
                f"{category_key}"
            )

        value = optional_float(
            row.value
        )

        is_not_published = to_bool(
            row.is_not_published
        )

        if (
            is_not_published
            and value is not None
        ):
            raise LoadError(
                "NDS row is marked NP but "
                "contains a numeric value."
            )

        rows.append(
            {
                "nds_category_id":
                    category_id,

                "financial_year":
                    str(
                        row.financial_year
                    ).strip(),

                "measure":
                    str(
                        row.measure
                    ).strip(),

                "unit":
                    str(
                        row.unit
                    ).strip(),

                "value":
                    value,

                "is_not_published":
                    is_not_published,

                "is_preliminary":
                    to_bool(
                        row.is_preliminary
                    ),

                "source_sheet":
                    optional_text(
                        row.source_sheet
                    ),

                "source_reference_id":
                    source_id,
            }
        )

    # Replace rows owned by this NDS source
    connection.execute(
        text(
            """
            DELETE FROM telosia.nds_claim_statistic
            WHERE source_reference_id = :source_id
            """
        ),
        {
            "source_id": source_id,
        },
    )

    statement = text(
        """
        INSERT INTO telosia.nds_claim_statistic (
            nds_category_id,
            financial_year,
            measure,
            unit,
            value,
            is_not_published,
            is_preliminary,
            source_sheet,
            source_reference_id
        )
        VALUES (
            :nds_category_id,
            :financial_year,
            :measure,
            :unit,
            :value,
            :is_not_published,
            :is_preliminary,
            :source_sheet,
            :source_reference_id
        )
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d NDS claim statistics",
        len(rows),
    )


def load_occupation_nds_links(
    connection,
    categories,
    category_map,
    occupation_map,
):
    log.info("Linking occupations to NDS categories")

    occupation_categories = categories[
        (
            categories["dimension"]
            == "occupation"
        )
        &
        (
            categories["classification"]
            == "ANZSCO"
        )
        &
        (
            categories["level"]
            == "sub_major_group"
        )
    ]

    submajor_codes = set(
        occupation_categories[
            "category_code"
        ]
        .astype(str)
        .str.strip()
    )

    rows = []
    unresolved = []

    for (
        occupation_code,
        occupation_id,
    ) in occupation_map.items():

        occupation_code = str(
            occupation_code
        ).strip()

        nds_code = occupation_code[:2]

        if nds_code not in submajor_codes:
            unresolved.append(
                occupation_code
            )
            continue

        category_id = category_map.get(
            (
                "occupation",
                nds_code,
            )
        )

        if category_id is None:
            unresolved.append(
                occupation_code
            )
            continue

        rows.append(
            {
                "occupation_id":
                    occupation_id,

                "nds_category_id":
                    category_id,

                "derivation":
                    "anzsco_first_two_digits",
            }
        )

    if unresolved:
        raise LoadError(
            "Could not link these occupations "
            "to an NDS ANZSCO Sub-major Group: "
            f"{unresolved[:20]}"
        )

    # Rebuild the bridge from the current occupation universe
    connection.execute(
        text(
            """
            DELETE FROM telosia.occupation_nds_link
            """
        )
    )

    statement = text(
        """
        INSERT INTO telosia.occupation_nds_link (
            occupation_id,
            nds_category_id,
            derivation
        )
        VALUES (
            :occupation_id,
            :nds_category_id,
            :derivation
        )
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Linked %d occupations to NDS categories",
        len(rows),
    )


def load_regions(
    connection,
    regions,
):
    log.info("Loading NERO regions")

    if len(regions) != 88:
        raise LoadError(
            "Expected 88 NERO regions, "
            f"found {len(regions)}"
        )

    duplicate_codes = regions["sa4_code"].duplicated()

    if duplicate_codes.any():
        raise LoadError(
            "Duplicate NERO SA4 code found."
        )

    rows = []

    for row in regions.itertuples(
        index=False
    ):
        rows.append(
            {
                "sa4_code":
                    str(row.sa4_code).strip(),
                "sa4_name":
                    str(row.sa4_name).strip(),
                "state_name":
                    str(row.state_name).strip(),
            }
        )

    statement = text(
        """
        INSERT INTO telosia.region (
            sa4_code,
            sa4_name,
            state_name
        )
        VALUES (
            :sa4_code,
            :sa4_name,
            :state_name
        )
        ON CONFLICT (
            sa4_code
        )
        DO UPDATE SET
            sa4_name = EXCLUDED.sa4_name,
            state_name = EXCLUDED.state_name
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    results = connection.execute(
        text(
            """
            SELECT
                sa4_code,
                region_id
            FROM telosia.region
            """
        )
    ).all()

    region_map = {
        str(code): int(region_id)
        for code, region_id in results
    }

    log.info(
        "Loaded %d NERO regions",
        len(rows),
    )

    return region_map


# Load NERO employment estimates for each occupation and SA4 region
def load_regional_employment(
    connection,
    employment,
    occupation_map,
    region_map,
    source_id,
):
    log.info("Loading NERO regional employment")

    if len(employment) != 31240:
        raise LoadError(
            "Expected 31240 NERO employment rows, "
            f"found {len(employment)}"
        )

    validate_occupation_codes(
        employment,
        "NERO regional employment",
    )

    if employment["occupation_code"].nunique() != 355:
        raise LoadError(
            "Expected NERO data for 355 occupations."
        )

    if employment["sa4_code"].nunique() != 88:
        raise LoadError(
            "Expected NERO data for 88 SA4 regions."
        )

    duplicate_keys = employment.duplicated(
        [
            "occupation_code",
            "sa4_code",
            "reference_date",
        ]
    )

    if duplicate_keys.any():
        raise LoadError(
            "Duplicate NERO occupation-region-date row found."
        )

    rows = []

    for row in employment.itertuples(
        index=False
    ):
        sa4_code = str(
            row.sa4_code
        ).strip()

        region_id = region_map.get(
            sa4_code
        )

        if region_id is None:
            raise LoadError(
                "NERO employment references missing SA4 region "
                f"{sa4_code}"
            )

        one_year_reference_date = None
        if not pd.isna(
            row.one_year_reference_date
        ):
            one_year_reference_date = pd.to_datetime(
                row.one_year_reference_date
            ).date()

        five_year_reference_date = None
        if not pd.isna(
            row.five_year_reference_date
        ):
            five_year_reference_date = pd.to_datetime(
                row.five_year_reference_date
            ).date()

        rows.append(
            {
                "occupation_id":
                    resolve_occupation(
                        row.occupation_code,
                        occupation_map,
                        "NERO regional employment",
                    ),
                "region_id":
                    region_id,
                "reference_date":
                    pd.to_datetime(
                        row.reference_date
                    ).date(),
                "estimated_employment":
                    float(
                        row.estimated_employment
                    ),
                "one_year_reference_date":
                    one_year_reference_date,
                "employment_1y_ago":
                    optional_float(
                        row.employment_1y_ago
                    ),
                "one_year_change_pct":
                    optional_float(
                        row.one_year_change_pct
                    ),
                "five_year_reference_date":
                    five_year_reference_date,
                "employment_5y_ago":
                    optional_float(
                        row.employment_5y_ago
                    ),
                "five_year_change_pct":
                    optional_float(
                        row.five_year_change_pct
                    ),
                "source_reference_id":
                    source_id,
            }
        )

    # Replace rows owned by this NERO source
    connection.execute(
        text(
            """
            DELETE FROM telosia.regional_employment
            WHERE source_reference_id = :source_id
            """
        ),
        {
            "source_id": source_id,
        },
    )

    statement = text(
        """
        INSERT INTO telosia.regional_employment (
            occupation_id,
            region_id,
            reference_date,
            estimated_employment,
            one_year_reference_date,
            employment_1y_ago,
            one_year_change_pct,
            five_year_reference_date,
            employment_5y_ago,
            five_year_change_pct,
            source_reference_id
        )
        VALUES (
            :occupation_id,
            :region_id,
            :reference_date,
            :estimated_employment,
            :one_year_reference_date,
            :employment_1y_ago,
            :one_year_change_pct,
            :five_year_reference_date,
            :employment_5y_ago,
            :five_year_change_pct,
            :source_reference_id
        )
        """
    )

    execute_batches(
        connection,
        statement,
        rows,
    )

    log.info(
        "Loaded %d NERO regional employment rows",
        len(rows),
    )


def validate_database(
    connection,
):
    log.info(
        "Validating database"
    )

    errors = []

    for table, expected in (
        EXPECTED_COUNTS.items()
    ):
        count = int(
            connection.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM telosia.{table}
                    """
                )
            ).scalar_one()
        )

        if count == expected:
            log.info(
                "PASS: %s has %d rows",
                table,
                count,
            )

        else:
            log.error(
                "FAIL: %s has %d rows, expected %d",
                table,
                count,
                expected,
            )

            errors.append(
                f"{table}: "
                f"{count} rows, "
                f"expected {expected}"
            )

    profile_occupations = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.occupation
                WHERE is_profile_occupation = TRUE
                """
            )
        ).scalar_one()
    )

    if profile_occupations == 358:
        log.info(
            "PASS: 358 occupations "
            "are profile-backed"
        )
    else:
        errors.append(
            "Expected 358 profile-backed "
            f"occupations, found {profile_occupations}"
        )

    source_only = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.occupation
                WHERE is_profile_occupation = FALSE
                """
            )
        ).scalar_one()
    )

    if source_only == 43:
        log.info(
            "PASS: 43 source-only "
            "occupation codes preserved"
        )
    else:
        errors.append(
            "Expected 43 source-only "
            f"occupations, found {source_only}"
        )

    worker_total = int(
        connection.execute(
            text(
                """
                SELECT
                    COALESCE(
                        SUM(worker_count),
                        0
                    )
                FROM telosia.mobility_flow
                """
            )
        ).scalar_one()
    )

    if worker_total == 95719060:
        log.info(
            "PASS: mobility worker total "
            "is %d",
            worker_total,
        )
    else:
        errors.append(
            "Mobility worker total is "
            f"{worker_total}, expected 95719060"
        )

    suppressed = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.injury_frequency
                WHERE is_suppressed = TRUE
                """
            )
        ).scalar_one()
    )

    if suppressed == 84:
        log.info(
            "PASS: WCIFR has 84 "
            "suppressed rows"
        )
    else:
        errors.append(
            "Expected 84 suppressed "
            f"WCIFR rows, found {suppressed}"
        )

    genuine_blanks = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.injury_frequency
                WHERE frequency_rate IS NULL
                  AND is_suppressed = FALSE
                """
            )
        ).scalar_one()
    )

    if genuine_blanks == 4:
        log.info(
            "PASS: WCIFR has 4 "
            "genuine blank rows"
        )
    else:
        errors.append(
            "Expected 4 genuine blank "
            f"WCIFR rows, found {genuine_blanks}"
        )

    bad_suppressed = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.injury_frequency
                WHERE is_suppressed = TRUE
                  AND frequency_rate IS NOT NULL
                """
            )
        ).scalar_one()
    )

    if bad_suppressed == 0:
        log.info(
            "PASS: suppressed WCIFR "
            "rows contain no rate"
        )
    else:
        errors.append(
            f"{bad_suppressed} suppressed "
            "WCIFR rows contain a rate"
        )

    hazard_categories = int(
        connection.execute(
            text(
                """
                SELECT COUNT(
                    DISTINCT hazard_category
                )
                FROM telosia.hazard_variable
                """
            )
        ).scalar_one()
    )

    if hazard_categories == 13:
        log.info(
            "PASS: BOHD has 13 "
            "hazard categories"
        )
    else:
        errors.append(
            "Expected 13 BOHD hazard "
            f"categories, found {hazard_categories}"
        )

    self_transitions = int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM telosia.mobility_flow
                WHERE is_self_transition = TRUE
                """
            )
        ).scalar_one()
    )

    if self_transitions == 3920:
        log.info(
            "PASS: Mobility has 3920 "
            "self-transition rows"
        )
    else:
        errors.append(
            "Expected 3920 mobility "
            f"self-transitions, found {self_transitions}"
        )

    if errors:
        raise LoadError(
            "Database validation failed:\n- "
            + "\n- ".join(errors)
        )

    log.info(
        "Database validation completed successfully"
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    log.info(
        "Reading cleaned ETL outputs"
    )

    profiles = read_csv(
        PROFILES_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    wcifr = read_csv(
        WCIFR_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    bohd = read_csv(
        BOHD_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    mobility = read_csv(
        MOBILITY_FILE,
        dtype={
            "source_occupation_code": str,
            "destination_occupation_code": str,
        },
    )

    aliases = read_csv(
        ALIASES_FILE,
        dtype={
            "anzsco_code": str,
        },
    )

    pay_gap = read_csv(
        PAY_GAP_FILE,
        dtype={
            "occupation_code": str,
            "parent_occupation_code": str,
        },
    )

    ai_exposure = read_csv(
        AI_EXPOSURE_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    descriptions = read_csv(
        DESCRIPTIONS_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    tasks = read_csv(
        TASKS_FILE,
        dtype={
            "occupation_code": str,
        },
    )

    nds_categories = read_csv(
        NDS_CATEGORY_FILE,
        dtype={
            "category_code": str,
            "parent_code": str,
        },
    )

    nds_claims = read_csv(
        NDS_CLAIMS_FILE,
        dtype={
            "category_code": str,
            "financial_year": str,
        },
    )

    nero_regions = read_csv(
        NERO_REGION_FILE,
        dtype={
            "sa4_code": str,
        },
    )

    nero_employment = read_csv(
        NERO_EMPLOYMENT_FILE,
        dtype={
            "sa4_code": str,
            "occupation_code": str,
        },
    )

    occupations = collect_occupation_codes(
        profiles,
        wcifr,
        bohd,
        mobility,
    )

    log.info(
        "Connecting to PostgreSQL"
    )

    # One transaction for the complete load.
    # If any step fails, PostgreSQL rolls everything back.
    with engine.begin() as connection:

        source_ids = {
            key:
                get_source_reference(
                    connection,
                    key,
                )
            for key in SOURCES
        }

        occupation_map = load_occupations(
            connection,
            occupations,
        )

        load_profiles(
            connection,
            profiles,
            occupation_map,
            source_ids[
                "profiles"
            ],
        )

        load_descriptions(
            connection,
            descriptions,
            occupation_map,
        )

        load_tasks(
            connection,
            tasks,
            occupation_map,
            source_ids[
                "profiles"
            ],
        )

        load_wcifr(
            connection,
            wcifr,
            occupation_map,
            source_ids[
                "wcifr"
            ],
        )

        load_hazards(
            connection,
            bohd,
            occupation_map,
            source_ids[
                "bohd"
            ],
        )

        load_mobility(
            connection,
            mobility,
            occupation_map,
            source_ids[
                "mobility"
            ],
        )

        load_pay_gap(
            connection,
            pay_gap,
            occupation_map,
            source_ids[
                "pay_gap"
            ],
        )

        load_ai_exposure(
            connection,
            ai_exposure,
            occupation_map,
            source_ids[
                "ai_exposure"
            ],
        )

        load_occupation_aliases(
            connection,
            aliases,
            occupation_map,
        )

        load_curated_aliases(
            connection,
            occupation_map,
        )

        nds_category_map = load_nds_categories(
            connection,
            nds_categories,
        )

        load_nds_claims(
            connection,
            nds_claims,
            nds_category_map,
            source_ids["nds"],
        )

        load_occupation_nds_links(
            connection,
            nds_categories,
            nds_category_map,
            occupation_map,
        )

        region_map = load_regions(
            connection,
            nero_regions,
        )

        load_regional_employment(
            connection,
            nero_employment,
            occupation_map,
            region_map,
            source_ids["nero"],
        )

        update_coverage_periods(
            connection,
            source_ids,
        )

        validate_database(
            connection
        )

    log.info(
        "Database load completed successfully"
    )


if __name__ == "__main__":
    main()