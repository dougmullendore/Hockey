"""Rate every NHL player against the others at his position.

Impact is a box-score rating in the style of hockey's "game score". Each
thing a player does is worth a set number of points:

  a goal                          0.75
  a first assist                  0.70
  a second assist                 0.55
  a shot on goal                  0.075
  a blocked shot                  0.05
  a takeaway / a giveaway        +0.03 / -0.03
  a minor penalty drawn / taken  +0.15 / -0.15
  on the ice for a goal for / against (plus-minus)   +0.15 / -0.15

A skater's Impact is his total minus what an average regular at his position
(forward or defenseman) would have piled up in the same ice time. So it is
"points added over an average forward", and a player who simply plays a lot
is not ranked high for that alone.

A goalie's Impact is the goals he saved beyond what an average goalie would
have on the same shots, counted separately at even strength, against the
power play and shorthanded, at 0.75 a goal like a skater's goal.

Impact is a box-score measure. It cannot see shot quality, who else was on
the ice, or the strength of the opponent.

Beside Impact, each card carries numbers from the play-by-play (see
pipeline/xg.py): a skater's shot attempts and expected goals, and how many
more goals he scored than those chances were worth; his faceoffs; and for a
goalie the goals he saved above expected, which does account for where the
shots came from.
"""
from __future__ import annotations

from .nhl import GK, SK

W_GOAL, W_A1, W_A2, W_SHOT, W_BLOCK, W_TAKE, W_PEN, W_ONICE = 0.75, 0.70, 0.55, 0.075, 0.05, 0.03, 0.15, 0.15
W_SAVE = 0.75                # a goal saved is worth what a goal scored is
REGULAR_SHARE = 0.4          # a regular skater has played at least this share of his team's games
REGULAR_GOALIE = 0.2         # and a regular goalie this share
MIN_POOL = 8                 # no percentile unless at least this many players qualify
MIN_SHOTS = 10               # no shooting percentage on fewer shots than this
GROUP = {"C": "F", "L": "F", "R": "F", "D": "D", "G": "G"}
PARTS = ["goals", "assists", "shots", "defense", "discipline", "onice"]
G_PARTS = ["g_ev", "g_pk", "g_sh"]
SUM = ["g", "a", "a1", "pm", "pim", "hits", "ppg", "sog", "toi", "blk", "shifts", "gv", "tk", "pt", "pd", "ppp", "shpts", "gwg"]
ADV = ["att", "fen", "ixg", "fow", "fot"]          # from the play-by-play: attempts, unblocked attempts, expected goals, faceoffs won and taken
MIN_FACEOFFS = 5             # a game: no faceoff percentage for players who take fewer
G_SUM = ["sa", "sv", "ga", "toi", "es_sa", "es_sv", "pp_sa", "pp_sv", "sh_sa", "sh_sv"]

# (key, higher is better, who is ranked on it: skaters, goalies, or skaters with enough shots)
METRICS = [
    ("impact_gp", True, "all"),
    ("goals", True, "sk"), ("assists", True, "sk"), ("shots", True, "sk"), ("defense", True, "sk"),
    ("discipline", True, "sk"), ("onice", True, "sk"),
    ("g60", True, "sk"), ("a160", True, "sk"), ("p60", True, "sk"), ("sog60", True, "sk"), ("shp", True, "shooter"),
    ("toi_gp", True, "sk"), ("hits60", True, "sk"), ("blk60", True, "sk"), ("tk60", True, "sk"), ("gv60", False, "sk"),
    ("pd60", True, "sk"), ("pim60", False, "sk"),
    ("ixg60", True, "sk"), ("gax60", True, "shooter"), ("att60", True, "sk"), ("fo_pct", True, "faceoff"),
    ("g_ev", True, "g"), ("g_pk", True, "g"), ("g_sh", True, "g"),
    ("svp", True, "g"), ("gaa", False, "g"), ("gsaa60", True, "g"), ("es_svp", True, "g"), ("pk_svp", True, "g"),
    ("sa60", True, "g"), ("gsax60", True, "g"),
]


def _r(v, nd=2):
    return None if v is None else round(v, nd)


def _events(p: dict) -> dict:
    """What a skater did, in the eight things Impact counts."""
    return {"g": p["g"], "a1": p["a1"], "a2": p["a"] - p["a1"], "sog": p["sog"], "blk": p["blk"],
            "poss": p["tk"] - p["gv"], "pen": p["pd"] - p["pt"], "pm": p["pm"]}


def _result(g: dict, side: str) -> str:
    """"W 4-3 OT" for the team on `side`."""
    mine, theirs = g[side]["score"], g["home" if side == "away" else "away"]["score"]
    return f"{'W' if mine > theirs else 'L'} {mine}-{theirs}" + (f" {g['end']}" if g.get("end") in ("OT", "SO") else "")


def compute(teams: list[dict], games: list[dict], boxes: dict, people: dict, xg_scale: float = 1.0) -> dict:
    """Every player who has played, with totals, rates, Impact and percentiles.
    `teams` are the standings rows; `games` the finished games that count;
    `people` is {player id: his details from the rosters}; `xg_scale` brings
    the season's expected goals in line with the goals actually scored.
    "logs" in the result is each player's game-by-game lines, newest first."""
    by_team = {t["id"]: t for t in teams}
    team_games = {t: 0 for t in by_team}
    sk, gk, logs = {}, {}, {}
    for g in sorted(games, key=lambda g: (g["date"], g["start"] or 0, g["id"])):
        box = boxes.get(str(g["id"]))
        if g["state"] != "final" or not box or box.get("status") != "F":
            continue
        for side in ("home", "away"):
            team = g[side]["id"]
            if team not in by_team or not (box.get(side) or {}).get("sk"):
                continue
            team_games[team] += 1
            adv = box.get("adv") or {}
            other = "home" if side == "away" else "away"
            where = [g["id"], g["date"], g[other]["id"], int(side == "home"), _result(g, side)]
            for row in box[side]["sk"]:
                r = dict(zip(SK, row))
                p = sk.setdefault(r["id"], {"id": r["id"], "gp": 0, **{s: 0 for s in SUM + ADV}})
                p.update(team=team, name=r["name"], num=r["num"], pos=r["pos"])      # as of his latest game
                p["gp"] += 1
                for s in SUM:
                    p[s] += r.get(s) or 0
                extra = (adv.get("sk") or {}).get(str(r["id"])) or [0, 0, 0.0, 0, 0]
                for s, v in zip(ADV, extra):
                    p[s] += v * (xg_scale if s == "ixg" else 1)
                logs.setdefault(r["id"], []).append(where + [r["g"], r["a"], r["pm"], r["sog"], r["hits"], r["blk"], r["pim"], r["toi"],
                                                             round(extra[2] * xg_scale, 2) if adv else None])
            for row in box[side]["g"]:
                r = dict(zip(GK, row))
                p = gk.setdefault(r["id"], {"id": r["id"], "gp": 0, "gs": 0, "w": 0, "l": 0, "otl": 0, "so": 0, "xga": 0.0, "xg_ga": 0,
                                            **{s: 0 for s in G_SUM}})
                p.update(team=team, name=r["name"], num=r["num"], pos="G")
                p["gp"] += 1
                p["gs"] += r["start"]
                if r["dec"] in ("W", "L", "O"):
                    p[{"W": "w", "L": "l", "O": "otl"}[r["dec"]]] += 1
                p["so"] += 1 if r["start"] and r["ga"] == 0 and r["toi"] >= 3540 and r["dec"] == "W" else 0
                for s in G_SUM:
                    p[s] += r[s] or 0
                faced = (adv.get("g") or {}).get(str(r["id"]))
                if faced:
                    p["xga"] += faced[0] * xg_scale
                    p["xg_ga"] += faced[1]
                logs.setdefault(r["id"], []).append(where + [r["sa"], r["sv"], r["ga"], r["toi"], r["dec"],
                                                             round(faced[0] * xg_scale - faced[1], 2) if faced else None])

    for p in sk.values():
        p["grp"] = GROUP.get(p["pos"], "F")
        p["regular"] = p["gp"] >= max(1.0, REGULAR_SHARE * team_games[p["team"]])
    for p in gk.values():
        p["grp"] = "G"
        p["regular"] = p["gp"] >= max(1.0, REGULAR_GOALIE * team_games[p["team"]])

    # What an average regular does per second of ice time, forwards and defensemen apart.
    base = {}
    for grp in ("F", "D"):
        pool = [p for p in sk.values() if p["grp"] == grp and p["regular"]] or [p for p in sk.values() if p["grp"] == grp]
        toi = sum(p["toi"] for p in pool)
        tot = {}
        for p in pool:
            for k, v in _events(p).items():
                tot[k] = tot.get(k, 0) + v
        base[grp] = {k: (v / toi if toi else 0.0) for k, v in tot.items()} or dict.fromkeys(_events(dict.fromkeys(SUM, 0)), 0.0)
    # What an average goalie lets in per shot, in each situation.
    every = list(gk.values())
    let_in = {}
    for key in ("es", "pp", "sh"):
        shots = sum(p[key + "_sa"] for p in every)
        let_in[key] = (shots - sum(p[key + "_sv"] for p in every)) / shots if shots else 0.0

    out = []
    for p in sk.values():
        b, e, t = base[p["grp"]], _events(p), p["toi"]
        over = {k: e[k] - b[k] * t for k in e}
        part = {"goals": W_GOAL * over["g"], "assists": W_A1 * over["a1"] + W_A2 * over["a2"], "shots": W_SHOT * over["sog"],
                "defense": W_BLOCK * over["blk"] + W_TAKE * over["poss"], "discipline": W_PEN * over["pen"],
                "onice": W_ONICE * over["pm"]}
        impact, gp, hours = sum(part.values()), p["gp"], t / 3600 or 1e-9
        v = {"impact_gp": impact / gp, **{k: part[k] / gp for k in PARTS},
             "g60": p["g"] / hours, "a160": p["a1"] / hours, "p60": (p["g"] + p["a"]) / hours, "sog60": p["sog"] / hours,
             "shp": 100 * p["g"] / p["sog"] if p["sog"] else None, "toi_gp": t / gp / 60,
             "hits60": p["hits"] / hours, "blk60": p["blk"] / hours, "tk60": p["tk"] / hours, "gv60": p["gv"] / hours,
             "pd60": p["pd"] / hours, "pim60": p["pim"] / hours,
             "ixg60": p["ixg"] / hours if p["fen"] else None, "gax60": (p["g"] - p["ixg"]) / hours if p["fen"] else None,
             "att60": p["att"] / hours if p["att"] else None, "fo_pct": 100 * p["fow"] / p["fot"] if p["fot"] else None}
        can = {"all": True, "sk": True, "g": False, "shooter": p["sog"] >= MIN_SHOTS, "faceoff": p["fot"] >= MIN_FACEOFFS * gp}
        tot = {k: p[k] for k in SUM} | {"pts": p["g"] + p["a"], "a2": p["a"] - p["a1"], "att": p["att"], "fen": p["fen"],
                                        "ixg": round(p["ixg"], 1), "fow": p["fow"], "fot": p["fot"]}
        out.append({**p, "impact": impact, "_v": v, "_can": can, "tot": tot})
    for p in every:
        saved = {key: p[key + "_sa"] * let_in[key] - (p[key + "_sa"] - p[key + "_sv"]) for key in ("es", "pp", "sh")}
        part = {"g_ev": W_SAVE * saved["es"], "g_pk": W_SAVE * saved["pp"], "g_sh": W_SAVE * saved["sh"]}
        impact, gp, hours = sum(part.values()), p["gp"], p["toi"] / 3600 or 1e-9
        v = {"impact_gp": impact / gp, **{k: part[k] / gp for k in G_PARTS},
             "svp": 100 * p["sv"] / p["sa"] if p["sa"] else None, "gaa": p["ga"] / hours,
             "gsaa60": sum(saved.values()) / hours,
             "es_svp": 100 * p["es_sv"] / p["es_sa"] if p["es_sa"] else None,
             "pk_svp": 100 * p["pp_sv"] / p["pp_sa"] if p["pp_sa"] >= 5 else None,
             "sa60": p["sa"] / hours, "gsax60": (p["xga"] - p["xg_ga"]) / hours if p["xga"] else None}
        can = {"all": True, "sk": False, "g": True, "shooter": False, "faceoff": False}
        tot = {k: p[k] for k in G_SUM + ["gs", "w", "l", "otl", "so"]} | {
            "gsaa": round(sum(saved.values()), 1), "xga": round(p["xga"], 1), "gsax": round(p["xga"] - p["xg_ga"], 1) if p["xga"] else None}
        out.append({**p, "impact": impact, "_v": v, "_can": can, "tot": tot})

    # Percentiles: against regulars at the same position, on the things that position does.
    keys = [m[0] for m in METRICS]
    for grp in ("F", "D", "G"):
        for key, higher, who in METRICS:
            pool = [q for q in out if q["grp"] == grp and q["regular"] and q["_can"][who] and q["_v"].get(key) is not None]
            if len(pool) < MIN_POOL:
                continue
            vals = sorted(q["_v"][key] for q in pool)
            for q in pool:
                x = q["_v"][key]
                below = sum(1 for y in vals if y < x) + 0.5 * sum(1 for y in vals if y == x)
                pct = 100 * below / len(vals)
                q.setdefault("_pct", {})[key] = int(min(99, max(1, round(pct if higher else 100 - pct))))

    # Ranks: by Impact per game among regulars. Skaters are ranked together and
    # goalies on their own; each also has a rank at his position.
    seen = {}
    for goalies in (False, True):
        pool = sorted((q for q in out if q["regular"] and (q["grp"] == "G") == goalies),
                      key=lambda q: (-q["_v"]["impact_gp"], -q["impact"], q["id"]))
        for i, q in enumerate(pool):
            q["rank"] = i + 1
            seen[q["grp"]] = seen.get(q["grp"], 0) + 1
            q["pos_rank"] = seen[q["grp"]]
    rows = []
    for q in sorted(out, key=lambda q: (q["grp"] == "G", q.get("rank") or 10**6, -q["_v"]["impact_gp"])):
        who = people.get(str(q["id"])) or {}
        name = (who.get("first", "") + " " + who.get("last", "")).strip() or q["name"]
        team = by_team[q["team"]]
        bio = {k: who[k] for k in ("sh", "ht", "wt", "born", "from") if who.get(k)}
        row = {"id": q["id"], "name": name, "team": team["name"], "team_id": q["team"], "team_rank": team["rank"],
               "num": q["num"] if q["num"] is not None else who.get("num"),
               "pos": q["pos"], "grp": q["grp"], "gp": q["gp"], "regular": q["regular"],
               "rank": q.get("rank"), "pos_rank": q.get("pos_rank"), "impact": _r(q["impact"], 1),
               "tot": q["tot"], "v": [_r(q["_v"].get(k), 3) for k in keys], "pct": [q.get("_pct", {}).get(k) for k in keys]}
        if who.get("photo"):
            row["photo"] = who["photo"]
        if bio:
            row["bio"] = bio
        rows.append(row)
    return {"metrics": keys, "players": rows, "logs": {pid: rows_[::-1] for pid, rows_ in logs.items()},
            "regulars": sum(n for g, n in seen.items() if g != "G"), "pos_regulars": seen,
            "teams": [{"id": t["id"], "name": t["name"], "rank": t["rank"], "games": team_games[t["id"]]} for t in teams],
            "baseline": {"F": {k: _r(v * 3600, 4) for k, v in base["F"].items()}, "D": {k: _r(v * 3600, 4) for k, v in base["D"].items()},
                         "goals_per_shot": {k: _r(v, 4) for k, v in let_in.items()}},
            "weights": {"goal": W_GOAL, "a1": W_A1, "a2": W_A2, "shot": W_SHOT, "block": W_BLOCK, "take": W_TAKE,
                        "pen": W_PEN, "onice": W_ONICE, "save": W_SAVE,
                        "regular_share": REGULAR_SHARE, "regular_goalie": REGULAR_GOALIE}}
