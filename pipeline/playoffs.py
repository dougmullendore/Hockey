"""Playoff odds: each team's chance of making the playoffs, of reaching each
round and of winning the Stanley Cup, and where it is likely to finish.

The rest of the regular season is played out PLAYOFF_SIMS times and the
playoffs after it, and the page shows how often each thing happened.

Each coming game is decided by the same chance of winning the Games page
shows (pipeline/odds.py). About two games in nine go past regulation (the
loser then gets a point), a third of those to a shootout, and past regulation
the game is much closer to a coin toss; those shares are counted from five
seasons of results (PLAYOFF_* in config.py).

Nobody knows exactly how good a team is, least of all in October, and teams
change over a season. So each time the season is played out, every team's
rating is first moved up or down by a random amount: a lot at the start of
the season, less as the games pile up (PLAYOFF_SPREAD_*). Without this the
odds would be far too sure of themselves early on. How that tested on past
seasons is in PLAYOFF_TESTED in config.py and in the README.

The standings follow the league's rules: the top three in each division and
the next two in each conference (the wild cards) go through, ties broken by
regulation wins, then regulation and overtime wins, then all wins; what is
still level after that (the league goes on to head-to-head and goal
difference) is settled by a coin toss. In the first round the better division
winner plays the second wild card, the other plays the first, and second
plays third in each division; the winners in each half of the bracket meet,
then the two halves, then the two conferences. Every series is best of seven,
with the extra home game for the team that finished higher.

Once the real playoffs begin this still plays them out from the seedings; it
does not yet take the real series scores into account.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from . import config, odds

VERSION = 1
# what a result adds to a team's standing: points, then regulation wins, then
# regulation and overtime wins, then wins, packed into one number that sorts right
PT, RW, ROW, W = 10 ** 6, 10 ** 4, 10 ** 2, 1
WIN_REG, WIN_OT, WIN_SO, LOSS_OT = 2 * PT + RW + ROW + W, 2 * PT + ROW + W, 2 * PT + W, PT
HOME_GAMES = (True, True, False, False, True, False, True)       # the higher finisher's home games in a series


def standing(games: list[dict], teams: list[str]) -> dict:
    """Each team's standing so far, as one number (see above), from the finished regular-season games."""
    s = {t: 0 for t in teams}
    for g in games:
        hs, vs = g["home"].get("score"), g["away"].get("score")
        if g["state"] != "final" or hs is None or vs is None or hs == vs:
            continue
        win, lose = (g["home"]["id"], g["away"]["id"]) if hs > vs else (g["away"]["id"], g["home"]["id"])
        end = g.get("end") or "REG"
        if win in s:
            s[win] += WIN_REG if end == "REG" else WIN_SO if end == "SO" else WIN_OT
        if lose in s and end != "REG":
            s[lose] += LOSS_OT
    return s


def cuts(p: float) -> tuple:
    """Where a random number from 0 to 1 has to fall for each way a game can
    end, given the home team's chance of winning it: home in regulation, away
    in regulation, home in overtime, home in a shootout, away in overtime
    (anything above the last is away in a shootout)."""
    q, so = config.PLAYOFF_OT_RATE, config.PLAYOFF_SO_SHARE
    p_ot = 0.5 + config.PLAYOFF_OT_EDGE * (p - 0.5)                # past regulation it is nearly even
    home_reg = min(max(p - q * p_ot, 0.0), 1.0 - q)
    a = home_reg
    b = 1.0 - q
    c = b + q * p_ot * (1 - so)
    d = b + q * p_ot
    e = d + q * (1 - p_ot) * (1 - so)
    return a, b, c, d, e


def series_chance(p_home: float, p_away: float) -> float:
    """The higher finisher's chance of winning a best-of-seven, given its
    chance of winning a game at home and a game away."""
    ways = {(0, 0): 1.0}
    won = 0.0
    for n, at_home in enumerate(HOME_GAMES):
        p = p_home if at_home else p_away
        nxt = {}
        for (w, l), pr in ways.items():
            for dw, dl, x in ((1, 0, p), (0, 1, 1 - p)):
                if w + dw == 4:
                    won += pr * x
                elif l + dl < 4:
                    nxt[(w + dw, l + dl)] = nxt.get((w + dw, l + dl), 0.0) + pr * x
        ways = nxt
    return won


def spread(played: float, total: float) -> float:
    """How far (one standard deviation) a rating is moved before the season
    is played out, given the share of the season already played."""
    done = min(1.0, played / total) if total else 1.0
    return config.PLAYOFF_SPREAD_END + (config.PLAYOFF_SPREAD_START - config.PLAYOFF_SPREAD_END) * (1.0 - done) ** 0.5


def simulate(teams: list[dict], games: list[dict], rating: dict, sims: int | None = None, seed: int = 1) -> dict:
    """Play out the season `sims` times. `teams` is the standings table (id,
    conf, div); `games` every regular-season game; `rating` from odds.rate().
    Returns {team: {"playoffs", "r2", "r3", "final", "cup", "points", "d1",
    "d2", "d3", "wc1", "wc2"}}, the chances as shares from 0 to 1."""
    sims = config.PLAYOFF_SIMS if sims is None else sims
    rnd = random.Random(seed)
    ids = [t["id"] for t in teams]
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    regular = [g for g in games if g["type"] == 2 and g["home"]["id"] in idx and g["away"]["id"] in idx]
    base_by = standing(regular, ids)
    base = [base_by[t] for t in ids]
    left = [(idx[g["home"]["id"]], idx[g["away"]["id"]], bool(g.get("neutral"))) for g in regular if g["state"] in ("upcoming", "live")]
    played = sum(1 for g in regular if g["state"] == "final")
    sd = spread(played, played + len(left))
    confs = {}
    for t in teams:
        confs.setdefault(t["conf"], {}).setdefault(t["div"], []).append(idx[t["id"]])
    confs = [list(divs.values()) for divs in confs.values()]
    keys = ("playoffs", "r2", "r3", "final", "cup", "d1", "d2", "d3", "wc1", "wc2")
    count = {k: [0] * n for k in keys}
    points = [0] * n
    home, stretch = config.ODDS_HOME, config.ODDS_STRETCH
    worlds = max(1, min(config.PLAYOFF_WORLDS, sims))
    random_ = rnd.random

    for w in range(worlds):
        runs = sims // worlds + (1 if w < sims % worlds else 0)
        r = [rating.get(t, 0.0) + (rnd.gauss(0.0, sd) if sd else 0.0) for t in ids]
        plan = [(h, a) + cuts(odds.goal_share(stretch * (r[h] - r[a] + (0.0 if neutral else home)))) for h, a, neutral in left]
        series = {}

        def beats(hi, lo):                      # does the higher finisher win the series?
            p = series.get((hi, lo))
            if p is None:
                gap = config.PLAYOFF_GAP_KEPT * (r[hi] - r[lo])
                p = series[(hi, lo)] = series_chance(odds.goal_share(stretch * (gap + home)), odds.goal_share(stretch * (gap - home)))
            return random_() < p

        for _ in range(runs):
            s = base[:]
            for h, a, c1, c2, c3, c4, c5 in plan:
                x = random_()
                if x < c1:
                    s[h] += WIN_REG
                elif x < c2:
                    s[a] += WIN_REG
                elif x < c3:
                    s[h] += WIN_OT
                    s[a] += LOSS_OT
                elif x < c4:
                    s[h] += WIN_SO
                    s[a] += LOSS_OT
                elif x < c5:
                    s[a] += WIN_OT
                    s[h] += LOSS_OT
                else:
                    s[a] += WIN_SO
                    s[h] += LOSS_OT
            key = [v + random_() for v in s]    # what is still level is a coin toss
            for i in range(n):
                points[i] += s[i] // PT
            finalists = []
            for divs in confs:
                tops, rest = [], []
                for d in divs:
                    order = sorted(d, key=key.__getitem__, reverse=True)
                    tops.append(order[:3])
                    rest += order[3:]
                    for k, t in zip(("d1", "d2", "d3"), order):
                        count[k][t] += 1
                rest.sort(key=key.__getitem__, reverse=True)
                wild = rest[:2]
                for k, t in zip(("wc1", "wc2"), wild):
                    count[k][t] += 1
                for t in wild:
                    count["playoffs"][t] += 1
                for three in tops:
                    for t in three:
                        count["playoffs"][t] += 1

                def play(a, b, stage):          # a is at home unless b finished higher
                    hi, lo = (a, b) if key[a] >= key[b] else (b, a)
                    winner = hi if beats(hi, lo) else lo
                    count[stage][winner] += 1
                    return winner

                tops.sort(key=lambda three: key[three[0]] if three else 0, reverse=True)     # the better division winner first
                halves = []
                for three, wc in zip(tops, reversed(wild + [None] * (len(tops) - len(wild)))):
                    if len(three) < 3 or wc is None:
                        continue
                    first = beats(three[0], wc)                      # a division winner is at home to a wild card
                    a = three[0] if first else wc
                    count["r2"][a] += 1
                    b = play(three[1], three[2], "r2")
                    halves.append(play(a, b, "r3"))
                if len(halves) == 2:
                    finalists.append(play(halves[0], halves[1], "final"))
            if len(finalists) == 2:
                a, b = finalists
                hi, lo = (a, b) if key[a] >= key[b] else (b, a)
                count["cup"][hi if beats(hi, lo) else lo] += 1

    out = {}
    for i, t in enumerate(ids):
        out[t] = {k: round(count[k][i] / sims, 4) for k in keys}
        out[t]["points"] = round(points[i] / sims, 1)
    return out


def fingerprint(teams: list[dict], games: list[dict], rating: dict) -> str:
    """Changes whenever the odds would: a result, the schedule, a rating or a setting."""
    regular = sorted((g["id"], g["state"] == "final", g["home"]["id"], g["away"]["id"], g["home"].get("score"), g["away"].get("score"),
                      g.get("end")) for g in games if g["type"] == 2)
    settings = [VERSION] + [getattr(config, k) for k in sorted(dir(config)) if k.startswith(("PLAYOFF_", "ODDS_")) and k != "PLAYOFF_TESTED"
                            and k != "ODDS_TESTED"]
    blob = json.dumps([regular, sorted((t["id"], t["conf"], t["div"]) for t in teams), sorted((k, round(v, 4)) for k, v in rating.items()),
                       settings], default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def update(kept: dict, teams: list[dict], games: list[dict], rating: dict, today: str) -> dict:
    """The odds, worked out again only when something has changed, with each
    day's playoff chances kept so the page can show who has moved. Returns
    what to keep: {"key", "odds", "days": {date: {team: chance of the playoffs}}}."""
    key = fingerprint(teams, games, rating)
    if kept.get("key") == key and kept.get("odds"):
        result = kept["odds"]
    else:
        result = simulate(teams, games, rating)
    days = dict(kept.get("days") or {})
    days[today] = {t: v["playoffs"] for t, v in result.items()}
    return {"key": key, "odds": result, "days": dict(sorted(days.items())[-config.PLAYOFF_DAYS_KEPT:])}


def week_ago(days: dict, today: str, back: int = 7) -> dict:
    """Each team's playoff chance as it stood a week ago ({} until a week of days has been kept)."""
    import datetime as dt
    target = (dt.date.fromisoformat(today) - dt.timedelta(days=back)).isoformat()
    older = [d for d in sorted(days) if d <= target]
    return days[older[-1]] if older else {}
