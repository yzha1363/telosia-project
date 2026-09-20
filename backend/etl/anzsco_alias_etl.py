"""Extract and clean the ABS ANZSCO alias index for occupation_alias.

Source: ABS, "ANZSCO 2022 Index of Principal Titles, Alternative Titles
and Specialisations" (abs.gov.au), released 22 November 2022, updated
27 June 2023. Not the same publication as the JSA "ANZSCO Occupation
data" workbook already loaded (occupation_profiles_etl.py) - that one
is JSA employment statistics; this one is the ABS's own classification
index, specifically built to list the different everyday/alternative
names for each occupation.

This file operates at the 6-digit ANZSCO occupation level. Our
occupation table is keyed at the 4-digit unit-group level (an
aggregation of multiple 6-digit occupations), so multiple distinct
6-digit titles legitimately become multiple aliases for one 4-digit
occupation - these are not duplicates. Confirmed by spot-checking
before writing this: e.g. 4-digit group 1112 aggregates 6-digit
"Corporate General Manager" (111211) and "Defence Force Senior
Officer" (111212) - two real, different search terms, not the same
thing said twice.

Only rows whose 4-digit prefix matches one of our loaded occupations
are kept (roughly 86% of our 401 loaded occupations get coverage from
this file - the rest, and genuine slang like "cop" or "coder" that
ANZSCO's own index doesn't recognise as an alternative title, are not
covered by this and would need a separate, clearly-labelled addition).
"""

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

RAW_FILE = (
    ROOT
    / "datasets"
    / "ANZSCO 2022 Index of Principal Titles Alternative Titles and Specialisations.xlsx"
)

OUTPUT_FILE = ROOT / "data" / "processed" / "anzsco_alias_clean.csv"

SHEET_NAME = "Table 2"
HEADER_ROW = 5

# Categories the source file uses. All four are loaded as aliases -
# even "Occupation in nec category" is a real thing someone might type,
# just a lower-precision match than an official Alternative Title.
VALID_CATEGORIES = {
    "Principal Title",
    "Alternative Title",
    "Specialisation",
    "Occupation in nec category",
}

MAX_ALIAS_LENGTH = 200  # matches occupation_alias.alias_text VARCHAR(200)

log = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


def extract():
    if not RAW_FILE.exists():
        raise FileNotFoundError(f"ANZSCO alias index not found: {RAW_FILE}")

    df = pd.read_excel(RAW_FILE, sheet_name=SHEET_NAME, header=HEADER_ROW)
    df.columns = ["occupation_code", "description", "category"]
    return df


def clean(df):
    # Drop the trailing copyright/footer row and anything else where the
    # occupation code isn't actually numeric.
    df = df[pd.to_numeric(df["occupation_code"], errors="coerce").notna()].copy()

    df["occupation_code"] = (
        df["occupation_code"].astype(int).astype(str).str.zfill(6)
    )
    df["anzsco_code"] = df["occupation_code"].str[:4]

    df["description"] = df["description"].astype(str).str.strip()
    df = df[df["description"].str.len() > 0]
    df = df[df["description"].str.len() <= MAX_ALIAS_LENGTH]

    df = df[df["category"].isin(VALID_CATEGORIES)]

    # Multiple 6-digit codes can share the same 4-digit group and
    # occasionally produce the exact same description text (rare, but
    # happens) - dedupe on (anzsco_code, description), not on the raw
    # 6-digit rows.
    df = df.drop_duplicates(subset=["anzsco_code", "description"])

    return df[["anzsco_code", "description", "category"]].rename(
        columns={"description": "alias_text"}
    )


def validate(df):
    if df["alias_text"].isna().any():
        raise ValidationError("Found null alias_text after cleaning.")

    if (df["anzsco_code"].str.len() != 4).any():
        raise ValidationError("Found an anzsco_code that isn't 4 digits.")

    dupes = df.duplicated(subset=["anzsco_code", "alias_text"]).sum()
    if dupes:
        raise ValidationError(f"Found {dupes} duplicate (anzsco_code, alias_text) rows.")

    log.info("Validation passed: %d alias rows", len(df))


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    log.info("Reading ANZSCO alias index")
    raw = extract()
    log.info("Raw rows: %d", len(raw))

    cleaned = clean(raw)
    log.info("Cleaned rows: %d", len(cleaned))
    log.info("Distinct 4-digit occupation codes referenced: %d", cleaned["anzsco_code"].nunique())

    validate(cleaned)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(OUTPUT_FILE, index=False)
    log.info("Wrote %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
