"""Roll scored shots up into the tables the website shows.

For every season and game type (regular season / playoffs) this writes
goalie, team and skater tables as small JSON files under
<data>/site_data/, plus a list of recent games and some site metadata."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, features, onice, store, xg

HIGH_DANGER = 0.15   # a shot worth 15%+ is a high-danger chance
MED_DANGER = 0.05

SHOT_COLS = ["game_id", "idx", "game_type", "period", "game_seconds", "team_id",
             "opp_id", "shooter_id", "goalie_id", "type", "goal", "on_goal",
             "strength", "shot_type", "x_adj", "y_adj", "xg"]


def _r(v, nd=2):
    """Round for JSON; missing values become None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return round(f, nd) if nd else int(round(f))


def _pct(num, den, nd=1):
    return None if not den else round(100.0 * float(num) / float(den), nd)


def season_label(season: int) -> str:
    return f"{season // 10000}-{str(season % 10000)[2:]}"


# --------------------------------------------------------------- scoring --
def scored_shots(model: dict, season: int, games: pd.DataFrame, events: pd.DataFrame,
                 prior_scale: float = 1.0, prior_weight: float = 0.0):
    """Returns (shots with xG, the season's scale factor)."""
    shots = features.build_shots(events, games)
    if not len(shots):
        return pd.DataFrame(columns=SHOT_COLS), prior_scale
    shots["xg"], scale = xg.season_scale(
        shots, xg.predict(model, shots, season), prior_scale, prior_weight)
    shots["strength"] = features.strength(shots)
    g = games.set_index("game_id")
    home = shots["game_id"].map(g["home_id"]).astype("Int64")
    away = shots["game_id"].map(g["away_id"]).astype("Int64")
    shots["opp_id"] = home.where(shots["team_id"] == away, away)
    return shots[SHOT_COLS], scale


def _write_shots(data: Path, season: int, shots: pd.DataFrame) -> None:
    p = Path(data) / "shots" / f"{season}.csv.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    out = shots.copy()
    out["xg"] = out["xg"].round(4)
    out.to_csv(p, index=False, compression={"method": "gzip", "mtime": 0, "compresslevel": 6})


def _read_shots(data: Path, season: int) -> pd.DataFrame | None:
    p = Path(data) / "shots" / f"{season}.csv.gz"
    if not p.exists():
        return None
    df = pd.read_csv(p, dtype={"type": "string", "strength": "string", "shot_type": "string"})
    for c in ["game_id", "team_id", "opp_id", "shooter_id", "goalie_id", "game_type"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


# ---------------------------------------------------------------- lookups --
def _names(rosters: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Latest name, position and team(s) for every player in a set of games."""
    if not len(rosters):
        return pd.DataFrame(columns=["name", "last", "pos", "team", "gp_dressed"]).rename_axis("player_id")
    abbr = pd.concat([
        games[["home_id", "home_abbrev"]].set_axis(["id", "ab"], axis=1),
        games[["away_id", "away_abbrev"]].set_axis(["id", "ab"], axis=1),
    ]).drop_duplicates("id").set_index("id")["ab"]
    r = rosters.sort_values("game_id", kind="stable").copy()
    r["ab"] = r["team_id"].map(abbr)
    r["name"] = (r["first_name"].fillna("") + " " + r["last_name"].fillna("")).str.strip()
    last = r.groupby("player_id").tail(1).set_index("player_id")
    teams = r.groupby("player_id")["ab"].agg(lambda s: "/".join(pd.unique(s.dropna())[::-1][:3]))
    out = pd.DataFrame({
        "name": last["name"], "last": last["last_name"], "pos": last["position"], "team": teams,
        "gp_dressed": r.groupby("player_id")["game_id"].nunique(),
    })
    return out


def _official(data: Path, kind: str, season: int, gt: int) -> pd.DataFrame:
    rows = store.read_json(Path(data) / "official" / f"{kind}_{season}_{gt}.json", []) or []
    if not rows:
        return pd.DataFrame().rename_axis("playerId")
    return pd.DataFrame(rows).drop_duplicates("playerId").set_index("playerId")


# ----------------------------------------------------------------- goalies --
def goalie_table(shots: pd.DataFrame, names: pd.DataFrame, official: pd.DataFrame) -> list[dict]:
    s = shots[shots["goalie_id"].notna() & (shots["strength"] != "EN")].copy()
    if not len(s):
        return []
    s["hd"] = s["xg"] >= HIGH_DANGER
    s["md"] = (s["xg"] >= MED_DANGER) & ~s["hd"]
    s["ld"] = s["xg"] < MED_DANGER
    s["v5"] = s["strength"] == "5v5"
    rows = []
    for gid, d in s.groupby("goalie_id"):
        gid = int(gid)
        fa, sa, ga, xga = len(d), int(d["on_goal"].sum()), int(d["goal"].sum()), float(d["xg"].sum())
        gsax = xga - ga
        o = official.loc[gid] if gid in official.index else None
        toi = float(o["timeOnIce"]) if o is not None and pd.notna(o.get("timeOnIce")) else None
        hd, v5 = d[d["hd"]], d[d["v5"]]
        nm = names.loc[gid] if gid in names.index else None
        row = {
            "id": gid,
            "name": None if nm is None else nm["name"],
            "team": None if nm is None else nm["team"],
            "gp": _r(o["gamesPlayed"], 0) if o is not None else int(d["game_id"].nunique()),
            "gs": _r(o.get("gamesStarted"), 0) if o is not None else None,
            "w": _r(o.get("wins"), 0) if o is not None else None,
            "l": _r(o.get("losses"), 0) if o is not None else None,
            "otl": _r(o.get("otLosses"), 0) if o is not None else None,
            "so": _r(o.get("shutouts"), 0) if o is not None else None,
            "toi": _r(toi / 60.0, 0) if toi else None,
            "fa": fa, "sa": sa, "ga": ga,
            "sv": round((sa - ga) / sa, 4) if sa else None,
            "xga": _r(xga, 1),
            "gsax": _r(gsax, 1),
            "gsax60": _r(gsax / (toi / 3600.0), 2) if toi else None,
            "gsax100": _r(100.0 * gsax / fa, 2) if fa else None,
            "gaa": _r(ga / (toi / 3600.0), 2) if toi else None,
            "xgaa": _r(xga / (toi / 3600.0), 2) if toi else None,
            "hd_sa": int(hd["on_goal"].sum()),
            "hd_ga": int(hd["goal"].sum()),
            "hd_sv": round(1 - hd["goal"].sum() / hd["on_goal"].sum(), 4) if hd["on_goal"].sum() else None,
            "hd_gsax": _r(hd["xg"].sum() - hd["goal"].sum(), 1),
            "md_gsax": _r(d.loc[d["md"], "xg"].sum() - d.loc[d["md"], "goal"].sum(), 1),
            "ld_gsax": _r(d.loc[d["ld"], "xg"].sum() - d.loc[d["ld"], "goal"].sum(), 1),
            "gsax_5v5": _r(v5["xg"].sum() - v5["goal"].sum(), 1),
        }
        rows.append(row)
    rows.sort(key=lambda r: -(r["gsax"] or 0))
    return rows


# ------------------------------------------------------------------- teams --
def team_table(shots: pd.DataFrame, events: pd.DataFrame, games: pd.DataFrame) -> list[dict]:
    if not len(games):
        return []
    abbr = {}
    rec = {}
    for g in games.itertuples(index=False):
        abbr[int(g.home_id)], abbr[int(g.away_id)] = g.home_abbrev, g.away_abbrev
        if pd.isna(g.home_score) or pd.isna(g.away_score):
            continue
        hw = g.home_score > g.away_score
        extra = g.last_period_type in ("OT", "SO")
        for tid, won in ((int(g.home_id), hw), (int(g.away_id), not hw)):
            r = rec.setdefault(tid, {"gp": 0, "w": 0, "l": 0, "otl": 0})
            r["gp"] += 1
            if won:
                r["w"] += 1
            elif extra and g.game_type == 2:
                r["otl"] += 1
            else:
                r["l"] += 1

    # shot attempts including blocks, for Corsi
    att = events[events["type"].isin(["goal", "shot-on-goal", "missed-shot", "blocked-shot"])
                 & (events["period_type"] != "SO") & events["team_id"].notna()]
    att5 = att[(att["home_skaters"] == 5) & (att["away_skaters"] == 5)
               & (att["home_goalie_in"] == 1) & (att["away_goalie_in"] == 1)]
    g = games.set_index("game_id")
    opp = g["home_id"].reindex(att5["game_id"]).to_numpy()
    away = g["away_id"].reindex(att5["game_id"]).to_numpy()
    opp_id = np.where(att5["team_id"].to_numpy() == opp, away, opp)
    cf = att5.groupby("team_id").size()
    ca = pd.Series(opp_id).value_counts()

    s = shots[shots["strength"] != "PS"]
    s5 = shots[shots["strength"] == "5v5"]
    rows = []
    for tid, r in rec.items():
        f, a = s[s["team_id"] == tid], s[s["opp_id"] == tid]
        f5, a5 = s5[s5["team_id"] == tid], s5[s5["opp_id"] == tid]
        fall, aall = shots[shots["team_id"] == tid], shots[shots["opp_id"] == tid]
        gf, ga = int(fall["goal"].sum()), int(aall["goal"].sum())
        xgf, xga = float(f["xg"].sum()), float(a["xg"].sum())
        gf5, ga5 = int(f5["goal"].sum()), int(a5["goal"].sum())
        xgf5, xga5 = float(f5["xg"].sum()), float(a5["xg"].sum())
        sf5, sa5 = int(f5["on_goal"].sum()), int(a5["on_goal"].sum())
        cf5, ca5 = int(cf.get(tid, 0)), int(ca.get(tid, 0))
        a_gk = aall[aall["strength"] != "EN"]
        sh5 = gf5 / sf5 if sf5 else None
        sv5 = 1 - ga5 / sa5 if sa5 else None
        gp = r["gp"]
        rows.append({
            "id": tid, "team": abbr.get(tid), "gp": gp, "w": r["w"], "l": r["l"], "otl": r["otl"],
            "pts": 2 * r["w"] + r["otl"],
            "pts_pct": _r((2 * r["w"] + r["otl"]) / (2 * gp), 3) if gp else None,
            "gf": gf, "ga": ga, "gd": gf - ga,
            "xgf": _r(xgf, 1), "xga": _r(xga, 1), "xgd": _r(xgf - xga, 1),
            "xg_pct": _pct(xgf, xgf + xga),
            "xgf_gp": _r(xgf / gp, 2) if gp else None,
            "xga_gp": _r(xga / gp, 2) if gp else None,
            "gf5": gf5, "ga5": ga5,
            "xgf5": _r(xgf5, 1), "xga5": _r(xga5, 1),
            "xg5_pct": _pct(xgf5, xgf5 + xga5),
            "gf5_pct": _pct(gf5, gf5 + ga5),
            "cf5_pct": _pct(cf5, cf5 + ca5),
            "ff5_pct": _pct(len(f5), len(f5) + len(a5)),
            "sh5": _r(100 * sh5, 1) if sh5 is not None else None,
            "sv5": _r(100 * sv5, 1) if sv5 is not None else None,
            "pdo": _r(100 * (sh5 + sv5), 1) if sh5 is not None and sv5 is not None else None,
            "finish": _r(gf - float(fall["xg"].sum()), 1),
            "goaltending": _r(float(a_gk["xg"].sum()) - int(a_gk["goal"].sum()), 1),
        })
    rows.sort(key=lambda r: -(r["xg_pct"] or 0))
    return rows


# ----------------------------------------------------------------- skaters --
def skater_table(shots: pd.DataFrame, events: pd.DataFrame, names: pd.DataFrame,
                 official: pd.DataFrame) -> list[dict]:
    if not len(shots):
        return []
    s = shots[shots["shooter_id"].notna()]
    by = s.groupby("shooter_id")
    agg = pd.DataFrame({
        "iff": by.size(), "sog": by["on_goal"].sum(), "g": by["goal"].sum(), "ixg": by["xg"].sum(),
    })
    s5 = s[s["strength"] == "5v5"].groupby("shooter_id")
    agg["g5"], agg["ixg5"] = s5["goal"].sum(), s5["xg"].sum()
    pp = s[s["strength"] == "PP"].groupby("shooter_id")
    agg["gpp"], agg["ixgpp"] = pp["goal"].sum(), pp["xg"].sum()
    hd = s[s["xg"] >= HIGH_DANGER].groupby("shooter_id")
    agg["hd"] = hd.size()

    goals = events[(events["type"] == "goal") & (events["period_type"] != "SO")]
    agg["a1"] = goals.groupby("player2_id").size()
    agg["a2"] = goals.groupby("player3_id").size()
    blk = events[(events["type"] == "blocked-shot") & (events["period_type"] != "SO")]
    agg["blocked"] = blk.groupby("player1_id").size()
    # players with assists but no shots still belong in the table
    extra = pd.Index(goals["player2_id"].dropna().unique()).union(
        pd.Index(goals["player3_id"].dropna().unique())).difference(agg.index)
    if len(extra):
        agg = pd.concat([agg, pd.DataFrame(index=extra, columns=agg.columns)])
        agg["a1"] = goals.groupby("player2_id").size().reindex(agg.index)
        agg["a2"] = goals.groupby("player3_id").size().reindex(agg.index)
    agg = agg.astype("float64").fillna(0.0)

    rows = []
    for pid, d in agg.iterrows():
        pid = int(pid)
        nm = names.loc[pid] if pid in names.index else None
        if nm is not None and nm["pos"] == "G":
            continue
        o = official.loc[pid] if pid in official.index else None
        gp = _r(o["gamesPlayed"], 0) if o is not None else (None if nm is None else int(nm["gp_dressed"]))
        toi = None
        if o is not None and pd.notna(o.get("timeOnIcePerGame")) and gp:
            toi = float(o["timeOnIcePerGame"]) * gp  # seconds
        g, a1, a2 = int(d["g"]), int(d["a1"]), int(d["a2"])
        pos = None if nm is None else nm["pos"]
        rows.append({
            "id": pid,
            "name": None if nm is None else nm["name"],
            "team": None if nm is None else nm["team"],
            "pos": "D" if pos == "D" else ("F" if pos in ("C", "L", "R") else pos),
            "pos_detail": pos,
            "gp": gp,
            "toi": _r(toi / 60.0, 0) if toi else None,
            "toi_gp": _r(toi / 60.0 / gp, 1) if toi and gp else None,
            "g": g, "a1": a1, "a2": a2, "p": g + a1 + a2, "p1": g + a1,
            "sog": int(d["sog"]), "iff": int(d["iff"]), "icf": int(d["iff"] + d["blocked"]),
            "ixg": _r(d["ixg"], 1),
            "gax": _r(g - d["ixg"], 1),
            "sh_pct": _pct(g, d["sog"]),
            "xsh_pct": _pct(d["ixg"], d["iff"]),
            "ixg60": _r(d["ixg"] / (toi / 3600.0), 2) if toi else None,
            "g60": _r(g / (toi / 3600.0), 2) if toi else None,
            "p60": _r((g + a1 + a2) / (toi / 3600.0), 2) if toi else None,
            "hd": int(d["hd"]),
            "g5": int(d["g5"]), "ixg5": _r(d["ixg5"], 1),
            "gpp": int(d["gpp"]), "ixgpp": _r(d["ixgpp"], 1),
        })
    rows.sort(key=lambda r: -(r["ixg"] or 0))
    return rows


# ------------------------------------------------------------------- games --
def game_list(shots: pd.DataFrame, games: pd.DataFrame, limit: int | None = None) -> list[dict]:
    if not len(games):
        return []
    by = shots[shots["strength"] != "PS"].groupby(["game_id", "team_id"])
    xgs, sog = by["xg"].sum(), by["on_goal"].sum()
    out = []
    ordered = games.sort_values(["date", "game_id"], ascending=False, kind="stable")
    for g in (ordered.head(limit) if limit else ordered).itertuples(index=False):
        gid, h, a = int(g.game_id), int(g.home_id), int(g.away_id)
        out.append({
            "id": gid, "date": g.date, "type": int(g.game_type),
            "home": g.home_abbrev, "away": g.away_abbrev,
            "hs": _r(g.home_score, 0), "as": _r(g.away_score, 0),
            "end": g.last_period_type,
            "hxg": _r(xgs.get((gid, h), 0.0), 2), "axg": _r(xgs.get((gid, a), 0.0), 2),
            "hsog": _r(sog.get((gid, h), 0), 0), "asog": _r(sog.get((gid, a), 0), 0),
        })
    return out


def shot_maps(shots: pd.DataFrame, games: pd.DataFrame, names: pd.DataFrame, limit: int = 16) -> list[dict]:
    """Shot-by-shot detail for the most recent games (for the rink chart).

    Coordinates are in feet from centre ice with the home team attacking to
    the right. Each shot is [x, y, xG, goal, is_home, period, shooter, type]."""
    out = []
    listing = {g["id"]: g for g in game_list(shots, games)}
    ordered = games.sort_values(["date", "game_id"], ascending=False, kind="stable").head(limit)
    by_game = dict(tuple(shots.groupby("game_id")))
    for g in ordered.itertuples(index=False):
        gid = int(g.game_id)
        d = by_game.get(gid)
        if d is None:
            continue
        rows = []
        for s in d.sort_values("game_seconds", kind="stable").itertuples(index=False):
            home = int(s.team_id == g.home_id)
            sign = 1 if home else -1
            pid = None if pd.isna(s.shooter_id) else int(s.shooter_id)
            nm = names.loc[pid, "name"] if pid in names.index else ""
            rows.append([int(sign * s.x_adj), int(sign * s.y_adj), round(float(s.xg), 3),
                         int(s.goal), home, int(s.period), nm, s.shot_type if pd.notna(s.shot_type) else "",
                         s.strength])
        out.append({**listing[gid], "shots": rows})
    return out


# ------------------------------------------------------------------ on-ice --
SUMS = ["toi5", *onice.FOR, *onice.AGAINST]
MIN_LINE_SECONDS = 300    # lines and pairs with under 5 minutes are dropped
MIN_WOWY_SECONDS = 600    # teammate pairs with under 10 minutes are dropped


def _abbrevs(games: pd.DataFrame) -> dict:
    out = {}
    for g in games.itertuples(index=False):
        out[int(g.home_id)], out[int(g.away_id)] = g.home_abbrev, g.away_abbrev
    return out


def _rates(d, prefix="") -> dict:
    """Shares and per-60 rates from a row of on-ice sums."""
    hours = float(d["toi5"]) / 3600.0
    sh = d["gf"] / d["sf"] if d["sf"] else None
    sv = 1 - d["ga"] / d["sa"] if d["sa"] else None
    return {
        prefix + "toi": _r(d["toi5"] / 60.0, 1),
        prefix + "cf_pct": _pct(d["cf"], d["cf"] + d["ca"]),
        prefix + "xgf": _r(d["xgf"], 1), prefix + "xga": _r(d["xga"], 1),
        prefix + "xg_pct": _pct(d["xgf"], d["xgf"] + d["xga"]),
        prefix + "gf": _r(d["gf"], 0), prefix + "ga": _r(d["ga"], 0),
        prefix + "gf_pct": _pct(d["gf"], d["gf"] + d["ga"]),
        prefix + "xgf60": _r(d["xgf"] / hours, 2) if hours else None,
        prefix + "xga60": _r(d["xga"] / hours, 2) if hours else None,
        prefix + "cf60": _r(d["cf"] / hours, 1) if hours else None,
        prefix + "ca60": _r(d["ca"] / hours, 1) if hours else None,
        prefix + "osh": _r(100 * sh, 1) if sh is not None else None,
        prefix + "osv": _r(100 * sv, 1) if sv is not None else None,
        prefix + "pdo": _r(100 * (sh + sv), 1) if sh is not None and sv is not None else None,
    }


def onice_table(res: dict, ids: set, names: pd.DataFrame) -> list[dict]:
    """Five-on-five results with each skater on the ice, and with him off it."""
    p = res["players"]
    p = p[p["game_id"].isin(ids)]
    if not len(p):
        return []
    team = res["teams"].set_index(["game_id", "team_id"])[SUMS]
    off = team.reindex(pd.MultiIndex.from_frame(p[["game_id", "team_id"]])).to_numpy() - p[SUMS].to_numpy()
    off = pd.DataFrame(off, columns=SUMS).assign(player_id=p["player_id"].to_numpy())
    on = p.groupby("player_id")[SUMS + ["toi_all"]].sum()
    gp = p.groupby("player_id")["game_id"].nunique()
    off = off.groupby("player_id")[SUMS].sum()
    rows = []
    for pid, d in on.iterrows():
        pid = int(pid)
        nm = names.loc[pid] if pid in names.index else None
        pos = None if nm is None else nm["pos"]
        o = off.loc[pid]
        row = {"id": pid, "name": None if nm is None else nm["name"],
               "team": None if nm is None else nm["team"],
               "pos": "D" if pos == "D" else "F", "gp": int(gp[pid]),
               "toi_gp": _r(d["toi5"] / 60.0 / gp[pid], 1), **_rates(d)}
        on_xg, off_xg = _pct(d["xgf"], d["xgf"] + d["xga"]), _pct(o["xgf"], o["xgf"] + o["xga"])
        on_cf, off_cf = _pct(d["cf"], d["cf"] + d["ca"]), _pct(o["cf"], o["cf"] + o["ca"])
        row["xg_rel"] = _r(on_xg - off_xg, 1) if on_xg is not None and off_xg is not None else None
        row["cf_rel"] = _r(on_cf - off_cf, 1) if on_cf is not None and off_cf is not None else None
        rows.append(row)
    rows.sort(key=lambda r: -(r["toi"] or 0))
    return rows


_POS_ORDER = {"L": 0, "C": 1, "R": 2, "D": 3}
_COMBO_FIELDS = {"toi", "cf_pct", "xgf", "xga", "xg_pct", "gf", "ga", "xgf60", "xga60"}


def combo_tables(res: dict, ids: set, names: pd.DataFrame, abbr: dict) -> dict:
    """Forward lines and defence pairs. Returns {"lines": [...], "pairs": [...]}."""
    c = res["combos"]
    c = c[c["game_id"].isin(ids)]
    out = {"lines": [], "pairs": []}
    if not len(c):
        return out
    g = c.groupby(["team_id", "kind", "key"], sort=False)
    sums = g[SUMS].sum()
    sums["gp"] = g["game_id"].nunique()
    sums = sums[sums["toi5"] >= MIN_LINE_SECONDS]
    for (team_id, kind, key), d in sums.iterrows():
        members = [int(x) for x in key.split("-")]
        known = [m for m in members if m in names.index]
        known.sort(key=lambda m: (_POS_ORDER.get(names.at[m, "pos"], 9), names.at[m, "last"] or ""))
        label = " / ".join(str(names.at[m, "last"]) for m in known) or key
        rates = {k: v for k, v in _rates(d).items() if k in _COMBO_FIELDS}
        out["lines" if kind == "F" else "pairs"].append({
            "name": label, "team": abbr.get(int(team_id)),
            "full": ", ".join(str(names.at[m, "name"]) for m in known),
            "gp": int(d["gp"]), **rates})
    for rows in out.values():
        rows.sort(key=lambda r: -(r["toi"] or 0))
    return out


def wowy_table(res: dict, ids: set, names: pd.DataFrame, abbr: dict) -> dict:
    """Every pair of teammates: together, and each without the other.

    Compact layout to keep the file small:
      players  {id: [name, position, [team, ...]]}
      totals   {"id|TEAM": [toi, cf, ca, xgf, xga, gf, ga]}  one skater on one team
      pairs    [[id1, id2, TEAM, toi, cf, ca, xgf, xga, gf, ga], ...]  together"""
    keep = ["toi5", "cf", "ca", "xgf", "xga", "gf", "ga"]
    w = res["pairs"]
    w = w[w["game_id"].isin(ids)] if len(w) else w
    p = res["players"]
    p = p[p["game_id"].isin(ids)]
    if not len(w) or not len(p):
        return {"players": {}, "totals": {}, "pairs": []}
    pair = w.groupby(["team_id", "p1", "p2"], sort=False)[keep].sum()
    pair = pair[pair["toi5"] >= MIN_WOWY_SECONDS]
    tot = p.groupby(["player_id", "team_id"])[keep].sum()

    def pack(d):
        return [int(d["toi5"]), int(d["cf"]), int(d["ca"]), round(float(d["xgf"]), 2),
                round(float(d["xga"]), 2), int(d["gf"]), int(d["ga"])]

    pairs, used = [], set()
    for (team_id, a, b), d in pair.iterrows():
        pairs.append([int(a), int(b), abbr.get(int(team_id)), *pack(d)])
        used.add((int(a), int(team_id))); used.add((int(b), int(team_id)))
    totals, players = {}, {}
    for (pid, team_id), d in tot.iterrows():
        pid, team_id = int(pid), int(team_id)
        if (pid, team_id) not in used:
            continue
        totals[f"{pid}|{abbr.get(team_id)}"] = pack(d)
        nm = names.loc[pid] if pid in names.index else None
        entry = players.setdefault(str(pid), [None if nm is None else nm["name"],
                                              None if nm is None else ("D" if nm["pos"] == "D" else "F"), []])
        entry[2].append(abbr.get(team_id))
    return {"players": players, "totals": totals, "pairs": pairs}


# -------------------------------------------------------------------- main --
def build_all(data: Path, log) -> dict:
    data = Path(data)
    model = xg.load(data)
    if model is None:
        raise RuntimeError("no expected-goals model available yet")
    out = data / "site_data"
    out.mkdir(parents=True, exist_ok=True)
    manifest = store.read_json(data / "manifest.json", {}) or {}
    built = manifest.setdefault("_stats", {})
    scales = manifest.setdefault("_xg_scale", {})
    coverage = manifest.setdefault("_shift_coverage", {})
    prior_scale = 1.0

    seasons_meta, summary = [], {}
    latest = None
    for season in config.SEASONS:
        games = store.read(data, "games", season)
        if not len(games):
            continue
        info = manifest.get(str(season), {})
        stamp = (f"{config.XG_MODEL_VERSION}|{len(games)}|{games['date'].max()}|"
                 f"{info.get('shift_games', 0)}|v7|" + ",".join(map(str, model.get("train_seasons", []))))
        types = []
        for gt, gname in config.GAME_TYPES.items():
            n = int((games["game_type"] == gt).sum())
            if n:
                types.append({"id": gname, "games": n,
                              "through": str(games.loc[games["game_type"] == gt, "date"].max())})
        seasons_meta.append({"id": season, "label": season_label(season), "types": types,
                             "complete": bool(info.get("complete"))})
        summary[season] = len(games)

        fresh = (built.get(str(season)) == stamp and info.get("complete")
                 and all((out / f"{kind}_{season}_{t['id']}.json").exists()
                         for t in types for kind in ("goalies", "onice", "wowy")))
        if fresh and str(season) in scales:
            prior_scale = scales[str(season)]
            continue

        events = store.read(data, "events", season)
        rosters = store.read(data, "rosters", season)
        shots, scale = scored_shots(
            model, season, games, events, prior_scale,
            0.0 if info.get("complete") else config.XG_SCALE_PRIOR)
        scales[str(season)] = prior_scale = round(float(scale), 5)
        _write_shots(data, season, shots)
        shifts = store.read(data, "shifts", season)
        ice = onice.build(games, events, rosters, shifts, shots, log)
        abbr = _abbrevs(games)
        coverage[str(season)] = {"games": int(len(games)), "with_shifts": int(len(ice["checks"]))}
        for gt, gname in config.GAME_TYPES.items():
            gm = games[games["game_type"] == gt]
            if not len(gm):
                continue
            ids = set(gm["game_id"].astype(int))
            sh = shots[shots["game_id"].isin(ids)]
            ev = events[events["game_id"].isin(ids)]
            names = _names(rosters[rosters["game_id"].isin(ids)], gm)
            store.write_json(out / f"goalies_{season}_{gname}.json",
                             goalie_table(sh, names, _official(data, "goalie", season, gt)), compact=True)
            store.write_json(out / f"teams_{season}_{gname}.json",
                             team_table(sh, ev, gm), compact=True)
            store.write_json(out / f"skaters_{season}_{gname}.json",
                             skater_table(sh, ev, names, _official(data, "skater", season, gt)), compact=True)
            store.write_json(out / f"games_{season}_{gname}.json", game_list(sh, gm), compact=True)
            store.write_json(out / f"onice_{season}_{gname}.json", onice_table(ice, ids, names), compact=True)
            combos = combo_tables(ice, ids, names, abbr)
            store.write_json(out / f"lines_{season}_{gname}.json", combos["lines"], compact=True)
            store.write_json(out / f"pairs_{season}_{gname}.json", combos["pairs"], compact=True)
            store.write_json(out / f"wowy_{season}_{gname}.json", wowy_table(ice, ids, names, abbr), compact=True)
        built[str(season)] = stamp
        latest = (shots, games, _names(rosters, games))
        log(f"stats: built season {season} ({len(games)} games, {len(shots):,} shots, "
            f"{shots['goal'].sum()} goals, {shots['xg'].sum():.0f} xG, scale {scale:.3f}, "
            f"shifts for {len(ice['checks'])} games)")

    if latest is not None:  # the newest season that was rebuilt this run
        store.write_json(out / "recent.json", shot_maps(*latest), compact=True)

    report = store.read_json(data / "model" / "xg_report.json", {}) or {}
    store.write_json(out / "model.json", report, compact=True)
    store.write_json(out / "meta.json", {
        "site": config.SITE_NAME, "tagline": config.SITE_TAGLINE,
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "seasons": seasons_meta[::-1],
        "model": {"version": report.get("version"), "auc": report.get("overall", {}).get("auc"),
                  "test_season": report.get("test_season")},
        "danger": {"high": HIGH_DANGER, "medium": MED_DANGER},
        "xg_scale": {k: v for k, v in scales.items()},
        "shift_coverage": coverage,
    })
    store.write_json(data / "manifest.json", manifest)
    return summary
