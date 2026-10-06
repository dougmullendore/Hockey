"""The expected-goals (xG) model.

xG answers: "given where and how this shot was taken, how often does a shot
like it go in?"  A shot from the slot on a rebound might be worth 0.30, a
point shot through traffic 0.02. Adding up xG tells you how many goals a
team, skater or goalie "should" have had from the chances that occurred.

The model is gradient-boosted decision trees trained on every unblocked
shot attempt from the most recent completed seasons.

Two details keep the numbers honest:

* A model partly "remembers" the shots it was trained on, which would
  flatter every shooter and goalie in those seasons. So the training games
  are split into five groups, and each group is scored by a copy of the
  model that never saw it. New games are scored by the full model.
* The model is first tested on a whole season it has never seen, and that
  report is published on the site's About page."""
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
N_FOLDS = 5
MIN_GAMES_PER_SEASON = 1000  # refuse to train on a partial download


def season_shots(data: Path, season: int) -> pd.DataFrame:
    games = store.read(data, "games", season)
    if not len(games):
        return pd.DataFrame()
    shots = features.build_shots(store.read(data, "events", season), games)
    shots["season"] = season
    return shots


def train_seasons(data: Path) -> list[int]:
    """The newest completed seasons we hold in full."""
    manifest = store.read_json(Path(data) / "manifest.json", {}) or {}
    done = [s for s in config.SEASONS
            if manifest.get(str(s), {}).get("complete")
            and manifest[str(s)].get("games", 0) >= MIN_GAMES_PER_SEASON]
    return done[-config.XG_TRAIN_SEASON_COUNT:]


def _trainable(shots: pd.DataFrame) -> pd.DataFrame:
    return shots[~shots["penalty_shot"].astype(bool)]


def _fold(game_ids) -> np.ndarray:
    return (np.asarray(game_ids, dtype="int64") % N_FOLDS).astype("int64")


def _weights(train: pd.DataFrame) -> np.ndarray:
    """Newest season counts fully; each season before it counts for less."""
    order = sorted(train["season"].unique())
    age = train["season"].map({s: len(order) - 1 - i for i, s in enumerate(order)})
    return np.power(config.XG_SEASON_DECAY, age.to_numpy("float64"))


def _fit(train: pd.DataFrame, max_iter: int | None = None):
    params = dict(PARAMS)
    if max_iter:  # reuse the tree count found with early stopping
        params.update(max_iter=max_iter, early_stopping=False)
    cat = [features.FEATURES.index(c) for c in features.CATEGORICAL]
    model = HistGradientBoostingClassifier(categorical_features=cat, **params)
    model.fit(train[features.FEATURES].to_numpy("float64"), train["goal"].to_numpy(),
              sample_weight=_weights(train))
    return model


def _raw(model, shots: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(shots[features.FEATURES].to_numpy("float64"))[:, 1]


def predict(blob: dict, shots: pd.DataFrame, season: int) -> np.ndarray:
    """xG for every row of one season's shots table."""
    if not len(shots):
        return np.array([])
    if season in blob.get("train_seasons", []) and blob.get("folds"):
        # each game is scored by the copy of the model that never saw it
        xg = np.zeros(len(shots))
        fold = _fold(shots["game_id"])
        for k, model in enumerate(blob["folds"]):
            m = fold == k
            if m.any():
                xg[m] = _raw(model, shots[m])
    else:
        xg = _raw(blob["final"], shots)
    return np.where(shots["penalty_shot"].to_numpy(bool), features.PENALTY_SHOT_XG, xg)


def season_scale(shots: pd.DataFrame, raw_xg: np.ndarray, prior_scale: float = 1.0,
                 prior_weight: float = 0.0) -> tuple[np.ndarray, float]:
    """Rescale a season so league xG matches league goals.

    Scoring conditions and record-keeping shift a few percent from year to
    year. After scaling, an exactly average goalie has zero goals saved above
    expected in that season. Only shots at a goalie are scaled. While a
    season is in progress, `prior_weight` expected goals at last season's
    scale keep the factor from swinging on a handful of games."""
    live = (shots["empty_net"].to_numpy() == 0) & ~shots["penalty_shot"].to_numpy(bool)
    goals, total = float(shots["goal"].to_numpy()[live].sum()), float(raw_xg[live].sum())
    if total + prior_weight <= 0:
        return raw_xg, 1.0
    scale = (goals + prior_weight * prior_scale) / (total + prior_weight)
    return np.where(live, np.clip(raw_xg * scale, 0.0, 0.99), raw_xg), scale


# ------------------------------------------------------------- reporting --
def _metrics(y, p) -> dict:
    base = float(np.mean(y))
    return {
        "shots": int(len(y)), "goals": int(np.sum(y)), "xg": round(float(np.sum(p)), 1),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 5),
        "baseline_log_loss": round(float(log_loss(y, np.full(len(y), base), labels=[0, 1])), 5),
        "auc": round(float(roc_auc_score(y, p)), 4) if 0 < np.sum(y) < len(y) else None,
        "brier": round(float(brier_score_loss(y, p)), 5),
    }


def _calibration(y, p, bins=10) -> list[dict]:
    """Group shots by predicted xG and compare with how many went in."""
    order = np.argsort(p)
    return [{"shots": int(len(c)), "avg_xg": round(float(p[c].mean()), 4),
             "goal_rate": round(float(y[c].mean()), 4)}
            for c in np.array_split(order, bins) if len(c)]


def evaluate(model, test: pd.DataFrame) -> dict:
    t = _trainable(test)
    y, p = t["goal"].to_numpy(), _raw(model, t)
    rep = {"overall": _metrics(y, p), "calibration": _calibration(y, p)}
    st = features.strength(t).to_numpy()
    rep["by_strength"] = {}
    for label in ["5v5", "PP", "SH", "EV", "EA", "EN"]:
        m = st == label
        if m.sum() > 200 and 0 < y[m].sum() < m.sum():
            rep["by_strength"][label] = _metrics(y[m], p[m])
    goalie = t["empty_net"].to_numpy() == 0
    rep["goalie_in_net"] = _metrics(y[goalie], p[goalie])
    scaled, scale = season_scale(t, p)
    rep["season_scale"] = round(scale, 4)
    rep["goalie_in_net_scaled"] = _metrics(y[goalie], scaled[goalie])
    rep["calibration_scaled"] = _calibration(y[goalie], scaled[goalie])
    return rep


# --------------------------------------------------------------- training --
def train(data: Path, seasons: list[int], log) -> dict:
    """Test on a held-out season, then fit the fold models and the full one."""
    if len(seasons) < 2:
        raise RuntimeError("the model needs at least two completed seasons; "
                           f"only {seasons} are stored in full so far")
    frames = {}
    for s in seasons:
        frames[s] = season_shots(data, s)
        log(f"xG: season {s}: {frames[s]['game_id'].nunique()} games, {len(frames[s]):,} unblocked shots")

    test_season = seasons[-1]
    earlier = _trainable(pd.concat([f for s, f in frames.items() if s != test_season], ignore_index=True))
    held_out = _fit(earlier)
    trees = int(held_out.n_iter_)
    report = evaluate(held_out, frames[test_season])
    report.update(test_season=test_season, trees=trees)
    log(f"xG: tested on unseen season {test_season}: {report['overall']}")

    everything = _trainable(pd.concat(list(frames.values()), ignore_index=True))
    fold = _fold(everything["game_id"])
    folds = []
    oof = np.zeros(len(everything))
    for k in range(N_FOLDS):
        m = _fit(everything[fold != k], max_iter=trees)
        if (fold == k).any():
            oof[fold == k] = _raw(m, everything[fold == k])
        folds.append(m)
        log(f"xG: fold {k + 1}/{N_FOLDS} fitted")
    y = everything["goal"].to_numpy()
    report["out_of_fold"] = _metrics(y, oof)
    report["out_of_fold_calibration"] = _calibration(y, oof)
    log(f"xG: out-of-fold over all training seasons: {report['out_of_fold']}")
    final = _fit(everything, max_iter=trees)

    report.update(
        version=config.XG_MODEL_VERSION, train_seasons=seasons,
        train_shots=int(len(everything)), train_goals=int(everything["goal"].sum()),
        features=features.FEATURES, sklearn=sklearn.__version__,
    )
    (data / "model").mkdir(parents=True, exist_ok=True)
    joblib.dump({"final": final, "folds": folds, "features": features.FEATURES,
                 "version": config.XG_MODEL_VERSION, "train_seasons": seasons},
                data / "model" / "xg.joblib", compress=3)
    store.write_json(data / "model" / "xg_report.json", report)
    return report


def load(data: Path) -> dict | None:
    """The stored model, or None if there is none that this code can use."""
    path = Path(data) / "model" / "xg.joblib"
    if not path.exists():
        return None
    try:
        blob = joblib.load(path)
    except Exception:
        return None
    if blob.get("version") != config.XG_MODEL_VERSION or blob.get("features") != features.FEATURES:
        return None
    return blob


def ensure_model(data: Path, log) -> dict:
    """Train the model if there is none, or a new season has been completed."""
    data = Path(data)
    wanted = train_seasons(data)
    blob = load(data)
    if blob is not None and (blob.get("train_seasons") == wanted or len(wanted) < 2):
        rep = store.read_json(data / "model" / "xg_report.json", {}) or {}
        return {"trained": False, "version": config.XG_MODEL_VERSION,
                "seasons": blob.get("train_seasons"), "auc": rep.get("overall", {}).get("auc")}
    rep = train(data, wanted, log)
    return {"trained": True, "version": config.XG_MODEL_VERSION, "seasons": wanted,
            "auc": rep["overall"]["auc"]}
