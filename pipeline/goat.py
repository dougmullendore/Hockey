"""The GOAT ranking: the site's own order of the 32 teams.

Five things decide it:
  1. record: the share of the possible points a team has won;
  2. strength of schedule: the average rating of the teams it has played so
     far (the ratings behind the odds), each game counted once;
  3. expected-goal share: of the expected goals in its games, the share that
     were its own (see pipeline/xg.py); this says who has had the better
     chances, whatever the bounces;
  4. goal share: of the goals in its games, the share it scored (a shootout
     win is not a goal);
  5. a hot streak: a team that has won its last few games gets a boost.

For each of the first four a team gets its place among all the teams, from 0
at the bottom to 1 at the top (teams level with each other share a place).
Those are combined with the weights in GOAT_WEIGHTS. A team on a winning
streak of GOAT_HOT_FROM games or more then gets GOAT_HOT_STEP added for each
win in the streak, up to GOAT_HOT_MAX. Highest total first.
"""
from __future__ import annotations

import bisect

from . import config


def _placement(values: dict) -> dict:
    """Each value's place among all of them, 0 (lowest) to 1 (highest); ties share."""
    xs = sorted(values.values())
    n = len(xs) or 1
    return {k: (bisect.bisect_left(xs, v) + 0.5 * (bisect.bisect_right(xs, v) - bisect.bisect_left(xs, v))) / n
            for k, v in values.items()}


def played(games: list[dict]) -> list[dict]:
    return [g for g in sorted(games, key=lambda g: (g["date"], g["start"] or 0, g["id"]))
            if g["state"] == "final" and g["home"].get("score") is not None and g["away"].get("score") is not None
            and g["home"]["score"] != g["away"]["score"]]


def win_streaks(games: list[dict]) -> dict:
    """{team: how many games in a row it has won, up to its latest game}."""
    streak = {}
    for g in played(games):
        home_won = g["home"]["score"] > g["away"]["score"]
        for side, won in (("home", home_won), ("away", not home_won)):
            t = g[side]["id"]
            streak[t] = streak.get(t, 0) + 1 if won else 0
    return streak


def hot_boost(streak: int) -> float:
    if streak < config.GOAT_HOT_FROM:
        return 0.0
    return min(config.GOAT_HOT_MAX, config.GOAT_HOT_STEP * streak)


def rank(games: list[dict], rating: dict, table: list[dict], xg: dict) -> dict:
    """Rank the teams in `table` (the standings rows). `games` are the games
    that count; `rating` is every team's rating from pipeline/odds.py; `xg` is
    {team: [expected goals for, against]} over the games with play-by-play.
    Returns {"order": [ids, best first], "score": {id: total}, and per team
    "record", "sos", "xg_pct", "goal_pct" (the raw numbers), "streak" and "boost"}."""
    teams = [t["id"] for t in table]
    floor = min(rating.values()) if rating else 0.0
    opp, gf, ga = {t: [] for t in teams}, dict.fromkeys(teams, 0), dict.fromkeys(teams, 0)
    for g in played(games):
        shootout = g.get("end") == "SO"
        for side, other in (("home", "away"), ("away", "home")):
            t = g[side]["id"]
            if t not in opp:
                continue
            mine, theirs = g[side]["score"], g[other]["score"]
            opp[t].append(rating.get(g[other]["id"], floor))
            gf[t] += mine - (1 if shootout and mine > theirs else 0)
            ga[t] += theirs - (1 if shootout and theirs > mine else 0)
    record = {t["id"]: t["pct"] if t["gp"] else 0.5 for t in table}
    sos = {t: sum(opp[t]) / len(opp[t]) if opp[t] else 0.0 for t in teams}
    goal_pct = {t: gf[t] / (gf[t] + ga[t]) if gf[t] + ga[t] else 0.5 for t in teams}
    xg_pct = {t: xg[t][0] / (xg[t][0] + xg[t][1]) if t in xg and xg[t][0] + xg[t][1] > 0 else 0.5 for t in teams}
    w = config.GOAT_WEIGHTS
    place = {"record": _placement(record), "sos": _placement(sos), "xg": _placement(xg_pct), "goals": _placement(goal_pct)}
    streak = win_streaks(games)
    boost = {t: hot_boost(streak.get(t, 0)) for t in teams}
    score = {t: sum(w[k] * place[k][t] for k in w) + boost[t] for t in teams}
    standing = {t["id"]: t["rank"] for t in table}
    order = sorted(teams, key=lambda t: (-score[t], standing[t]))
    return {"order": order, "score": score, "record": record, "sos": sos, "xg_pct": xg_pct, "goal_pct": goal_pct,
            "streak": {t: streak.get(t, 0) for t in teams}, "boost": boost}
