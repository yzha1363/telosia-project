"""
Occupation content ETL - descriptions and tasks (JSA ANZSCO Occupation Data).

Extracts the occupation description and the task list for each occupation, so
that plain-language search can match on more than the occupation title, and so
that a destination can show what the work actually involves.

Source
------
File   : datasets/ANZSCO_Occupation_data_-_February_2026.xlsx
Sheets : "Table_2" - Occupation descriptions, one row per occupation
         "Table_3" - Occupation tasks, one row per task
Layout : both sheets carry the header on row 6 with data from row 7, matching
         the layout used by the occupation profiles pipeline.

Table_2 supplies 1,236 descriptions, one per occupation, of which 358 are at
4-digit level. Table_3 supplies 8,113 task rows across 1,235 occupations; the
same occupation appears once per task, giving 3,037 task rows across the 358
four-digit occupations, a median of 9 tasks each.

Both sheets carry trailing unnamed columns that are entirely empty in the
published file. They are dropped rather than loaded.

Outputs
-------
data/processed/occupation_descriptions_clean.csv - one row per occupation
data/processed/occupation_tasks_clean.csv        - one row per task

Run:
    python -m etl.occupation_content_etl
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "datasets" / "ANZSCO Occupation data - February 2026.xlsx"
DESCRIPTIONS_FILE = ROOT / "data" / "processed" / "occupation_descriptions_clean.csv"
TASKS_FILE = ROOT / "data" / "processed" / "occupation_tasks_clean.csv"

DESCRIPTIONS_SHEET = "Table_2"
TASKS_SHEET = "Table_3"
HEADER_ROW = 6

CODE_COLUMN = "ANZSCO Code"
TITLE_COLUMN = "Occupation"
DESCRIPTION_COLUMN = "Description"
TASKS_COLUMN = "Tasks"

TARGET_ANZSCO_LEVEL = 4

# Derived from inspecting the workbook.
EXPECTED_DESCRIPTIONS = 358
EXPECTED_TASK_ROWS = 3037
EXPECTED_TASK_OCCUPATIONS = 358

log = logging.getLogger(__name__)


class OccupationContentValidationError(Exception):
    """Raised when the transformed description or task data fails a check."""


def extract_content(path: Path = RAW_FILE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the description and task sheets from the raw workbook."""
    if not path.exists():
        raise FileNotFoundError(
            f"JSA occupation data workbook not found at {path}. "
            "Place the downloaded file in datasets/ without renaming it."
        )

    descriptions = pd.read_excel(
        path, sheet_name=DESCRIPTIONS_SHEET, header=HEADER_ROW,
        engine="openpyxl", dtype={CODE_COLUMN: str},
    )
    tasks = pd.read_excel(
        path, sheet_name=TASKS_SHEET, header=HEADER_ROW,
        engine="openpyxl", dtype={CODE_COLUMN: str},
    )

    log.info("Extracted %d description rows and %d task rows",
             len(descriptions), len(tasks))
    return descriptions, tasks


def _prepare(df: pd.DataFrame, text_column: str, label: str) -> pd.DataFrame:
    """Keep the code, title and text column, and filter to 4-digit occupations."""
    missing = [c for c in (CODE_COLUMN, TITLE_COLUMN, text_column)
               if c not in df.columns]
    if missing:
        raise OccupationContentValidationError(
            f"{label} sheet is missing expected columns: {missing}. "
            "The publisher may have changed the workbook layout."
        )

    # Trailing unnamed columns in the published file are entirely empty.
    dropped = [c for c in df.columns if str(c).startswith("Unnamed")]
    if dropped:
        log.info("  %s: dropping %d empty trailing column(s)", label, len(dropped))

    work = df[[CODE_COLUMN, TITLE_COLUMN, text_column]].copy()
    work[CODE_COLUMN] = work[CODE_COLUMN].astype(str).str.strip()
    work = work[work[CODE_COLUMN].str.match(r"^\d+$")]

    work["anzsco_level"] = work[CODE_COLUMN].str.len()
    levels = work["anzsco_level"].value_counts().sort_index().to_dict()
    log.info("  %s: ANZSCO code lengths present: %s", label, levels)

    # Keep 4-digit Unit Groups. The 6-digit rows sit underneath them, so keeping
    # both would attach two sets of content to the same unit group.
    work = work[work["anzsco_level"] == TARGET_ANZSCO_LEVEL]

    work[text_column] = work[text_column].astype(str).str.strip()
    work = work[work[text_column].notna() & (work[text_column] != "")
                & (work[text_column].str.lower() != "nan")]
    return work


def transform_content(descriptions: pd.DataFrame,
                      tasks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Produce one description row per occupation and one row per task."""
    desc = _prepare(descriptions, DESCRIPTION_COLUMN, DESCRIPTIONS_SHEET)
    desc = desc.rename(columns={
        CODE_COLUMN: "occupation_code",
        TITLE_COLUMN: "occupation_title",
        DESCRIPTION_COLUMN: "description",
    })
    desc["description_length"] = desc["description"].str.len()
    desc = (desc[["occupation_code", "occupation_title", "anzsco_level",
                  "description", "description_length"]]
            .sort_values("occupation_code")
            .reset_index(drop=True))
    log.info("Descriptions: %d occupations", len(desc))

    task = _prepare(tasks, TASKS_COLUMN, TASKS_SHEET)
    task = task.rename(columns={
        CODE_COLUMN: "occupation_code",
        TITLE_COLUMN: "occupation_title",
        TASKS_COLUMN: "task_text",
    })

    # The source lists tasks in a meaningful order but supplies no index, so one
    # is added per occupation to preserve that order through the database.
    task = task.sort_values(["occupation_code"], kind="stable")
    task["task_order"] = task.groupby("occupation_code").cumcount() + 1
    task = (task[["occupation_code", "occupation_title", "anzsco_level",
                  "task_order", "task_text"]]
            .reset_index(drop=True))

    per_occupation = task.groupby("occupation_code").size()
    log.info("Tasks: %d rows across %d occupations (min %d, median %d, max %d per occupation)",
             len(task), task["occupation_code"].nunique(),
             per_occupation.min(), int(per_occupation.median()), per_occupation.max())
    return desc, task


def validate_content(desc: pd.DataFrame, task: pd.DataFrame) -> None:
    """Check the structural properties of the cleaned description and task data."""
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            log.info("  PASS  %s", label)
        else:
            log.error("  FAIL  %s%s", label, f" — {detail}" if detail else "")
            failures.append(label)

    log.info("Validating occupation descriptions and tasks")

    check(f"description rows == {EXPECTED_DESCRIPTIONS}",
          len(desc) == EXPECTED_DESCRIPTIONS, f"got {len(desc)}")
    check("occupation_code is unique in descriptions",
          desc["occupation_code"].is_unique)
    check("every description code matches ^\\d{4}$",
          desc["occupation_code"].str.match(r"^\d{4}$").all())
    check("descriptions are non-empty", (desc["description_length"] > 0).all())

    check(f"task rows == {EXPECTED_TASK_ROWS}",
          len(task) == EXPECTED_TASK_ROWS, f"got {len(task)}")
    check(f"task occupations == {EXPECTED_TASK_OCCUPATIONS}",
          task["occupation_code"].nunique() == EXPECTED_TASK_OCCUPATIONS,
          f"got {task['occupation_code'].nunique()}")
    check("every task code matches ^\\d{4}$",
          task["occupation_code"].str.match(r"^\d{4}$").all())
    check("task text is non-empty", (task["task_text"].str.len() > 0).all())

    dupes = task[task.duplicated(["occupation_code", "task_order"], keep=False)]
    check("(occupation_code, task_order) is unique", dupes.empty,
          f"{len(dupes)} duplicated rows")

    check("task_order starts at 1 for every occupation",
          bool((task.groupby("occupation_code")["task_order"].min() == 1).all()))

    # Every occupation with a description should also have at least one task.
    without_tasks = set(desc["occupation_code"]) - set(task["occupation_code"])
    check("every described occupation has at least one task",
          not without_tasks, f"missing: {sorted(without_tasks)[:5]}")

    check("codes stored as strings",
          desc["occupation_code"].map(type).eq(str).all()
          and task["occupation_code"].map(type).eq(str).all())

    if failures:
        raise OccupationContentValidationError(
            f"{len(failures)} validation check(s) failed:\n  - " + "\n  - ".join(failures)
        )
    log.info("All validation checks passed")


def main(write_csv: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    log.info("Reading %s", RAW_FILE.name)
    raw_desc, raw_tasks = extract_content()
    desc, task = transform_content(raw_desc, raw_tasks)
    validate_content(desc, task)

    if write_csv:
        DESCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        desc.to_csv(DESCRIPTIONS_FILE, index=False)
        task.to_csv(TASKS_FILE, index=False)
        log.info("Wrote %s (%d rows)", DESCRIPTIONS_FILE, len(desc))
        log.info("Wrote %s (%d rows)", TASKS_FILE, len(task))
    return desc, task


if __name__ == "__main__":
    main()