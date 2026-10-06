"""The expected-goals (xG) model.

xG answers: "given where and how this shot was taken, how often does a shot
like it go in?"  A shot from the slot on a rebound might be worth 0.30, a
point shot through traffic 0.02. Adding up xG tells you how many goals a
team, skater or goalie "should" have had from the chances that occurred.

The model is gradient-boosted decision trees trained on every unblocked
shot attempt from the seasons in config.XG_TRAIN_SEASONS."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from . import config, features, store

PARAMS = dict(
    learning_rate=0.05, max_iter=1500, max_leaf_nodes=40, min_samples_leaf=150,
    l2_regularization=2.0, early_stopping=True, validation_fraction=0.1,
    n_iter_no_change=40, random_state=7,
)


MIN_GAMES_PER_SEASON = 1000  # refuse to train on a partial download


def season_shots(data: Path, season: int) -> pd.DataFrame:
    games = store.read(data, "games", season)
    if not len(games):
        return pd.DataFrame()
    shots = features.build_shots(store.read(data, "events", season), games)
    shots["season"] = season
    return shots


def _trainable(shots: pd.DataFrame) -> pd.DataFrame:
    return shots[~shots["penalty_shot"].astype(bool)]


def _fit(train: pd.DataFrame, max_iter: int | None = None):
    params = dict(PARAMS)
    if max_iter:  # final fit: reuse the tree count found with early stopping
        params.update(max_iter=max_iter, early_stopping=False)
    cat = [features.FEATURES.index(c) for c in features.CATEGORICAL]
    model = HistGradientBoostingClassifier(categorical_features=cat, **params)
    model.fit(train[features.FEATURES].to_numpy("float64"), train["goal"].to_numpy())
    return model


def predict(model, shots: pd.DataFrame) -> np.ndarray:
    """xG for every row of a shots table (penalty shots get a flat value)."""
    if not len(shots):
        return np.array([])
    xg = model.predict_proba(shots[features.FEATURES].to_numpy("float64"))[:, 1]
    return np.where(shots["penalty_shot"].to_numpy(bool), features.PENALTY_SHOT_XG, xg)


def _metrics(y, p) -> dict:
    base = float(np.mean(y))
    return {
        "shots": int(len(y)), "goals": int(np.sum(y)), "xg": round(float(np.sum(p)), 1),
        "log_loss": round(float(log_loss(y, p)), 5),
        "baseline_log_loss": round(float(log_loss(y, np.full(len(y), base))), 5),
        "auc": round(float(roc_auc_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
    }


def _calibration(y, p, bins=10) -> list[dict]:
    """Group shots by predicted xG and compare with how many went in."""
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        out.append({
            "shots": int(len(chunk)),
            "avg_xg": round(float(p[chunk].mean()), 4),
            "goal_rate": round(float(y[chunk].mean()), 4),
        })
    return out


def evaluate(model, test: pd.DataFrame) -> dict:
    t = _trainable(test)
    y, p = t["goal"].to_numpy(), predict(model, t)
    rep = {"overall": _metrics(y, p), "calibration": _calibration(y, p)}
    st = features.strength(t).to_numpy()
    rep["by_strength"] = {}
    for label in ["5v5", "PP", "SH", "EV", "EA", "EN"]:
        m = st == label
        if m.sum() > 200 and 0 < y[m].sum() < m.sum():
            rep["by_strength"][label] = _metrics(y[m], p[m])
    goalie = t["empty_net"].to_numpy() == 0
    rep["goalie_in_net"] = _metrics(y[goalie], p[goalie])
    return rep


def train(data: Path, log) -> dict:
    """Fit, test on a held-out season, then refit on everything."""
    frames = {}
    for s in config.XG_TRAIN_SEASONS:
        sh = season_shots(data, s)
        n_games = sh["game_id"].nunique() if len(sh) else 0
        log(f"xG: season {s}: {n_games} games, {len(sh):,} unblocked shots")
        if n_games < MIN_GAMES_PER_SEASON:
            raise RuntimeError(f"season {s} has only {n_games} games stored; "
                               "the model needs the full history first")
        frames[s] = sh

    test_season = config.XG_TEST_SEASON
    tr = _trainable(pd.concat([f for s, f in frames.items() if s != test_season], ignore_index=True))
    held_out = _fit(tr)
    report = evaluate(held_out, frames[test_season])
    report["test_season"] = test_season
    report["trees"] = int(held_out.n_iter_)
    log(f"xG: held-out {test_season}: {report['overall']}")

    everything = _trainable(pd.concat(list(frames.values()), ignore_index=True))
    final = _fit(everything, max_iter=int(held_out.n_iter_))
    report.update(
        version=config.XG_MODEL_VERSION, train_seasons=config.XG_TRAIN_SEASONS,
        train_shots=int(len(everything)), train_goals=int(everything["goal"].sum()),
        features=features.FEATURES, sklearn=sklearn.__version__,
    )
    (data / "model").mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": features.FEATURES,
                 "version": config.XG_MODEL_VERSION}, data / "model" / "xg.joblib", compress=3)
    store.write_json(data / "model" / "xg_report.json", report)
    return report


def load(data: Path):
    path = Path(data) / "model" / "xg.joblib"
    if not path.exists():
        return None
    try:
        blob = joblib.load(path)
    except Exception:
        return None
    if blob.get("version") != config.XG_MODEL_VERSION or blob.get("features") != features.FEATURES:
        return None
    return blob["model"]


def ensure_model(data: Path, log) -> dict:
    """Train the model if we do not have a current one."""
    data = Path(data)
    if load(data) is not None:
        rep = store.read_json(data / "model" / "xg_report.json", {}) or {}
        return {"trained": False, "version": config.XG_MODEL_VERSION,
                "auc": rep.get("overall", {}).get("auc")}
    rep = train(data, log)
    return {"trained": True, "version": config.XG_MODEL_VERSION, "auc": rep["overall"]["auc"]}
