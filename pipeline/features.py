"""Describe every shot with the things that make it more or less dangerous.

Input: the tidy events table. Output: one row per unblocked shot attempt
(goals, saved shots and misses) with the features the expected-goals model
uses. Blocked shots are left out because the feed records where the block
happened, not where the shot was taken from."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

UNBLOCKED = ("goal", "shot-on-goal", "missed-shot")

SHOT_TYPE_LEVELS = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected",
                    "wrap-around", "bat", "poke", "between-legs", "cradle", "unknown"]
PREV_TYPE_LEVELS = ["faceoff", "hit", "giveaway", "takeaway", "shot-on-goal",
                    "missed-shot", "blocked-shot", "goal", "penalty", "other"]

# Order matters: the model is trained on exactly these columns.
FEATURES = [
    "dist", "angle", "x_adj", "y_abs", "shot_type_code",
    "shooter_skaters", "defender_skaters", "empty_net", "extra_attacker",
    "score_diff", "period", "period_seconds", "is_home", "is_playoff",
    "prev_type_code", "prev_same_team", "secs_since_prev", "dist_from_prev",
    "speed_from_prev", "prev_x", "prev_y_abs", "angle_change", "rebound", "rush",
    "secs_since_faceoff",
]
CATEGORICAL = ["shot_type_code", "prev_type_code"]

# Penalty shots are one-on-one and are not modelled; they get a flat value
# (the league converts roughly one in three).
PENALTY_SHOT_XG = 0.32


def _code(series: pd.Series, levels: list[str], other: str) -> np.ndarray:
    lookup = {v: i for i, v in enumerate(levels)}
    return series.map(lookup).fillna(lookup[other]).astype("int16").to_numpy()


def build_shots(events: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """One row per unblocked shot attempt, with model features attached."""
    ev = events.sort_values(["game_id", "idx"], kind="stable").reset_index(drop=True)

    # ---- the previous event with a location, within the same period -------
    has_xy = ev["x_adj"].notna() & ev["team_id"].notna()
    loc = ev[has_xy]
    grp = [loc["game_id"], loc["period"]]
    prev = pd.DataFrame({
        "prev_type": loc.groupby(grp)["type"].shift(1),
        "prev_team": loc.groupby(grp)["team_id"].shift(1),
        "prev_secs": loc.groupby(grp)["game_seconds"].shift(1),
        "prev_xa": loc.groupby(grp)["x_adj"].shift(1),
        "prev_ya": loc.groupby(grp)["y_adj"].shift(1),
    }, index=loc.index)
    ev = ev.join(prev)

    # ---- seconds since the last faceoff in the period --------------------
    fo_time = ev["game_seconds"].where(ev["type"] == "faceoff")
    ev["last_faceoff"] = fo_time.groupby([ev["game_id"], ev["period"]]).ffill()

    s = ev[ev["type"].isin(UNBLOCKED) & (ev["period_type"] != "SO") & ev["x_adj"].notna()].copy()
    if not len(s):
        return pd.DataFrame(columns=["game_id", "idx", "goal", *FEATURES])

    f = lambda c: s[c].astype("float64")  # noqa: E731
    x, y = f("x_adj"), f("y_adj")
    dx = config.GOAL_X - x
    s["dist"] = np.hypot(dx, y)
    s["angle"] = np.degrees(np.arctan2(np.abs(y), dx))  # 0 = dead centre
    s["y_abs"] = np.abs(y)
    s["x_adj"] = x
    s["y_adj"] = y

    home = s["is_home"].astype("float64") == 1
    hs, as_ = f("home_skaters"), f("away_skaters")
    hg, ag = f("home_goalie_in"), f("away_goalie_in")
    s["shooter_skaters"] = np.where(home, hs, as_)
    s["defender_skaters"] = np.where(home, as_, hs)
    s["empty_net"] = np.where(home, ag, hg) == 0
    s["extra_attacker"] = np.where(home, hg, ag) == 0
    # penalty shots: nobody on the ice but shooter and goalie
    s["penalty_shot"] = s["situation"].isin(["0101", "1010"])
    # an empty-net flag is only believable if no goalie is credited
    s["empty_net"] = (s["empty_net"] & s["goalie_id"].isna()).astype("int8")
    s["extra_attacker"] = s["extra_attacker"].astype("int8")

    diff = f("home_score") - f("away_score")
    s["score_diff"] = np.clip(np.where(home, diff, -diff), -3, 3)
    s["period"] = np.clip(f("period"), 1, 5)
    s["period_seconds"] = f("period_seconds")
    s["is_home"] = home.astype("int8")

    s["shot_type_code"] = _code(s["shot_type"], SHOT_TYPE_LEVELS, "unknown")
    pt = s["prev_type"].where(s["prev_type"].isin(PREV_TYPE_LEVELS[:-1]), "other")
    s["prev_type_code"] = _code(pt, PREV_TYPE_LEVELS, "other")

    same = (s["prev_team"].astype("float64") == s["team_id"].astype("float64"))
    s["prev_same_team"] = same.astype("int8")
    secs = (f("game_seconds") - s["prev_secs"].astype("float64")).clip(lower=0)
    s["secs_since_prev"] = secs.fillna(60).clip(upper=60)
    # put the previous event in the shooter's frame of reference
    sign = np.where(same, 1.0, -1.0)
    px = s["prev_xa"].astype("float64") * sign
    py = s["prev_ya"].astype("float64") * sign
    s["prev_x"] = px
    s["prev_y_abs"] = np.abs(py)
    d_prev = np.hypot(x - px, y - py)
    s["dist_from_prev"] = d_prev
    s["speed_from_prev"] = (d_prev / s["secs_since_prev"].clip(lower=0.5)).clip(upper=200)

    prev_angle = np.degrees(np.arctan2(py, config.GOAL_X - px))
    this_angle = np.degrees(np.arctan2(y, dx))
    is_reb = same & s["prev_type"].isin(["shot-on-goal", "missed-shot"]) & (secs <= 3)
    s["rebound"] = is_reb.astype("int8")
    s["angle_change"] = np.where(is_reb, np.abs(this_angle - prev_angle), 0.0)
    s["rush"] = ((secs <= 4) & (px < 25) & ~s["prev_type"].isin(["faceoff"])).astype("int8")
    s["secs_since_faceoff"] = (f("game_seconds") - s["last_faceoff"].astype("float64")).clip(0, 120).fillna(120)

    gtype = games.set_index("game_id")["game_type"]
    s["game_type"] = s["game_id"].map(gtype).astype("Int64")
    s["is_playoff"] = (s["game_type"] == 3).astype("int8")
    s["goal"] = (s["type"] == "goal").astype("int8")
    s["on_goal"] = s["type"].isin(["goal", "shot-on-goal"]).astype("int8")
    s["shooter_id"] = s["player1_id"]

    keep = ["game_id", "idx", "game_type", "period", "game_seconds", "team_id",
            "shooter_id", "goalie_id", "type", "goal", "on_goal", "penalty_shot",
            "shot_type", "situation", "y_adj", *[c for c in FEATURES if c != "period"]]
    return s[keep].reset_index(drop=True)


def strength(shots: pd.DataFrame) -> pd.Series:
    """Label each shot's manpower situation from the shooter's side.

    PS  penalty shot            EN  shooting at an empty net
    EA  shooter's goalie pulled for an extra attacker
    5v5 full strength           PP  power play        SH  shorthanded
    EV  other even strength (4-on-4, 3-on-3 overtime)"""
    a = shots["shooter_skaters"].astype("float64")
    b = shots["defender_skaters"].astype("float64")
    out = np.select(
        [shots["penalty_shot"].to_numpy(bool), (shots["empty_net"] == 1).to_numpy(),
         (shots["extra_attacker"] == 1).to_numpy(), (a == 5) & (b == 5), a > b, a < b],
        ["PS", "EN", "EA", "5v5", "PP", "SH"], default="EV")
    return pd.Series(out, index=shots.index)
