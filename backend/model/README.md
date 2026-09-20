# Exposure -> injury model

A research model that predicts an occupation's injury-frequency rate from
its BOHD (Beta Occupational Hazards Dataset) physical-exposure scores.
This directory is the **training** side only - what gets built here is
copied into `model_service/artifacts/` and served by the separate
`model_service/` FastAPI app. See `model_service/artifacts/flow.md` for
what happens to the trained model after this script runs.

## What it predicts, and what it doesn't

- **Input:** 57 BOHD physical-exposure scores per occupation (bending,
  standing, repetitive motion, noise, vibration, and so on - one score
  0-100 per hazard variable).
- **Target:** WCIFR injury frequency rate, averaged across non-suppressed
  years 2014-15 to 2023-24.
- **Output that actually gets used:** a tercile label -
  `"Lower than typical"` / `"About typical"` / `"Higher than typical"` -
  never a raw predicted number.

That last point is the most important thing to know about this model:
its held-out test R^2 is **negative** (see `test` in `metrics.json`),
meaning the actual predicted rate isn't trustworthy enough to show
anyone. What the model *is* good at is **ranking** occupations relative
to each other - test Spearman correlation 0.77, 81% pairwise direction
accuracy. So only that ranking (bucketed into thirds) is ever exposed
downstream. Nothing that consumes this model's output should try to
recover or display the number.

This is a cross-sectional association, not a causal claim and not a
temporal forecast - see `metrics.json`'s `limitations` for the full list
(no body-region-specific labels, not women-specific, related occupations
may share source mappings beyond exact profiles, target is an
across-year average rather than a prediction of any single future year).

## Running it

```bash
python model/train_exposure_model.py --out artifacts/exposure
```

**Requires:** `data/processed/bohd_clean.csv` (the 57 predictor scores,
produced by the BOHD ETL) and `data/processed/wcifr_clean.csv` (the
10-year injury frequency series, produced by the WCIFR ETL) - both
already committed in this repo. Python deps: `pandas`, `numpy`, `scipy`,
`scikit-learn`, `joblib` (all pinned in the repo root `requirements.txt`).

Optional flags: `--bohd-csv` / `--wcifr-csv` to point at different input
files, `--out` to change the output directory (default
`artifacts/exposure`).

## Method, briefly

1. **Candidates:** Ridge regression and Random Forest, each behind
   `impute (median) -> scale -> regress`, wrapped in a
   `TransformedTargetRegressor` with a log1p/expm1 target transform (the
   target is heavily right-skewed - most occupations sit under 5, a
   handful sit above 50).
2. **Model selection:** grouped 5-fold cross-validation on a dev split,
   picking whichever candidate has the lower MAE. Grouped by exposure
   profile (rounded to 2 decimals) so near-duplicate occupations don't
   leak across folds. Currently: **ridge** wins.
3. **Evaluation:** the selected candidate is refit on all of `dev` and
   scored once against a completely untouched `test` split (also grouped
   by profile) - that test score is what's in `metrics.json`'s `test`
   block, and it's the number that matters for judging the model, not the
   cross-validation score.
4. **Final artifact:** refit again on every usable row (`dev` + `test`
   combined) *after* the test score is already recorded, so the deployed
   model uses all available data without that refit ever influencing its
   own evaluation.
5. **Tier thresholds:** the final model scores every BOHD-covered
   occupation (not just the ones with a training target - inference only
   needs features, not a target), and the predictions are split into
   thirds to get the two cutoffs published tiers are based on.

## Output

Four files land in `artifacts/exposure/` (default) - `research_model.joblib`
(the fitted pipeline + feature order), `metrics.json` (full report,
including `tier_thresholds`), and `predictions.csv` / `test_predictions.csv`
(this run's own record, for auditing - not read by any serving code). Only
`research_model.joblib` and `metrics.json` need to be copied into
`model_service/artifacts/` for serving; see that directory's `flow.md` for
why both files (not just the joblib) are required.

## Retraining

There's no automation for this yet. To retrain and redeploy:

1. Run the command above.
2. Review the new `metrics.json` - compare `test` and `test_pairs` against
   the previous run before trusting a new model more than the old one.
3. Copy the new `research_model.joblib` and `metrics.json` into
   `model_service/artifacts/`, overwriting the old copies.
4. Restart (or redeploy) `model_service/` to pick up the new artifact -
   it's loaded once at process start, not reloaded per request.
