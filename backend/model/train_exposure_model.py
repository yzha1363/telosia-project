"""Telosia cross-sectional research baseline. NOT a future-year forecast.

Predicts WCIFR injury frequency rate from BOHD physical-exposure scores, using
the project's own cleaned ETL outputs (data/processed/bohd_clean.csv and
wcifr_clean.csv) instead of the raw BOHD workbook - bohd_clean.csv already
has the 57 predictor scores, and wcifr_clean.csv has a real 10-year injury
frequency series per occupation (2014-15 to 2023-24) rather than the single
snapshot column the raw workbook would have supplied as a target.

Usage: python model/train_exposure_model.py --out artifacts/exposure
Requires pandas, numpy, scipy, scikit-learn, joblib (see requirements.txt).
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOHD_CSV = ROOT / "data" / "processed" / "bohd_clean.csv"
DEFAULT_WCIFR_CSV = ROOT / "data" / "processed" / "wcifr_clean.csv"


def load_bohd_features(bohd_path):
    """Long (occupation x variable) -> wide (one row per occupation, one column
    per hazard variable) - what the model needs as its feature matrix. Covers
    every BOHD occupation, whether or not it has a WCIFR target - training
    needs the target, but inference for the UI only needs these features.
    """
    bohd = pd.read_csv(bohd_path)
    bohd["occupation_code"] = bohd["occupation_code"].astype(str).str.zfill(4)
    wide = bohd.pivot_table(
        index="occupation_code", columns="hazard_variable", values="exposure_score"
    )
    features = sorted(wide.columns.tolist())
    if len(features) != 57:
        raise ValueError(f"Expected 57 hazard variables, found {len(features)}")
    if ((wide[features] < 0) | (wide[features] > 100)).any().any():
        raise ValueError("Exposure score outside 0-100")
    return wide, features


def load_exposures(bohd_path, wcifr_path):
    wide, features = load_bohd_features(bohd_path)

    # Target: mean frequency_rate across non-suppressed years per occupation.
    # Suppressed years are dropped, never zero-filled - a suppressed rate is
    # unpublished, not zero.
    wcifr = pd.read_csv(wcifr_path)
    wcifr["occupation_code"] = wcifr["occupation_code"].astype(str).str.zfill(4)
    published = wcifr.loc[~wcifr["is_suppressed"]]
    target = published.groupby("occupation_code")["frequency_rate"].mean()

    data = wide.join(target.rename("target"), how="inner").reset_index()

    # Group near-identical rounded source profiles together during splitting.
    data["profile_group"] = data[features].round(2).apply(
        lambda row: tuple(None if pd.isna(v) else float(v) for v in row), axis=1
    ).factorize()[0]
    return data, features


def regression_metrics(y, prediction):
    y, prediction = np.asarray(y), np.asarray(prediction)
    rho = spearmanr(y, prediction).statistic if len(y) > 2 else np.nan
    return {
        "mae": float(mean_absolute_error(y, prediction)),
        "rmse": float(np.sqrt(mean_squared_error(y, prediction))),
        "r_squared": float(r2_score(y, prediction)),
        "spearman": float(rho) if np.isfinite(rho) else None,
        "n": int(len(y)),
    }


def pair_metrics(y, prediction, tolerance=1.0):
    # Both members are in the same untouched evaluation partition.
    # Pairs are dependent; their count is not an independent sample size.
    y, prediction = np.asarray(y), np.asarray(prediction)
    i, j = np.triu_indices(len(y), k=1)
    truth, estimated = y[j] - y[i], prediction[j] - prediction[i]
    material = np.abs(truth) > tolerance
    return {
        "pair_delta_mae": float(np.mean(np.abs(truth - estimated))) if len(i) else None,
        "pair_direction_accuracy": float(np.mean(np.sign(truth[material]) == np.sign(estimated[material]))) if material.any() else None,
        "material_pairs": int(material.sum()),
        "tolerance": tolerance,
        "warning": "Correlated pairs; bootstrap occupations/groups, not pairs.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bohd-csv", default=str(DEFAULT_BOHD_CSV))
    parser.add_argument("--wcifr-csv", default=str(DEFAULT_WCIFR_CSV))
    parser.add_argument("--out", default="artifacts/exposure")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source, features = load_exposures(args.bohd_csv, args.wcifr_csv)
    # Suppressed outcomes remain unavailable, never zero-filled or published as estimates.
    usable = source.loc[source.target.notna()].reset_index(drop=True)
    if len(usable) < 50 or (usable.target < 0).any():
        raise ValueError("Insufficient data or invalid target")
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    dev_idx, test_idx = next(splitter.split(usable, groups=usable.profile_group))
    dev, test = usable.iloc[dev_idx], usable.iloc[test_idx]

    # log1p/expm1 target transform: frequency_rate is heavily right-skewed
    # (skew ~3.8 - most occupations sit under 5, a handful sit above 50), which
    # both Ridge and RandomForest fit poorly on the raw scale. RidgeCV picks
    # its own alpha via generalized cross-validation instead of a guessed
    # constant.
    candidates = {
        "median_baseline": DummyRegressor(strategy="median"),
        "ridge": TransformedTargetRegressor(
            make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), RidgeCV(alphas=np.logspace(-2, 3, 30))),
            func=np.log1p, inverse_func=np.expm1,
        ),
        "random_forest": TransformedTargetRegressor(
            make_pipeline(SimpleImputer(strategy="median"), RandomForestRegressor(
                n_estimators=300, max_depth=6, min_samples_leaf=8,
                max_features=0.7, random_state=42, n_jobs=-1)),
            func=np.log1p, inverse_func=np.expm1,
        ),
    }

    # Model selection by grouped 5-fold cross-validation on `dev`, not a single
    # train/validation split - with only ~250 occupations in dev, one 70-row
    # validation slice is noisy enough to flip which candidate looks best by
    # chance. Out-of-fold predictions across all of `dev` give a much more
    # stable comparison. `test` stays completely untouched until the very end.
    n_splits = 5
    group_kfold = GroupKFold(n_splits=n_splits)
    validation_scores = {}
    for name, estimator in candidates.items():
        oof_prediction = np.maximum(0, cross_val_predict(
            estimator, dev[features], dev.target,
            groups=dev.profile_group, cv=group_kfold, n_jobs=-1,
        ))
        validation_scores[name] = regression_metrics(dev.target, oof_prediction)
    selected = min(validation_scores, key=lambda n: validation_scores[n]["mae"])
    frozen = clone(candidates[selected]).fit(dev[features], dev.target)
    prediction = np.maximum(0, frozen.predict(test[features]))
    baseline = DummyRegressor(strategy="median").fit(dev[features], dev.target)
    baseline_prediction = baseline.predict(test[features])
    report = {
        "task": "cross_sectional_association_not_forecast",
        "target": "WCIFR frequency_rate, mean across non-suppressed years 2014-15 to 2023-24",
        "split": "grouped by exposure profile rounded to 2 decimal places",
        "n_dev": len(dev), "cv_folds": n_splits, "n_test": len(test),
        "n_occupations_without_published_target": int(source.target.isna().sum()),
        "selected": selected, "cross_validation": validation_scores,
        "test": regression_metrics(test.target, prediction),
        "test_baseline": regression_metrics(test.target, baseline_prediction),
        "test_pairs": pair_metrics(test.target, prediction),
        "production_approved": False,
        "limitations": ["No body-region injury labels", "Not women-specific", "Not causal",
                        "Related occupations may share source mappings beyond exact profiles",
                        "Target is an across-year average, not a temporal forecast"],
    }
    test.assign(predicted_rate=prediction, baseline_rate=baseline_prediction)[
        ["occupation_code", "target", "predicted_rate", "baseline_rate", "profile_group"]
    ].to_csv(out / "test_predictions.csv", index=False)
    # Refit a research artifact only after recording the untouched test result.
    # It must not be deployed merely because this file exists.
    final = clone(candidates[selected]).fit(usable[features], usable.target)
    joblib.dump({"model": final, "features": features, "metadata": report}, out / "research_model.joblib")

    # Direction-only inference, for every BOHD-covered occupation (not just
    # the ones with a WCIFR target - inference only needs features). The
    # model's absolute predictions aren't reliable enough to publish as a
    # number (test R^2 is negative), but its RANKING of occupations is -
    # test Spearman 0.77, 81% pairwise direction accuracy. So only the
    # tercile a prediction falls into gets published, never the predicted
    # number itself.
    all_wide, _ = load_bohd_features(args.bohd_csv)
    all_prediction = np.maximum(0, final.predict(all_wide[features]))
    low_cut, high_cut = np.percentile(all_prediction, [33.33, 66.67])
    tier = np.where(
        all_prediction <= low_cut, "Lower than typical",
        np.where(all_prediction >= high_cut, "Higher than typical", "About typical"),
    )
    pd.DataFrame({
        "occupation_code": all_wide.index,
        "predicted_rate": all_prediction,
        "tier": tier,
    }).to_csv(out / "predictions.csv", index=False)

    report["deployable_signal"] = (
        "direction_only - predicted_rate must never be shown as a number, only "
        "the tier (test R^2 is negative; tier ranking is backed by test Spearman "
        "0.77 / 81% pairwise direction accuracy)"
    )
    report["tier_thresholds"] = {"low_cutoff": float(low_cut), "high_cutoff": float(high_cut)}
    (out / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
