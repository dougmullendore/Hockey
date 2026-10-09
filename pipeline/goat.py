"""The GOAT ranking: the site's own order of the 32 teams.

Four things decide it, in this order of importance:
  1. head to head: a team that has the better of another in their games is
     ranked above it where that can be done without contradicting more
     results than it honors;
  2. strength of schedule: the average rating of the teams it has played
     (the ratings behind the odds);
  3. the standings: a team gets credit for its place in the league table;
  4. record: its share of games won.
Factors 2 to 4 make a score: each team's place among all teams on schedule
and on record (0 at the bottom, 1 at the top) and its standings credit
((33 - place) / 32), weighted by GOAT_WEIGHTS.

The order starts from that score. Then every pair of teams has a price for
being ranked the "wrong" way round: ranking a team above one that leads their
season series costs 1 for each win the other is ahead by, and ranking it above
a team with a higher score costs the gap divided by GOAT_HEAD_TO_HEAD. The
GOAT order is the one with the lowest total price, found by moving one team at
a time to wherever it lowers the total most, until no move helps. So a series
lead lifts a team over the team it beat when their scores are close, but not
when the gap is wide. Results that form a circle (A beat B, B beat C, C beat
A) cannot all be honored; it keeps as many as it can.
"""
from __future__ import annotations

from . import config


def head_to_head(games: list[dict]) -> dict:
    """{(team, opponent): [wins, losses, [dates won]]} from finished games."""
    out = {}
    for g in sorted(games, key=lambda g: (g["date"], g["id"])):
        hs, vs = g["home"].get("score"), g["away"].get("score")
        if g["state"] != "final" or hs is None or vs is None or hs == vs:
            continue
        w, l = (g["home"]["id"], g["away"]["id"]) if hs > vs else (g["away"]["id"], g["home"]["id"])
        a = out.setdefault((w, l), [0, 0, []])
        a[0] += 1
        a[2].append(g["date"])
        out.setdefault((l, w), [0, 0, []])[1] += 1
    return out


def _percentile(values: dict) -> dict:
    """Each value's place among all of them, 0 (lowest) to 1 (highest); ties share."""
    xs = sorted(values.values())
    n = len(xs) or 1
    import bisect
    return {k: (bisect.bisect_left(xs, v) + 0.5 * (bisect.bisect_right(xs, v) - bisect.bisect_left(xs, v))) / n
            for k, v in values.items()}


def rank(games: list[dict], rating: dict, teams: set, place: dict) -> dict:
    """Rank `teams` (ids). `place` is {id: place in the league standings}.
    Returns {"order": [ids, best first], "base": {id: place by score alone},
    "score": {id: score}, "factors": {id: [schedule, standings, record]}}."""
    finals = [g for g in games if g["state"] == "final" and g["home"].get("score") is not None
              and g["away"].get("score") is not None and g["home"]["score"] != g["away"]["score"]]
    floor = min(rating.values()) if rating else 0.0
    won, played, opp = {}, {}, {}
    for g in finals:
        for side, other in (("home", "away"), ("away", "home")):
            t = g[side]["id"]
            if t not in teams:
                continue
            played[t] = played.get(t, 0) + 1
            won[t] = won.get(t, 0) + (g[side]["score"] > g[other]["score"])
            opp.setdefault(t, []).append(rating.get(g[other]["id"], floor))
    sos = _percentile({t: (sum(opp[t]) / len(opp[t])) if opp.get(t) else floor for t in teams})
    rec = _percentile({t: won.get(t, 0) / played[t] if played.get(t) else 0.0 for t in teams})
    size = max(place.values(), default=32)       # the number of teams in the league
    poll = {t: (size + 1 - place[t]) / size if t in place else 0.0 for t in teams}
    ws, wp, wr = config.GOAT_WEIGHTS
    score = {t: ws * sos[t] + wp * poll[t] + wr * rec[t] for t in teams}
    order = sorted(teams, key=lambda t: (-score[t], t))
    base = {t: i + 1 for i, t in enumerate(order)}
    net = {(a, b): x[0] - x[1] for (a, b), x in head_to_head(finals).items()
           if a in teams and b in teams and x[0] > x[1]}

    def price(a, b):                       # what it costs to rank a above b
        return net.get((b, a), 0) + max(0.0, score[b] - score[a]) / config.GOAT_HEAD_TO_HEAD

    # Moves look this far up and down the order (the whole league).
    reach, moved, rounds = config.GOAT_REACH, True, 0
    while moved and rounds < 500:
        moved, rounds = False, rounds + 1
        for src in range(len(order)):
            x, best, d = order[src], (-1e-9, None), 0.0
            for dst in range(src - 1, max(-1, src - reach - 1), -1):
                t = order[dst]
                d += price(x, t) - price(t, x)
                if d < best[0]:
                    best = (d, dst)
            d = 0.0
            for dst in range(src + 1, min(len(order), src + reach + 1)):
                t = order[dst]
                d += price(t, x) - price(x, t)
                if d < best[0]:
                    best = (d, dst)
            if best[1] is not None:
                order.pop(src)
                order.insert(best[1], x)
                moved = True
    return {"order": order, "base": base, "score": score,
            "factors": {t: [round(sos[t], 3), round(poll[t], 3), round(rec[t], 3)] for t in teams}}


def contradictions(order: list, games: list[dict], among: set) -> int:
    """How many head-to-head results between teams in `among` the order gets
    the wrong way round (a team ranked below one it has the better of)."""
    place = {t: i for i, t in enumerate(order)}
    return sum(1 for (a, b), (wins, losses, _) in head_to_head(games).items()
               if a in among and b in among and a in place and b in place and wins > losses and place[a] > place[b])
