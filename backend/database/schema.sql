BEGIN;

CREATE SCHEMA IF NOT EXISTS telosia;

-- Powers the search endpoint's typo-tolerance tier (similarity()).
-- Installs into public, which is fine - search_path below covers it.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

SET search_path TO telosia, public;


-- ============================================================
-- 1. SOURCE REFERENCE
-- Provenance information for each dataset
-- ============================================================

CREATE TABLE IF NOT EXISTS source_reference (
    source_reference_id SERIAL PRIMARY KEY,

    publisher VARCHAR(100) NOT NULL,
    dataset_title VARCHAR(200) NOT NULL,
    dataset_url VARCHAR(300),
    licence VARCHAR(100),
    attribution_text TEXT,

    coverage_period_start DATE,
    coverage_period_end DATE,
    retrieval_date DATE,

    plain_language_note TEXT,
    update_frequency VARCHAR(60),

    UNIQUE (
        publisher,
        dataset_title
    )
);


-- ============================================================
-- 2. OCCUPATION
--
-- Contains every 4-character occupation code referenced by the
-- four core datasets.
--
-- 358 codes are backed by JSA Occupation Profiles.
-- Additional source-only / nfd codes are kept so WCIFR and
-- Mobility rows are not discarded.
-- ============================================================

CREATE TABLE IF NOT EXISTS occupation (
    occupation_id SERIAL PRIMARY KEY,

    anzsco_code VARCHAR(4) UNIQUE NOT NULL,
    occupation_title VARCHAR(200) NOT NULL,
    occupation_description TEXT,

    anzsco_level INTEGER NOT NULL DEFAULT 4,

    is_profile_occupation BOOLEAN NOT NULL DEFAULT FALSE,
    is_launch_persona BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CHECK (
        anzsco_code ~ '^[0-9]{4}$'
    ),

    CHECK (
        anzsco_level = 4
    ),

    CHECK (
        occupation_description IS NULL
        OR length(trim(occupation_description)) > 0
    )
);

-- Allows this schema file to update an already-created database
ALTER TABLE occupation
    ADD COLUMN IF NOT EXISTS occupation_description TEXT;


-- ============================================================
-- 3. OCCUPATION PROFILE
-- JSA profile data
-- Only the 358 occupations published in the profile workbook
-- receive a row here.
-- ============================================================

CREATE TABLE IF NOT EXISTS occupation_profile (
    occupation_profile_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    employed FLOAT,

    female_share_pct FLOAT,
    part_time_share_pct FLOAT,

    median_age FLOAT,
    median_weekly_earnings FLOAT,

    annual_employment_growth FLOAT,

    postgrad_share_pct FLOAT,
    bachelor_share_pct FLOAT,
    diploma_share_pct FLOAT,
    certificate_share_pct FLOAT,
    year12_share_pct FLOAT,
    year11_share_pct FLOAT,
    year10_or_below_share_pct FLOAT,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        occupation_id
    ),

    CHECK (
        female_share_pct IS NULL
        OR female_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        part_time_share_pct IS NULL
        OR part_time_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        postgrad_share_pct IS NULL
        OR postgrad_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        bachelor_share_pct IS NULL
        OR bachelor_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        diploma_share_pct IS NULL
        OR diploma_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        certificate_share_pct IS NULL
        OR certificate_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        year12_share_pct IS NULL
        OR year12_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        year11_share_pct IS NULL
        OR year11_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        year10_or_below_share_pct IS NULL
        OR year10_or_below_share_pct BETWEEN 0 AND 100
    ),

    CHECK (
        median_age IS NULL
        OR median_age BETWEEN 15 AND 80
    ),

    CHECK (
        median_weekly_earnings IS NULL
        OR median_weekly_earnings > 0
    ),

    CHECK (
        employed IS NULL
        OR employed >= 0
    )
);


-- ============================================================
-- 3b. OCCUPATION TASK
-- JSA occupation tasks - what the work actually involves
-- ============================================================

CREATE TABLE IF NOT EXISTS occupation_task (
    occupation_task_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    task_order INTEGER NOT NULL,
    task_text TEXT NOT NULL,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (occupation_id, task_order),

    CHECK (task_order >= 1),
    CHECK (length(trim(task_text)) > 0)
);


-- ============================================================
-- 4. INJURY FREQUENCY
-- Safe Work Australia WCIFR
--
-- Rate = lost time claims per million hours worked.
--
-- NULL + is_suppressed TRUE = publisher withheld the value.
-- NULL + is_suppressed FALSE = source cell genuinely blank.
-- ============================================================

CREATE TABLE IF NOT EXISTS injury_frequency (
    injury_frequency_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    financial_year VARCHAR(7) NOT NULL,
    measure_type VARCHAR(100) NOT NULL,

    frequency_rate FLOAT,

    is_suppressed BOOLEAN NOT NULL DEFAULT FALSE,
    is_preliminary BOOLEAN NOT NULL DEFAULT FALSE,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        occupation_id,
        financial_year,
        measure_type
    ),

    CHECK (
        financial_year ~ '^[0-9]{4}-[0-9]{2}$'
    ),

    CHECK (
        frequency_rate IS NULL
        OR frequency_rate >= 0
    ),

    CHECK (
        NOT (
            is_suppressed
            AND frequency_rate IS NOT NULL
        )
    )
);


-- ============================================================
-- 5. HAZARD VARIABLE
-- BOHD's 57 predictor variables and their 13 categories
-- ============================================================

CREATE TABLE IF NOT EXISTS hazard_variable (
    hazard_variable_id SERIAL PRIMARY KEY,

    hazard_variable VARCHAR(250) UNIQUE NOT NULL,
    hazard_category VARCHAR(150) NOT NULL,

    question_text TEXT,

    CHECK (
        hazard_category NOT ILIKE
        'Workers%compensation%'
    ),

    CHECK (
        hazard_category NOT ILIKE
        'ABS employment data'
    )
);


-- ============================================================
-- 6. HAZARD EXPOSURE
-- One BOHD score for each occupation / hazard combination
-- ============================================================

CREATE TABLE IF NOT EXISTS hazard_exposure (
    hazard_exposure_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    hazard_variable_id INTEGER NOT NULL
        REFERENCES hazard_variable(hazard_variable_id),

    exposure_score FLOAT NOT NULL,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        occupation_id,
        hazard_variable_id
    ),

    CHECK (
        exposure_score >= 0
        AND exposure_score <= 100
    )
);


-- ============================================================
-- 7. MOBILITY FLOW
--
-- JSA source data begins at 6-digit ANZSCO.
-- ETL rolls both sides to 4 characters and aggregates counts.
--
-- Every code is represented in occupation, including preserved
-- source-only / nfd codes, so both FKs are required.
-- ============================================================

CREATE TABLE IF NOT EXISTS mobility_flow (
    mobility_flow_id SERIAL PRIMARY KEY,

    source_occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    destination_occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    financial_year VARCHAR(7) NOT NULL,

    worker_count INTEGER NOT NULL,

    is_self_transition BOOLEAN
        NOT NULL DEFAULT FALSE,

    source_rows_merged INTEGER
        NOT NULL DEFAULT 1,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        financial_year,
        source_occupation_id,
        destination_occupation_id
    ),

    CHECK (
        financial_year ~ '^[0-9]{4}-[0-9]{2}$'
    ),

    CHECK (
        worker_count > 0
    ),

    CHECK (
        source_rows_merged >= 1
    ),

    CHECK (
        is_self_transition =
        (
            source_occupation_id =
            destination_occupation_id
        )
    )
);


-- ============================================================
-- 8. OCCUPATION ALIAS
-- Plain-language or alternative occupation names
-- ============================================================

CREATE TABLE IF NOT EXISTS occupation_alias (
    alias_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    alias_text VARCHAR(200) NOT NULL,

    is_primary BOOLEAN DEFAULT FALSE,

    UNIQUE (
        occupation_id,
        alias_text
    )
);


-- ============================================================
-- 9. CROSSWALK STATUS
-- Future ASCO2 -> ANZSCO mapping for WorkSafe Victoria
-- ============================================================

CREATE TABLE IF NOT EXISTS crosswalk_status (
    crosswalk_id SERIAL PRIMARY KEY,

    occupation_id INTEGER
        REFERENCES occupation(occupation_id),

    asco2_code VARCHAR(4),
    anzsco_code VARCHAR(4),

    mapping_type VARCHAR(40),
    verification_status VARCHAR(40),
    mapping_confidence VARCHAR(10),

    female_count INTEGER,
    person_count INTEGER,
    allocation_weight FLOAT,

    source_reference_id INTEGER
        REFERENCES source_reference(source_reference_id),

    verified_at TIMESTAMP,
    notes TEXT,

    UNIQUE (
        asco2_code,
        anzsco_code
    ),

    CHECK (
        allocation_weight IS NULL
        OR allocation_weight BETWEEN 0 AND 1
    ),

    CHECK (
        mapping_confidence IS NULL
        OR mapping_confidence IN (
            'high',
            'medium',
            'low'
        )
    ),

    CHECK (
        female_count IS NULL
        OR female_count >= 0
    ),

    CHECK (
        person_count IS NULL
        OR person_count >= 0
    )
);


-- ============================================================
-- 9b. PAY GAP
-- JSA Occupational Gender Pay Gap Dashboard, at 6-digit ANZSCO
-- (medians are not aggregated to Telosia's 4-digit unit group)
-- ============================================================

CREATE TABLE IF NOT EXISTS pay_gap (
    pay_gap_id SERIAL PRIMARY KEY,

    parent_occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    anzsco_6digit_code VARCHAR(6) NOT NULL,
    anzsco_6digit_title VARCHAR(200) NOT NULL,

    is_sole_child_of_parent BOOLEAN NOT NULL,

    cohort VARCHAR(40) NOT NULL,
    is_headline_cohort BOOLEAN NOT NULL,

    segregation_intensity VARCHAR(60),

    female_income_median NUMERIC(12,2),
    male_income_median NUMERIC(12,2),

    gender_pay_gap NUMERIC(6,3),
    hours_difference NUMERIC(6,3),
    ten_year_pay_gap NUMERIC(6,3),

    source_reference_id INTEGER
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        anzsco_6digit_code,
        cohort
    ),

    CHECK (
        anzsco_6digit_code ~ '^[0-9]{6}$'
    ),

    CHECK (
        female_income_median IS NULL
        OR female_income_median > 0
    ),

    CHECK (
        male_income_median IS NULL
        OR male_income_median > 0
    )
);


-- ============================================================
-- 9c. AI EXPOSURE
-- JSA Generative AI Capacity Study - published exposure ratings
-- only, nothing modelled by the team
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_exposure (
    ai_exposure_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    occupation_matrix_group VARCHAR(120),

    automation_exposure NUMERIC(4,3) NOT NULL,
    automation_sd NUMERIC(4,3),

    augmentation_exposure NUMERIC(4,3) NOT NULL,
    augmentation_sd NUMERIC(4,3),

    rate_of_skill_change NUMERIC(6,3),
    high_fit_transition_rate NUMERIC(4,3),
    entry_level_ad_share NUMERIC(4,3),

    source_reference_id INTEGER
        REFERENCES source_reference(source_reference_id),

    UNIQUE (occupation_id),

    CHECK (
        automation_exposure BETWEEN 0 AND 1
    ),

    CHECK (
        augmentation_exposure BETWEEN 0 AND 1
    )
);


-- ============================================================
-- 10. NDS CATEGORY / NDS CLAIM STATISTIC / OCCUPATION NDS LINK
-- Safe Work Australia's National Dataset for Compensation
-- Based Statistics - a national, ANZSCO-native claims dataset
-- that sidesteps the ASCO2 crosswalk problem entirely, but only
-- publishes occupation figures at 2-digit ANZSCO Sub-major
-- Group level, and (like WorkSafe Victoria's report) does not
-- cross-tabulate occupation against injury mechanism.
-- ============================================================

CREATE TABLE IF NOT EXISTS nds_category (
    nds_category_id SERIAL PRIMARY KEY,

    dimension VARCHAR(20) NOT NULL,
    classification VARCHAR(10) NOT NULL,

    category_code VARCHAR(20) NOT NULL,
    category_label VARCHAR(200) NOT NULL,

    level VARCHAR(30) NOT NULL,
    parent_code VARCHAR(20),

    is_nfd BOOLEAN NOT NULL DEFAULT FALSE,

    UNIQUE (
        dimension,
        category_code
    ),

    CHECK (
        dimension IN (
            'industry',
            'occupation'
        )
    ),

    CHECK (
        classification IN (
            'ANZSIC',
            'ANZSCO'
        )
    ),

    CHECK (
        (
            dimension = 'industry'
            AND classification = 'ANZSIC'
        )
        OR
        (
            dimension = 'occupation'
            AND classification = 'ANZSCO'
        )
    )
);


CREATE TABLE IF NOT EXISTS nds_claim_statistic (
    nds_claim_statistic_id BIGSERIAL PRIMARY KEY,

    nds_category_id INTEGER NOT NULL
        REFERENCES nds_category(nds_category_id),

    financial_year VARCHAR(7) NOT NULL,

    measure VARCHAR(40) NOT NULL,
    unit VARCHAR(60) NOT NULL,

    value NUMERIC(18,6),

    is_not_published BOOLEAN NOT NULL DEFAULT FALSE,
    is_preliminary BOOLEAN NOT NULL DEFAULT FALSE,

    source_sheet VARCHAR(20),

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        nds_category_id,
        financial_year,
        measure
    ),

    CHECK (
        measure IN (
            'claim_count',
            'frequency_rate',
            'incidence_rate',
            'median_compensation',
            'median_time_lost'
        )
    ),

    CHECK (
        NOT (
            value IS NOT NULL
            AND is_not_published = TRUE
        )
    )
);


-- Links each Telosia 4-digit occupation to its
-- published NDS 2-digit ANZSCO Sub-major Group
CREATE TABLE IF NOT EXISTS occupation_nds_link (
    occupation_id INTEGER PRIMARY KEY
        REFERENCES occupation(occupation_id),

    nds_category_id INTEGER NOT NULL
        REFERENCES nds_category(nds_category_id),

    derivation VARCHAR(60) NOT NULL
        DEFAULT 'anzsco_first_two_digits'
);


-- ============================================================
-- 10b. REGION / REGIONAL EMPLOYMENT
-- JSA's NERO (Nowcast of Employment by Region and Occupation) -
-- SA4-region-level employment estimates per occupation, with
-- current, one-year-ago and five-year-ago figures. This is
-- employment LEVELS by region, not mobility by region - it
-- answers "is my job common where I live", not "where do people
-- leaving my job in my region actually go" (mobility_flow stays
-- national-only; nothing here changes that).
-- ============================================================

CREATE TABLE IF NOT EXISTS region (
    region_id SERIAL PRIMARY KEY,
    sa4_code VARCHAR(3) NOT NULL UNIQUE,
    sa4_name VARCHAR(120) NOT NULL,
    state_name VARCHAR(10) NOT NULL,

    CHECK (sa4_code ~ '^[0-9]{3}$')
);


CREATE TABLE IF NOT EXISTS regional_employment (
    regional_employment_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    region_id INTEGER NOT NULL
        REFERENCES region(region_id),

    reference_date DATE NOT NULL,

    estimated_employment FLOAT NOT NULL,

    one_year_reference_date DATE,
    employment_1y_ago FLOAT,
    one_year_change_pct FLOAT,

    five_year_reference_date DATE,
    employment_5y_ago FLOAT,
    five_year_change_pct FLOAT,

    source_reference_id INTEGER NOT NULL
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        occupation_id,
        region_id,
        reference_date
    ),

    CHECK (estimated_employment >= 0),

    CHECK (
        employment_1y_ago IS NULL
        OR employment_1y_ago >= 0
    ),

    CHECK (
        employment_5y_ago IS NULL
        OR employment_5y_ago >= 0
    )
);


-- ============================================================
-- 11. MODEL RUN
-- One row for each model-training run
-- ============================================================

CREATE TABLE IF NOT EXISTS model_run (
    model_run_id SERIAL PRIMARY KEY,

    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(40) NOT NULL,

    generated_at TIMESTAMP
        DEFAULT CURRENT_TIMESTAMP,

    cv_r_squared FLOAT,
    training_n INTEGER,

    notes TEXT,

    CHECK (
        training_n IS NULL
        OR training_n >= 0
    )
);


-- ============================================================
-- 12. INJURY INSIGHT
-- Model-generated values, not raw source observations
-- ============================================================

CREATE TABLE IF NOT EXISTS injury_insight (
    insight_id SERIAL PRIMARY KEY,

    occupation_id INTEGER NOT NULL
        REFERENCES occupation(occupation_id),

    model_run_id INTEGER NOT NULL
        REFERENCES model_run(model_run_id),

    insight_type VARCHAR(60) NOT NULL,

    direction_or_label VARCHAR(100),
    confidence_value FLOAT,

    window_start VARCHAR(7),
    window_end VARCHAR(7),

    source_reference_id INTEGER
        REFERENCES source_reference(source_reference_id),

    UNIQUE (
        occupation_id,
        model_run_id,
        insight_type
    ),

    CHECK (
        confidence_value IS NULL
        OR confidence_value BETWEEN 0 AND 1
    )
);


-- ============================================================
-- FUTURE WORKSAFE CLAIMS
--
-- WorkSafe Victoria is not loaded yet because its occupation
-- data uses ASCO2 and requires the crosswalk.
--
-- Occupation and body-part/mechanism aggregates must not be
-- joined unless the source actually publishes that joint grain.
--
-- Future constraint:
--
-- CHECK (
--     (dimension_type = 'occupation'
--      AND occupation_id IS NOT NULL)
--     OR
--     (dimension_type <> 'occupation'
--      AND occupation_id IS NULL)
-- )
-- ============================================================


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_injury_frequency_occupation
    ON injury_frequency (
        occupation_id
    );


CREATE INDEX IF NOT EXISTS idx_injury_frequency_year
    ON injury_frequency (
        financial_year
    );


CREATE INDEX IF NOT EXISTS idx_hazard_exposure_occupation
    ON hazard_exposure (
        occupation_id
    );


CREATE INDEX IF NOT EXISTS idx_hazard_exposure_variable
    ON hazard_exposure (
        hazard_variable_id
    );


CREATE INDEX IF NOT EXISTS idx_mobility_flow_source
    ON mobility_flow (
        source_occupation_id,
        financial_year
    );


CREATE INDEX IF NOT EXISTS idx_mobility_flow_destination
    ON mobility_flow (
        destination_occupation_id
    );


CREATE INDEX IF NOT EXISTS idx_occupation_profile_female_share
    ON occupation_profile (
        female_share_pct
    );


CREATE INDEX IF NOT EXISTS idx_occupation_alias_text
    ON occupation_alias (
        lower(alias_text)
    );


CREATE INDEX IF NOT EXISTS idx_pay_gap_parent
    ON pay_gap (
        parent_occupation_id,
        is_headline_cohort
    );


CREATE INDEX IF NOT EXISTS idx_ai_exposure_occupation
    ON ai_exposure (
        occupation_id
    );


CREATE INDEX IF NOT EXISTS idx_nds_category_lookup
    ON nds_category (
        dimension,
        classification,
        level
    );


CREATE INDEX IF NOT EXISTS idx_nds_claim_lookup
    ON nds_claim_statistic (
        nds_category_id,
        financial_year,
        measure
    );


CREATE INDEX IF NOT EXISTS idx_occupation_nds_category
    ON occupation_nds_link (
        nds_category_id
    );


CREATE INDEX IF NOT EXISTS idx_regional_employment_occupation
    ON regional_employment (
        occupation_id,
        reference_date
    );


CREATE INDEX IF NOT EXISTS idx_regional_employment_region
    ON regional_employment (
        region_id,
        reference_date
    );


COMMIT;