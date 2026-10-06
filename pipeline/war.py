"""Wins above replacement (WAR).

WAR asks: how many more wins did this player give his team than a
freely available fill-in (a "replacement" player) would have?

For a skater it adds six things, each first measured in goals:

  ev_off   his isolated effect on his team's chances at five-on-five
  ev_def   his isolated effect on the opponent's chances at five-on-five
  pp       his isolated effect on his team's power-play chances
  pk       his isolated effect on opposing power-play chances
  fin      goals he scored beyond what his shots were worth (finishing)
  pen      penalties he drew minus penalties he took

"Isolated" means estimated by the regression in rapm.py, which accounts for
linemates, opponents, the score and where shifts start. For a goalie it is
goals saved above expected.

Each piece is compared with what a replacement player would have done in
the same ice time, and goals are converted to wins."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, rapm

COMPONENTS = ["ev_off", "ev_def", "pp", "pk", "fin", "pen"]

# A team's regulars: the rest form the replacement pool for that kind of ice time.
REGULARS = {
    "toi5": {"F": 13, "D": 7},     # five-on-five and overall
    "toi_pp": {"F": 9, "D": 4},    # two power-play units
    "toi_sh": {"F": 8, "D": 6},    # penalty killers
}
GOALIE_REGULARS = 2


def penalties(events: pd.DataFrame, game_ids: set) -> tuple[pd.Series, pd.Series, int]:
    """Minor penalties taken and drawn per player, and how many led to a power play.

    Matching minors called on both teams at the same moment cancel out (no
    power play), so they are not counted. A double minor counts as two."""
    p = events[(events["type"] == "penalty") & events["game_id"].isin(game_ids)
               & events["penalty_minutes"].isin([2, 4])
               & events["penalty_type"].isin(["MIN", "BEN"]) & events["team_id"].notna()].copy()
    if not len(p):
        return pd.Series(dtype=float), pd.Series(dtype=float), 0
    p["n"] = (p["penalty_minutes"] // 2).astype(float)
    when = ["game_id", "period", "period_seconds"]
    per_team = p.groupby(when + ["team_id"])["n"].sum().reset_index()
    spread = per_team.groupby(when)["n"].agg(["min", "max", "count"])
    offsetting = spread[(spread["count"] == 2) & (spread["min"] == spread["max"])].index
    p = p[~pd.MultiIndex.from_frame(p[when]).isin(offsetting)]
    taken = p.groupby("player1_id")["n"].sum()
    drawn = p.groupby("player2_id")["n"].sum()
    return taken, drawn, int(p["n"].sum())


def goals_per_win(games_by_season: dict) -> float:
    """How many extra goals are worth one more win, from team-season results.

    A "win" here is two standings points. Shootout results are left out of
    the goal totals because the league's scores add one goal for the winner."""
    rows = []
    for games in games_by_season.values():
        g = games[(games["game_type"] == 2) & games["home_score"].notna()]
        if len(g) < 1000:
            continue
        hw = g["home_score"] > g["away_score"]
        extra = g["last_period_type"].isin(["OT", "SO"])
        so = g["last_period_type"] == "SO"
        hgd = (g["home_score"] - g["away_score"]).astype(float) - np.where(so, np.where(hw, 1, -1), 0)
        home = pd.DataFrame({"team": g["home_id"], "pts": np.where(hw, 2, np.where(extra, 1, 0)), "gd": hgd})
        away = pd.DataFrame({"team": g["away_id"], "pts": np.where(~hw, 2, np.where(extra, 1, 0)), "gd": -hgd})
        t = pd.concat([home, away]).groupby("team").sum()
        rows.append(t)
    if not rows:
        return config.WAR_GOALS_PER_WIN
    t = pd.concat(rows)
    wins = (t["pts"] - t["pts"].mean()) / 2.0
    slope = float((wins * t["gd"]).sum() / (t["gd"] ** 2).sum())
    return round(1.0 / slope, 2) if slope > 0 else config.WAR_GOALS_PER_WIN


def _pool_seconds(per_team: pd.DataFrame, pos: pd.Series) -> pd.DataFrame:
    """Seconds each player spent as a non-regular, per kind of ice time.

    Within each team, skaters are ranked by ice time at their position. Time
    played by anyone ranked below the regulars counts as replacement-level
    time: it is what teams actually get when they reach past their lineup."""
    out = pd.DataFrame(0.0, index=pos.index, columns=list(REGULARS))
    s = per_team.copy()
    s["pos"] = s["player_id"].map(pos)
    for toi_col, limits in REGULARS.items():
        rank = s.groupby(["team_id", "pos"])[toi_col].rank(ascending=False, method="first")
        beyond = rank > s["pos"].map(limits)
        out[toi_col] = s[beyond & (s[toi_col] > 0)].groupby("player_id")[toi_col].sum().reindex(pos.index).fillna(0.0)
    return out.rename(columns={"toi5": "pool5", "toi_pp": "pool_pp", "toi_sh": "pool_sh"})


# Role groups: rank within the team at the position, by ice time of that kind.
ROLE_CUTS = {
    "toi5": {"F": [3, 6, 9, 12], "D": [2, 4, 6]},     # lines 1-4 + spares; pairs 1-3 + spares
    "toi_pp": {"F": [4, 8], "D": [1, 2]},              # first unit, second unit, the rest
    "toi_sh": {"F": [2, 4], "D": [2, 4]},
}


def roles(per_team: pd.DataFrame, pos: pd.Series, toi_col: str) -> tuple[dict, list]:
    """Each skater's role on his main team, e.g. "F2" = second-line forward."""
    s = per_team[per_team[toi_col] > 0].copy()
    s["pos"] = s["player_id"].map(pos)
    s["rank"] = s.groupby(["team_id", "pos"])[toi_col].rank(ascending=False, method="first")
    s = s.sort_values(toi_col).groupby("player_id").last()     # the team he played most for
    labels = [f"{g}{i + 1}" for g in ("F", "D") for i in range(len(ROLE_CUTS[toi_col][g]) + 1)]
    index = {lab: i for i, lab in enumerate(labels)}
    out = {}
    for pid, row in s.iterrows():
        cuts = ROLE_CUTS[toi_col][row["pos"]]
        tier = int(np.searchsorted(cuts, row["rank"], side="left"))
        out[int(pid)] = index[f"{row['pos']}{tier + 1}"]
    return out, labels


def _team_check(stints: pd.DataFrame, per_team: pd.DataFrame, gaa: pd.DataFrame, tot: pd.DataFrame,
                home_of: dict, away_of: dict) -> list[dict]:
    """Per team: what actually happened next to what the player ratings add up to."""
    st = stints.copy()
    st["home"], st["away"] = st["game_id"].map(home_of), st["game_id"].map(away_of)
    hours = st["dur"] / 3600.0
    ev = st["state"] == 1
    rows = {}

    def add(team, key, val):
        for t, v in pd.Series(np.asarray(val, float)).groupby(np.asarray(team)).sum().items():
            rows.setdefault(int(t), {}).setdefault(key, 0.0)
            rows[int(t)][key] += float(v)

    e = st[ev]
    add(e["home"], "ev_h", hours[ev]); add(e["away"], "ev_h", hours[ev])
    add(e["home"], "ev_xgf", e["hxg"]); add(e["away"], "ev_xgf", e["axg"])
    add(e["home"], "ev_xga", e["axg"]); add(e["away"], "ev_xga", e["hxg"])
    for state, pp_team, pk_team, col in ((2, "home", "away", "hxg"), (3, "away", "home", "axg")):
        m = st["state"] == state
        add(st.loc[m, pp_team], "pp_h", hours[m]); add(st.loc[m, pp_team], "pp_xgf", st.loc[m, col])
        add(st.loc[m, pk_team], "pk_h", hours[m]); add(st.loc[m, pk_team], "pk_xga", st.loc[m, col])
    t = pd.DataFrame.from_dict(rows, orient="index").fillna(0.0)
    ev_rate = t["ev_xgf"].sum() / t["ev_h"].sum()
    pp_rate = t["pp_xgf"].sum() / max(t["pp_h"].sum(), 1e-9)
    actual = pd.DataFrame({
        "ev_off": t["ev_xgf"] - ev_rate * t["ev_h"], "ev_def": -(t["ev_xga"] - ev_rate * t["ev_h"]),
        "pp": t["pp_xgf"] - pp_rate * t["pp_h"], "pk": -(t["pk_xga"] - pp_rate * t["pk_h"]),
    })
    share = per_team.set_index(["player_id", "team_id"])
    out = []
    for team in actual.index:
        mine = per_team[per_team["team_id"] == team]
        rec = {"team_id": int(team)}
        for comp, toi_col in (("ev_off", "toi5"), ("ev_def", "toi5"), ("pp", "toi_pp"), ("pk", "toi_sh")):
            frac = (mine[toi_col].to_numpy(float)
                    / np.maximum(tot[toi_col].reindex(mine["player_id"]).to_numpy(float), 1.0))
            rec[comp + "_players"] = round(float((gaa[comp].reindex(mine["player_id"]).to_numpy(float) * frac).sum()), 3)
            rec[comp + "_actual"] = round(float(actual.at[team, comp]), 3)
        out.append(rec)
    return out


def skaters(stints: pd.DataFrame, players: pd.DataFrame, shots: pd.DataFrame,
            events: pd.DataFrame, games: pd.DataFrame, names: pd.DataFrame,
            prior: dict | None = None) -> dict:
    """Goals above average for every skater in one regular season.

    Returns a plain dictionary (saved between runs) with one record per
    skater, a per-team cross-check, and the ratings to carry into next
    season. `finalize` turns these into WAR."""
    prior = prior or {}
    ids = set(players["game_id"].unique())
    fade = config.WAR_PRIOR_FADE
    toi_cols = ["toi_all", "toi5", "toi_pp", "toi_sh"]
    per_team = players.groupby(["player_id", "team_id"])[toi_cols].sum().reset_index()
    tot = per_team.groupby("player_id")[toi_cols].sum()
    gp = players.groupby("player_id")["game_id"].nunique()
    pos = names["pos"].reindex(tot.index).map(lambda p: "D" if p == "D" else "F")

    r5, l5 = roles(per_team, pos, "toi5")
    rpp, lpp = roles(per_team, pos, "toi_pp")
    rsh, lsh = roles(per_team, pos, "toi_sh")
    ev = rapm.fit(stints, "ev", config.WAR_LAMBDA_EV, roles=(r5, r5, l5, l5),
                  prior={int(k): (fade * v[0], fade * v[1]) for k, v in prior.get("ev", {}).items()})
    pp = rapm.fit(stints, "pp", config.WAR_LAMBDA_PP, roles=(rpp, rsh, lpp, lsh),
                  prior={int(k): (fade * v[0], fade * v[1]) for k, v in prior.get("pp", {}).items()})
    rating = pd.DataFrame(index=tot.index)
    rating["ev_off"] = pd.Series(ev["off"], index=ev["players"])
    rating["ev_def"] = pd.Series(ev["def"], index=ev["players"])
    rating["pp_off"] = pd.Series(pp["off"], index=pp["players"])
    rating["pk_def"] = pd.Series(pp["def"], index=pp["players"])
    rating = rating.fillna(0.0)
    # Forwards and defensemen are always on the ice together, so the data
    # cannot say which position deserves more of the credit. Each skater is
    # therefore rated against the average at his own position.
    for col, toi_col in (("ev_off", "toi5"), ("ev_def", "toi5"), ("pp_off", "toi_pp"), ("pk_def", "toi_sh")):
        for g in ("F", "D"):
            m = (pos == g) & (tot[toi_col] > 0)
            if m.any() and tot.loc[m, toi_col].sum() > 0:
                rating.loc[pos == g, col] -= np.average(rating.loc[m, col], weights=tot.loc[m, toi_col])
        rating.loc[tot[toi_col] == 0, col] = 0.0
    r = rating

    gaa = pd.DataFrame(index=tot.index)
    gaa["ev_off"] = r["ev_off"] * tot["toi5"] / 3600.0
    gaa["ev_def"] = -r["ev_def"] * tot["toi5"] / 3600.0
    gaa["pp"] = r["pp_off"] * tot["toi_pp"] / 3600.0
    gaa["pk"] = -r["pk_def"] * tot["toi_sh"] / 3600.0

    s = shots[shots["game_id"].isin(ids) & shots["shooter_id"].notna()
              & ~shots["strength"].isin(["EN", "PS"])]
    by = s.groupby("shooter_id")
    ixg = by["xg"].sum().reindex(tot.index).fillna(0.0)
    goals = by["goal"].sum().reindex(tot.index).fillna(0.0)
    # one season of finishing is mostly luck, so only part of it is credited
    gaa["fin"] = (goals - ixg) * ixg / (ixg + config.WAR_FINISHING_K)
    gaa["fin"] -= gaa["fin"].sum() * tot["toi_all"] / tot["toi_all"].sum()   # centre on average

    taken, drawn, n_pen = penalties(events, ids)
    in_season = shots["game_id"].isin(ids)
    pp_goals = float(shots.loc[in_season & (shots["strength"] == "PP"), "goal"].sum())
    sh_goals = float(shots.loc[in_season & (shots["strength"] == "SH"), "goal"].sum())
    pen_value = (pp_goals - sh_goals) / n_pen if n_pen else 0.0
    net = drawn.reindex(tot.index).fillna(0.0) - taken.reindex(tot.index).fillna(0.0)
    avg = {g: float(net[pos == g].sum()) / max(float(tot.loc[pos == g, "toi_all"].sum()), 1.0) for g in ("F", "D")}
    gaa["pen"] = pen_value * (net - pos.map(avg) * tot["toi_all"])

    pool = _pool_seconds(per_team, pos)
    abbr = {}
    for g in games.itertuples(index=False):
        abbr[int(g.home_id)], abbr[int(g.away_id)] = g.home_abbrev, g.away_abbrev
    main_team = per_team.sort_values("toi_all").groupby("player_id")["team_id"].last()
    shares = {}
    for row in per_team.itertuples(index=False):
        shares.setdefault(int(row.player_id), {})[abbr.get(int(row.team_id), str(row.team_id))] = round(
            float(row.toi_all) / max(float(tot.at[row.player_id, "toi_all"]), 1.0), 4)
    records = []
    for pid in tot.index:
        nm = names.loc[pid] if pid in names.index else None
        rec = {"id": int(pid), "name": None if nm is None else nm["name"],
               "team": None if nm is None else nm["team"], "pos": pos[pid], "gp": int(gp[pid]),
               "main_team": abbr.get(int(main_team[pid])), "shares": shares.get(int(pid), {})}
        for c in toi_cols:
            rec[c] = int(tot.at[pid, c])
        for c in ("pool5", "pool_pp", "pool_sh"):
            rec[c] = int(pool.at[pid, c])
        for c in COMPONENTS:
            rec[c] = round(float(gaa.at[pid, c]), 4)
        records.append(rec)

    home_of = dict(zip(games["game_id"].astype(int), games["home_id"].astype(int)))
    away_of = dict(zip(games["game_id"].astype(int), games["away_id"].astype(int)))
    return {
        "players": records,
        "teams": _team_check(stints, per_team, gaa, tot, home_of, away_of),
        "ratings": {
            # each skater relative to his role; this is what carries into next season
            "ev": {str(int(p)): [round(float(a), 5), round(float(b), 5)]
                   for p, a, b in zip(ev["players"], ev["off_dev"], ev["def_dev"])},
            "pp": {str(int(p)): [round(float(a), 5), round(float(b), 5)]
                   for p, a, b in zip(pp["players"], pp["off_dev"], pp["def_dev"])},
        },
        "notes": {"penalty_value": round(pen_value, 4),
                  "rating_per60": {str(int(p)): [round(float(x), 4) for x in r.loc[p]] for p in tot.index},
                  "ev_controls": {k: float(v) for k, v in ev["controls"].items()},
                  "pp_controls": {k: float(v) for k, v in pp["controls"].items()}},
    }


def dollars_per_war(season: int, league_war: float) -> tuple[float, float]:
    """(millions of dollars one win costs, league-minimum salary) for a season.

    Every team has to fill a roster at the minimum anyway. What is left of
    league payroll buys all the wins above replacement, so dividing one by
    the other gives the going rate for a win."""
    cap, minimum = config.SALARY_CAP.get(season) or config.SALARY_CAP[max(config.SALARY_CAP)]
    payroll = 32 * cap * config.CAP_SPEND_SHARE
    floor = 32 * config.ROSTER_SPOTS * minimum
    return ((payroll - floor) / league_war if league_war > 0 else 0.0), minimum


RAPM_PARTS = ["ev_off", "ev_def", "pp", "pk"]
POOL_OF = {"ev_off": ("pool5", "toi5"), "ev_def": ("pool5", "toi5"), "pp": ("pool_pp", "toi_pp"),
           "pk": ("pool_sh", "toi_sh"), "fin": ("pool5", "toi5"), "pen": ("pool5", "toi5")}


def finalize(seasons: dict, goalie_rows: dict, gpw: float, complete: set) -> dict:
    """Turn every season's goals above average into WAR.

    seasons      {season: what `skaters` returned}
    goalie_rows  {season: the goalie table rows (with gsax and fa)}
    complete     seasons that are finished; the league-wide settings
                 (scaling, replacement level) are measured on these only.
    Returns {season: {"rows": [...], "notes": {...}}}."""
    ref = [s for s in seasons if s in complete] or list(seasons)

    # 1. Scale: the regression is cautious about splitting credit between
    #    teammates, which also trims the total a little. Stretch each part so
    #    that players' credit adds up to what their teams actually did.
    scale = {}
    for comp in RAPM_PARTS:
        x = np.array([t[comp + "_players"] for s in ref for t in seasons[s]["teams"]], float)
        y = np.array([t[comp + "_actual"] for s in ref for t in seasons[s]["teams"]], float)
        slope = float((x * y).sum() / (x * x).sum()) if (x * x).sum() > 0 else 1.0
        scale[comp] = round(float(np.clip(slope, 1.0, 1.6)), 3)

    def frame(s):
        d = pd.DataFrame(seasons[s]["players"])
        for comp in RAPM_PARTS:
            d[comp] = d[comp] * scale[comp]
        return d

    # 2. Replacement level: what teams get, per second, from skaters outside
    #    their regular lineup, pooled over the finished seasons.
    repl = {comp: {} for comp in COMPONENTS}
    pooled = pd.concat([frame(s) for s in ref], ignore_index=True)
    for comp in COMPONENTS:
        pool_col, toi_col = POOL_OF[comp]
        for g in ("F", "D"):
            d = pooled[(pooled["pos"] == g) & (pooled[toi_col] > 0)]
            seconds = float(d[pool_col].sum())
            value = float((d[comp] * d[pool_col] / d[toi_col]).sum())
            repl[comp][g] = value / seconds if seconds > 0 else 0.0

    gref = pd.concat([pd.DataFrame(goalie_rows[s]).assign(season=s) for s in ref if goalie_rows.get(s)],
                     ignore_index=True) if any(goalie_rows.get(s) for s in ref) else pd.DataFrame()
    g_rate = 0.0
    if len(gref):
        gref["first_team"] = gref["team"].fillna("").str.split("/").str[0]
        gref["rank"] = gref.groupby(["season", "first_team"])["fa"].rank(ascending=False, method="first")
        pool = gref[gref["rank"] > GOALIE_REGULARS]
        g_rate = float(pool["gsax"].sum()) / float(pool["fa"].sum()) if pool["fa"].sum() else 0.0

    out = {}
    for s in seasons:
        d = frame(s)
        rows = []
        for x in d.itertuples(index=False):
            rec = {"id": x.id, "name": x.name, "team": x.team, "pos": x.pos, "gp": x.gp,
                   "toi": round(x.toi_all / 60.0)}
            total = 0.0
            for comp in COMPONENTS:
                gar = getattr(x, comp) - repl[comp][x.pos] * getattr(x, POOL_OF[comp][1])
                rec[comp] = round(gar / gpw, 2)
                total += gar
            rec["gar"] = round(total, 1)
            rec["war"] = round(total / gpw, 2)
            rec["war82"] = round(total / gpw / x.gp * 82.0, 2) if x.gp else None
            rec["_main"], rec["_shares"] = x.main_team, x.shares
            rec["_toi"], rec["_toi5"], rec["_toi_pp"], rec["_toi_sh"] = x.toi_all, x.toi5, x.toi_pp, x.toi_sh
            rows.append(rec)
        for x in goalie_rows.get(s) or []:
            gar = float(x["gsax"]) - g_rate * float(x["fa"])
            first = (x.get("team") or "").split("/")[0]
            rows.append({"id": x["id"], "name": x["name"], "team": x["team"], "pos": "G", "gp": x["gp"],
                         "toi": x.get("toi"), "goalie": round(gar / gpw, 2), "gar": round(gar, 1),
                         "war": round(gar / gpw, 2), "war82": None, "_main": first, "_shares": {first: 1.0}})
        rows.sort(key=lambda r: -r["war"])
        out[s] = {"rows": rows, "notes": {
            "league_war": round(sum(r["war"] for r in rows), 1),
            "goals_per_win": gpw, "scale": scale,
            "penalty_value": seasons[s]["notes"].get("penalty_value"),
            "replacement_per60": {c: {g: round(v * 3600.0, 3) for g, v in repl[c].items()} for c in COMPONENTS},
            "goalie_replacement_per_100_shots": round(100 * g_rate, 3),
            "total_war": round(sum(r["war"] for r in rows), 1),
            "skater_war": round(sum(r["war"] for r in rows if r["pos"] != "G"), 1),
            "goalie_war": round(sum(r["war"] for r in rows if r["pos"] == "G"), 1),
            "finished": s in complete,
        }}
    # Dollar values: a full season's league WAR sets the price of a win.
    full = [out[s]["notes"]["league_war"] for s in out if s in complete]
    typical = float(np.mean(full)) if full else 620.0
    for s, res in out.items():
        league = res["notes"]["league_war"] if s in complete else typical
        rate, minimum = dollars_per_war(s, league)
        res["notes"]["dollars_per_war"], res["notes"]["min_salary"] = round(rate, 3), minimum
        for r in res["rows"]:
            # the minimum salary is earned by the game, so a call-up is not credited a full one
            base = minimum * min(1.0, (r["gp"] or 0) / 82.0)
            r["value"] = round(max(base, base + r["war"] * rate), 2)
    return out


def team_totals(rows: list[dict]) -> dict:
    """Sum WAR by team, splitting traded players by where they played."""
    out = {}
    for r in rows:
        for team, share in (r.get("_shares") or {}).items():
            out[team] = out.get(team, 0.0) + r["war"] * share
    return {k: round(v, 2) for k, v in out.items()}
