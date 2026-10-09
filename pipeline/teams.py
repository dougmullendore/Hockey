"""Team stats for the 32 teams, from the official box scores.

Each team's own numbers per game and its opponents' against it, plus the
site's rating of the team (the one behind the odds) and how hard its schedule
has been (the average rating of the teams it has played).
"""
from __future__ import annotations

KEYS = ["sog", "fow", "fot", "ppg", "ppo", "pim", "hits", "blk", "gv", "tk"]


def compute(teams: list[dict], games: list[dict], boxes: dict, rating: dict) -> dict:
    """{"teams": [...], "through": date}. `teams` are the standings rows;
    `games` the finished games that count; `rating` is every team's rating
    from pipeline/odds.py."""
    power = {t: i + 1 for i, t in enumerate(sorted(rating, key=lambda x: -rating[x]))}
    acc = {t["id"]: {"gp": 0, "gf": 0, "ga": 0, "boxed": 0, "pp_games": 0, "opp_r": [],
                     "own": dict.fromkeys(KEYS, 0), "opp": dict.fromkeys(KEYS, 0)} for t in teams}
    through = None
    for g in games:
        if g["state"] != "final" or g["away"].get("score") is None or g["home"].get("score") is None:
            continue
        through = max(through or g["date"], g["date"])
        box = boxes.get(str(g["id"])) or {}
        stats = box.get("tstats") or {}
        for side, other in (("home", "away"), ("away", "home")):
            a = acc.get(g[side]["id"])
            if a is None:
                continue
            a["gp"] += 1
            # a shootout win is one goal in the final score but not a goal scored
            shootout = g.get("end") == "SO"
            mine, theirs = g[side]["score"], g[other]["score"]
            a["gf"] += mine - (1 if shootout and mine > theirs else 0)
            a["ga"] += theirs - (1 if shootout and theirs > mine else 0)
            if g[other]["id"] in rating:
                a["opp_r"].append(rating[g[other]["id"]])
            own, opp = stats.get(side) or {}, stats.get(other) or {}
            if box.get("status") == "F" and own and opp:          # stats only from games with a box score
                a["boxed"] += 1
                a["pp_games"] += 1 if "ppo" in own and "ppo" in opp else 0
                for k in KEYS:
                    a["own"][k] += own.get(k) or 0
                    a["opp"][k] += opp.get(k) or 0
    out = []
    for t in teams:
        a = acc[t["id"]]
        o, p, n, gp = a["own"], a["opp"], a["boxed"], a["gp"]

        def per(x, games=None, nd=1):
            games = n if games is None else games
            return round(x / games, nd) if games else None

        def share(x, of, nd=1):
            return round(100 * x / of, nd) if of else None

        out.append({
            "id": t["id"], "name": t["name"], "short": t["short"], "rank": t["rank"],
            "gp": t["gp"], "w": t["w"], "l": t["l"], "otl": t["otl"], "pts": t["pts"], "pct": t["pct"],
            "games": n, "gf_gp": per(a["gf"], gp, 2), "ga_gp": per(a["ga"], gp, 2),
            "sf_gp": per(o["sog"]), "sa_gp": per(p["sog"]),
            "sh_pct": share(a["gf"], o["sog"]) if n == gp else None,
            "sv_pct": round(1 - a["ga"] / p["sog"], 3) if p["sog"] and n == gp else None,
            "pp_pct": share(o["ppg"], o["ppo"]) if a["pp_games"] else None,
            "pk_pct": share(p["ppo"] - p["ppg"], p["ppo"]) if a["pp_games"] else None,
            "fo_pct": share(o["fow"], o["fot"]),
            "hits_gp": per(o["hits"]), "blk_gp": per(o["blk"]), "pim_gp": per(o["pim"]),
            "gv_gp": per(o["gv"]), "tk_gp": per(o["tk"]),
            "power": power.get(t["id"]), "sos": round(sum(a["opp_r"]) / len(a["opp_r"]), 3) if a["opp_r"] else None,
        })
    # strength of schedule as a rank: 1 is the hardest
    for i, r in enumerate(sorted((r for r in out if r["sos"] is not None), key=lambda r: -r["sos"])):
        r["sos_rank"] = i + 1
    for r in out:
        r.pop("sos")
    return {"teams": out, "through": through}
