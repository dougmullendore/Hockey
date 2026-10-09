"""The awards race: who would win each of the league's trophies if the season ended today.

Three of the trophies are simple counts and are shown as they stand: the Art
Ross (most points), the Rocket Richard (most goals) and the Presidents'
Trophy (best record), plus the Jennings (the goalies of the team allowing the
fewest goals). The rest are voted on, so nobody can know them; for each of
those this module scores every eligible player from 0 to 100 on the things
voters tend to reward, using the site's own numbers:

  Hart (most valuable)        Impact added this season, and how his team is doing
  Norris (best defenseman)    Impact, points and ice time, among defensemen
  Vezina (best goalie)        goals saved above expected, save percentage and wins
  Calder (best rookie)        Impact and points, among rookies
  Selke (best defensive forward)   plus-minus, blocks and takeaways, faceoffs won and penalty-kill time
  Lady Byng (skill and sportsmanship)   points, and few penalty minutes
  Jack Adams (coach)          how far his team is ahead of what its rating before the season pointed to

Each ingredient is turned into a place among the eligible players, 0 at the
bottom and 1 at the top, and the places are mixed with the weights in RECIPES
below. These are a reading of the numbers, not a forecast of the vote.

A rookie, as the league defines one: no earlier NHL season of more than 25
games, not two earlier seasons of 6 games or more, and under 26 on September
15 of the season.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math

from . import config

TOP = 10
RECIPES = {
    "hart": {"impact": 0.7, "team": 0.3},
    "norris": {"impact": 0.5, "points": 0.3, "ice": 0.2},
    "vezina": {"saved": 0.5, "save_pct": 0.25, "wins": 0.25},
    "calder": {"impact": 0.6, "points": 0.4},
    "selke": {"plus_minus": 0.3, "defense": 0.3, "faceoffs": 0.2, "kill": 0.2},
    "byng": {"points": 0.6, "clean": 0.4},
}
ABOUT = [   # key, trophy, what it is for, who is listed
    ("hart", "Hart Trophy", "Most valuable player", "player"),
    ("art_ross", "Art Ross Trophy", "Most points", "player"),
    ("richard", "Rocket Richard Trophy", "Most goals", "player"),
    ("norris", "Norris Trophy", "Best defenseman", "player"),
    ("vezina", "Vezina Trophy", "Best goalie", "player"),
    ("calder", "Calder Trophy", "Best rookie", "player"),
    ("selke", "Selke Trophy", "Best defensive forward", "player"),
    ("byng", "Lady Byng Trophy", "Skill and sportsmanship", "player"),
    ("adams", "Jack Adams Award", "Coach of the year", "team"),
    ("jennings", "Jennings Trophy", "Goalies of the team allowing the fewest goals", "team"),
    ("presidents", "Presidents' Trophy", "Best record in the regular season", "team"),
]
COUNTED = ("art_ross", "richard", "jennings", "presidents")       # counts, not scores


def _places(values: dict) -> dict:
    """Each value's place among all of them, 0 (lowest) to 1 (highest); ties share."""
    xs = sorted(values.values())
    n = len(xs) or 1
    return {k: (bisect.bisect_left(xs, v) + 0.5 * (bisect.bisect_right(xs, v) - bisect.bisect_left(xs, v))) / n
            for k, v in values.items()}


def is_rookie(earlier: list[list] | None, born: str | None, season: int) -> bool:
    """`earlier` is the player's NHL regular seasons before this one, as kept
    in careers.json ([season, team, games, ...]); None when not known."""
    if earlier is None:
        return False
    games = {}
    for row in earlier:
        if row[0] < season:
            games[row[0]] = games.get(row[0], 0) + row[2]
    if any(n > 25 for n in games.values()) or sum(1 for n in games.values() if n >= 6) >= 2:
        return False
    if born:
        try:
            if dt.date.fromisoformat(born) <= dt.date(season - 26, 9, 15):       # already 26 on September 15
                return False
        except ValueError:
            pass
    return True


def expected_pct(rating: float) -> float:
    """The share of the possible points a team with this rating would win
    against an average schedule: its chance of winning, plus the point for
    the losses that come after regulation (about 23% of them)."""
    win = 1.0 / (1.0 + math.exp(-config.ODDS_STRETCH * rating))
    return win + 0.115 * (1.0 - win)


def _mix(pool: list[dict], recipe: dict, parts: dict) -> list[tuple]:
    """Score everyone in `pool` (0 to 100): each part's place among the pool, weighted."""
    places = {k: _places({p["id"]: parts[k](p) for p in pool}) for k in recipe}
    scored = [(100 * sum(w * places[k][p["id"]] for k, w in recipe.items()), p) for p in pool]
    return sorted(scored, key=lambda x: (-x[0], -x[1]["impact"], x[1]["id"]))


def compute(rated: dict, table: list[dict], careers: dict, people: dict, kill_seconds: dict, coaches: dict,
            before: dict, team_ga: dict, season: int) -> list[dict]:
    """Every race, best first. `rated` is players.compute()'s result; `table`
    the standings; `careers` and `people` as stored; `kill_seconds` {player:
    seconds on the penalty kill}; `coaches` {team: head coach}; `before`
    {team: rating before the season}; `team_ga` {team: [goals against, games]}."""
    m = rated["metrics"]

    def val(p, key):
        v = p["v"][m.index(key)]
        return 0.0 if v is None else v

    teams = {t["id"]: t for t in table}
    team_place = _places({t["id"]: t["pct"] if t["gp"] else 0.5 for t in table})
    regulars = [p for p in rated["players"] if p["regular"]]
    skaters = [p for p in regulars if p["grp"] != "G"]
    goalies = [p for p in regulars if p["grp"] == "G"]

    def line(p, score, stats):
        return {"id": p["id"], "name": p["name"], "team": p["team_id"], "pos": p["pos"], "photo": p.get("photo"),
                "score": None if score is None else round(score, 1), "stats": stats}

    def skater_stats(p, *extra):
        t = p["tot"]
        return [f"{t['pts']} PTS", f"{t['g']} G", f"{t['a']} A", *extra, f"{p['gp']} GP"]

    def goalie_stats(p):
        t = p["tot"]
        saved = t.get("gsax") if t.get("gsax") is not None else t.get("gsaa")
        pct = f"{t['sv'] / t['sa']:.3f}".lstrip("0") if t["sa"] else "–"
        return [f"{t['w']}-{t['l']}-{t['otl']}", f"{pct} Sv%", f"{saved:+.1f} goals saved", f"{p['gp']} GP"]

    def signed(v):
        return f"{v:+d}" if isinstance(v, int) else f"{v:+.1f}"

    races = {}
    parts = {"impact": lambda p: p["impact"], "team": lambda p: team_place.get(p["team_id"], 0.5),
             "points": lambda p: p["tot"].get("pts", 0), "ice": lambda p: val(p, "toi_gp"),
             "saved": lambda p: p["tot"]["gsax"] if p["tot"].get("gsax") is not None else p["tot"].get("gsaa", 0.0),
             "save_pct": lambda p: p["tot"]["sv"] / p["tot"]["sa"] if p["tot"].get("sa") else 0.0,
             "wins": lambda p: p["tot"].get("w", 0),
             "plus_minus": lambda p: p["tot"].get("pm", 0), "defense": lambda p: val(p, "defense") * p["gp"],
             "faceoffs": lambda p: p["tot"].get("fow", 0), "kill": lambda p: kill_seconds.get(str(p["id"]), 0),
             "clean": lambda p: -(p["tot"].get("pim", 0) / p["gp"])}

    def stats_for(p, *extra):
        return goalie_stats(p) if p["grp"] == "G" else skater_stats(p, *extra)

    races["hart"] = [line(p, s, stats_for(p, f"{signed(p['impact'])} Impact")) for s, p in _mix(regulars, RECIPES["hart"], parts)[:TOP]]
    races["norris"] = [line(p, s, skater_stats(p, f"{val(p, 'toi_gp'):.1f} min a game"))
                       for s, p in _mix([p for p in skaters if p["grp"] == "D"], RECIPES["norris"], parts)[:TOP]]
    races["vezina"] = [line(p, s, goalie_stats(p)) for s, p in _mix(goalies, RECIPES["vezina"], parts)[:TOP]]
    rookies = [p for p in regulars if is_rookie(None if str(p["id"]) not in careers else careers[str(p["id"])].get("seasons") or [],
                                                (people.get(str(p["id"])) or {}).get("born"), season)]
    races["calder"] = [line(p, s, stats_for(p, f"{signed(p['impact'])} Impact")) for s, p in _mix(rookies, RECIPES["calder"], parts)[:TOP]]
    forwards = [p for p in skaters if p["grp"] == "F"]
    races["selke"] = [line(p, s, [f"{signed(p['tot']['pm'])} plus-minus", f"{p['tot']['blk']} blocks", f"{p['tot']['tk']} takeaways",
                                  f"{p['tot'].get('fow', 0)} faceoffs won", f"{kill_seconds.get(str(p['id']), 0) // 60} min killing penalties"])
                      for s, p in _mix(forwards, RECIPES["selke"], parts)[:TOP]]
    races["byng"] = [line(p, s, skater_stats(p, f"{p['tot']['pim']} PIM")) for s, p in _mix(skaters, RECIPES["byng"], parts)[:TOP]]

    everyone = [p for p in rated["players"] if p["grp"] != "G"]
    by_points = sorted(everyone, key=lambda p: (-p["tot"]["pts"], -p["tot"]["g"], p["gp"], p["id"]))
    races["art_ross"] = [line(p, None, skater_stats(p)) for p in by_points[:TOP] if p["tot"]["pts"] > 0]
    by_goals = sorted(everyone, key=lambda p: (-p["tot"]["g"], p["gp"], p["id"]))
    races["richard"] = [line(p, None, [f"{p['tot']['g']} G", f"{p['tot']['sog']} shots", f"{p['gp']} GP"]) for p in by_goals[:TOP] if p["tot"]["g"] > 0]

    def team_line(t, score, stats, name=None):
        return {"team": t["id"], "name": name or t["name"], "sub": t["name"] if name else None,
                "score": None if score is None else round(score, 1), "stats": stats}

    ahead = []
    for t in table:
        if not t["gp"]:
            continue
        expected = expected_pct(before.get(t["id"], 0.0))
        ahead.append((t["pct"] - expected, expected, t))
    ahead.sort(key=lambda x: (-x[0], x[2]["rank"]))
    span = max((abs(a[0]) for a in ahead), default=1.0) or 1.0
    races["adams"] = [team_line(t, 50 + 50 * gap / span, [f"{t['w']}-{t['l']}-{t['otl']}", f"{t['pct']:.3f}".replace("0.", ".") + " of the points",
                                                           f"{expected:.3f}".replace("0.", ".") + " expected", f"{100 * gap:+.1f} points per 100 ahead"],
                                coaches.get(t["id"]))
                      for gap, expected, t in ahead[:TOP]]
    stingy = sorted((t for t in table if (team_ga.get(t["id"]) or [0, 0])[1]), key=lambda t: (team_ga[t["id"]][0] / team_ga[t["id"]][1], t["rank"]))
    keepers = {}
    for p in sorted(rated["players"], key=lambda p: -p["gp"]):
        if p["grp"] == "G":
            keepers.setdefault(p["team_id"], []).append(p["name"])
    races["jennings"] = [team_line(t, None, [f"{team_ga[t['id']][0]} goals against", f"{team_ga[t['id']][0] / team_ga[t['id']][1]:.2f} a game", f"{team_ga[t['id']][1]} GP"],
                                   " and ".join(keepers.get(t["id"], [])[:2]) or None) for t in stingy[:TOP]]
    races["presidents"] = [team_line(t, None, [f"{t['pts']} PTS", f"{t['w']}-{t['l']}-{t['otl']}", f"{t['gp']} GP", f"{t['diff']:+d} goals"])
                           for t in sorted(table, key=lambda t: t["rank"])[:TOP]]

    out = []
    for key, trophy, what, kind in ABOUT:
        out.append({"key": key, "trophy": trophy, "for": what, "kind": kind, "counted": key in COUNTED,
                    "recipe": RECIPES.get(key), "rows": races.get(key) or []})
    return out


def who(row: dict) -> str:
    return str(row["id"]) if "id" in row else row["team"]


def movement(races: list[dict], history: dict, today: str, days: int = 7) -> None:
    """Mark each row with where it stood a week ago ("was": an earlier place,
    or 0 if it was not in the top ten), from the kept daily snapshots."""
    earlier = sorted(d for d in history if d < today)
    if not earlier:
        return
    target = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    older = [d for d in earlier if d <= target]
    then = history[older[-1] if older else earlier[0]]
    for race in races:
        was = then.get(race["key"])
        if was is None:
            continue
        for row in race["rows"]:
            row["was"] = was.index(who(row)) + 1 if who(row) in was else 0
        race["since"] = older[-1] if older else earlier[0]


def snapshot(races: list[dict]) -> dict:
    return {race["key"]: [who(row) for row in race["rows"]] for race in races}
