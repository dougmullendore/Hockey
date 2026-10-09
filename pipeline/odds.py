"""Each team's chance of winning a game, from a rating built on results.

These are this site's own estimate, not a sportsbook's line.

A rating says how large a share of the goals a team takes against an average
NHL team. Before each game the two ratings (and home ice) give an expected
share of the goals; afterwards both teams move toward what actually happened,
quickly early in the season and slowly later. A team starts a season on part
of last season's rating. The chance of winning the game follows from the
expected share of the goals.

A shootout win counts as one goal, as it does in the final score. A blowout
counts for a little less than its margin: goals beyond ODDS_MARGIN_CAP say
more about an empty net than about the teams.

How it tested is in ODDS_TESTED in config.py and in the README. The settings
were chosen on those same games, so expect slightly worse on new ones.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import config

SEED_FILE = Path(__file__).resolve().parents[1] / "ratings" / "seed.json"


def seed() -> dict:
    """{"season": the season these ratings finished, "ratings": {team: rating}}:
    where teams stood before this site kept its own ratings."""
    return json.loads(SEED_FILE.read_text()) if SEED_FILE.exists() else {}


def goal_share(gap: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, gap))))


def game_chance(home: float, away: float, neutral: bool = False) -> float:
    """The home team's chance of winning the game."""
    gap = home - away + (0.0 if neutral else config.ODDS_HOME)
    return goal_share(config.ODDS_STRETCH * gap)


def capped(hs: int, vs: int) -> tuple[float, float]:
    """The score with the winning margin held to ODDS_MARGIN_CAP goals."""
    cap = config.ODDS_MARGIN_CAP
    if hs - vs > cap:
        return vs + cap, vs
    if vs - hs > cap:
        return hs, hs + cap
    return hs, vs


def rate(games: list[dict], before: dict) -> tuple[dict, dict]:
    """Walk through a season's games in order. `before` is last season's
    final ratings. Returns (ratings now, {game id: the home team's chance as
    it stood before that game was played})."""
    rating, played, pregame = {}, {}, {}
    for g in sorted(games, key=lambda g: (g["date"], g["start"] or 0, g["id"])):
        h, a = g["home"]["id"], g["away"]["id"]
        for t in (h, a):
            if t not in rating:
                rating[t] = config.ODDS_KEEP * before.get(t, 0.0)
        hs, vs = g["home"].get("score"), g["away"].get("score")
        if g["state"] != "final" or hs is None or vs is None or hs == vs:
            continue
        neutral = bool(g.get("neutral"))
        pregame[g["id"]] = game_chance(rating[h], rating[a], neutral)
        hc, vc = capped(hs, vs)
        surprise = hc - (hc + vc) * goal_share(rating[h] - rating[a] + (0.0 if neutral else config.ODDS_HOME))
        for t, sign in ((h, 1.0), (a, -1.0)):
            step = config.ODDS_STEP / (1.0 + played.get(t, 0) / config.ODDS_SETTLE) + config.ODDS_MIN_STEP
            rating[t] += sign * step * surprise
            played[t] = played.get(t, 0) + 1
    return rating, pregame
