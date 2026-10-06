"""Player cards: where each player ranks at his position.

For every player and season this works out a percentile (0 = worst,
100 = best among regulars at the same position) for each part of WAR and a
few scoring rates. It does so twice:

  one    that season alone
  three  that season and the two before it, with recent seasons counting
         more (weights 3 : 2 : 1). Steadier, and the default on the site.

Percentiles compare rates (value per hour of the relevant ice time), so a
player is not ranked low just for missing games. Players with too little
ice time to judge get no percentile."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import store

WEIGHTS = [1.0, 2.0 / 3.0, 1.0 / 3.0]     # this season, last season, the one before

# key, label, which ice time it is a rate of, share of the leader's ice time needed
SKATER_METRICS = [
    ("war", "toi", 0.25), ("ev_off", "toi5", 0.25), ("ev_def", "toi5", 0.25),
    ("pp", "toi_pp", 0.15), ("pk", "toi_sh", 0.15), ("fin", "toi", 0.25), ("pen", "toi", 0.25),
    ("g", "toi", 0.25), ("a1", "toi", 0.25), ("ixg", "toi", 0.25), ("xg_pct", "toi5", 0.25),
]
GOALIE_METRICS = [("war", "fa", 0.2), ("gsax", "fa", 0.2), ("hd_gsax", "hd_sa", 0.2),
                  ("gsax_5v5", "fa", 0.2), ("sv", "sa", 0.2)]
WAR_PARTS = {"war", "ev_off", "ev_def", "pp", "pk", "fin", "pen"}


def _season_records(final: dict, out: Path) -> dict:
    """{season: {player_id: plain numbers for that season}}"""
    seasons = {}
    for season, res in final.items():
        sk = {r["id"]: r for r in store.read_json(out / f"skaters_{season}_regular.json", []) or []}
        oi = {r["id"]: r for r in store.read_json(out / f"onice_{season}_regular.json", []) or []}
        gl = {r["id"]: r for r in store.read_json(out / f"goalies_{season}_regular.json", []) or []}
        recs = {}
        for r in res["rows"]:
            pid = r["id"]
            base = {"name": r["name"], "team": r["team"], "pos": r["pos"], "gp": r["gp"] or 0,
                    "war": r["war"]}
            if r["pos"] == "G":
                g = gl.get(pid)
                if not g:
                    continue
                base.update(fa=g["fa"], sa=g["sa"], hd_sa=g["hd_sa"], gsax=g["gsax"], hd_gsax=g["hd_gsax"],
                            gsax_5v5=g["gsax_5v5"], saves=g["sa"] - g["ga"], ga=g["ga"],
                            w=g.get("w"), toi_min=g.get("toi"))
            else:
                s, o = sk.get(pid, {}), oi.get(pid, {})
                base.update({k: r[k] for k in ("ev_off", "ev_def", "pp", "pk", "fin", "pen")})
                base.update(toi=r["_toi"], toi5=r["_toi5"], toi_pp=r["_toi_pp"], toi_sh=r["_toi_sh"],
                            g=s.get("g", 0), a1=s.get("a1", 0), a2=s.get("a2", 0), ixg=s.get("ixg", 0.0),
                            xgf=o.get("xgf") or 0.0, xga=o.get("xga") or 0.0)
            recs[pid] = base
        seasons[season] = recs
    return seasons


def _blend(recs: list, weights: list) -> dict:
    """Weighted totals over one or more seasons of the same player."""
    out = {}
    for rec, w in zip(recs, weights):
        if rec is None:
            continue
        for k, v in rec.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = out.get(k, 0.0) + w * v
    return out


def _rate(tot: dict, key: str, base: str):
    if key == "xg_pct":
        d = tot.get("xgf", 0.0) + tot.get("xga", 0.0)
        return 100.0 * tot.get("xgf", 0.0) / d if d > 0 else None
    if key == "sv":
        return tot["saves"] / tot["sa"] if tot.get("sa") else None
    return tot.get(key, 0.0) / tot[base] if tot.get(base) else None


def _display(tot: dict, key: str, base: str, single: bool):
    """The number printed beside the bar."""
    rate = _rate(tot, key, base)
    if rate is None:
        return None
    if key in ("xg_pct",):
        return round(rate, 1)
    if key == "sv":
        return round(rate, 3)
    if key in ("g", "a1", "ixg"):
        return round(rate * 3600.0, 2)                     # per 60 minutes
    if key in ("gsax", "gsax_5v5"):
        return round(rate * 100.0, 2)                      # per 100 shots faced
    if key == "hd_gsax":
        return round(rate * 100.0, 1)
    if single:
        return round(tot.get(key, 0.0), 2)                 # WAR parts: the season total
    games = 50.0 if "fa" in tot else 82.0                 # a full workload: 50 for a goalie
    return round(tot.get(key, 0.0) / tot["gp"] * games, 2) if tot.get("gp") else None


def _percentiles(blended: dict, metrics: list, single: bool) -> dict:
    """{player_id: ([percentiles], [display values])} within one position group."""
    ids = list(blended)
    out = {pid: ([None] * len(metrics), [None] * len(metrics)) for pid in ids}
    for j, (key, base, share) in enumerate(metrics):
        base_vals = np.array([blended[p].get(base, 0.0) for p in ids], float)
        need = share * base_vals.max() if len(ids) else 0.0
        rates = [(_rate(blended[p], key, base), p) for p, b in zip(ids, base_vals) if b >= need and b > 0]
        rates = sorted((r, p) for r, p in rates if r is not None)
        n = len(rates)
        for rank, (_, p) in enumerate(rates):
            out[p][0][j] = int(round(100.0 * (rank + 0.5) / n))
        for p in ids:
            out[p][1][j] = _display(blended[p], key, base, single)
    return out


def build(final: dict, out: Path, bio: dict | None = None) -> dict:
    """Write cards.json and return a small summary.

    `bio` maps a player id to his birth date and handedness, when known."""
    bio = bio or {}
    seasons = _season_records(final, out)
    order = sorted(seasons)
    players = {}
    for i, season in enumerate(order):
        window = [seasons[s] for s in (order[i], *reversed(order[max(0, i - 2):i]))]   # newest first
        for group in ("F", "D", "G"):
            metrics = GOALIE_METRICS if group == "G" else SKATER_METRICS
            ids = [p for p, r in seasons[season].items() if r["pos"] == group]
            one = {p: _blend([seasons[season][p]], [1.0]) for p in ids}
            three = {p: _blend([w.get(p) if (w.get(p) or {}).get("pos") == group else None for w in window],
                               WEIGHTS) for p in ids}
            pct1, pct3 = _percentiles(one, metrics, True), _percentiles(three, metrics, False)
            for p in ids:
                r = seasons[season][p]
                card = players.setdefault(str(p), {"n": r["name"], "p": group, "y": {}})
                card["n"], card["t"] = r["name"], (r["team"] or "").split("/")[0]
                who = bio.get(str(p)) or {}
                if who.get("born"):
                    card["b"] = who["born"]
                if who.get("shoots"):
                    card["sh"] = who["shoots"]
                row = {"t": r["team"], "gp": r["gp"], "war": r["war"],
                       "p1": pct1[p][0], "v1": pct1[p][1], "p3": pct3[p][0], "v3": pct3[p][1],
                       "n3": sum(1 for w in window if p in w)}
                if group == "G":
                    row.update(w=r.get("w"), sa=r["sa"], sv=round(r["saves"] / r["sa"], 3) if r["sa"] else None,
                               gsax=r["gsax"])
                else:
                    row.update(toi=round(r["toi"] / 60.0), g=r["g"], a=r["a1"] + r["a2"])
                card["y"][str(season)] = row
    doc = {"seasons": order, "weights": [round(w, 2) for w in WEIGHTS],
           "skater_metrics": [m[0] for m in SKATER_METRICS],
           "goalie_metrics": [m[0] for m in GOALIE_METRICS],
           # per season: [millions of dollars per win, league-minimum salary]
           "money": {str(s): [final[s]["notes"].get("dollars_per_war"), final[s]["notes"].get("min_salary")]
                     for s in order},
           "players": players}
    store.write_json(out / "cards.json", doc, compact=True)
    return {"players": len(players), "seasons": len(order)}
