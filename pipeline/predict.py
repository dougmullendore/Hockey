"""Game win probabilities, projected standings and playoff odds.

Step 1, team strength. Every team carries two running numbers, updated
after each game and weighted toward recent games:

  chances   expected-goal difference per game (how well it out-chances teams)
  results   goal difference beyond the chances (finishing and goaltending)

Chances are the steadier signal, so they update faster and count for more.
Both are pulled toward zero until a team has played enough games, and fade
by half over each summer.

Step 2, one game. The gap between the two teams' numbers, home ice, and
whether either side played yesterday go into a logistic regression fitted
on every game since 2021-22. It returns the home team's chance of winning.

Step 3, the season. The rest of the schedule is played out thousands of
times with those chances (plus some doubt about how good each team really
is), then the playoff bracket. Counting how often each thing happens gives
projected points, playoff odds and Stanley Cup odds."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from . import config, store

ALIAS = {"ARI": "UTA"}            # the Arizona franchise moved to Utah in 2024
FEATURES = ["chances", "results", "home_played_yesterday", "away_played_yesterday"]

# Fallback if the league's standings feed is unavailable.
DIVISIONS = {
    "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    "Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
    "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
}
CONFERENCE_OF = {"Atlantic": "Eastern", "Metropolitan": "Eastern", "Central": "Western", "Pacific": "Western"}


def history(site_data: Path) -> pd.DataFrame:
    """Every finished game, oldest first, with goals (shootouts removed) and xG."""
    rows = []
    for f in sorted(Path(site_data).glob("games_*_*.json")):
        season = int(f.name.split("_")[1])
        for g in store.read_json(f, []) or []:
            if g.get("hs") is None or g.get("as") is None:
                continue
            rows.append({**g, "season": season})
    if not rows:
        return pd.DataFrame()
    G = pd.DataFrame(rows).sort_values(["date", "id"]).reset_index(drop=True)
    G["home"], G["away"] = G["home"].replace(ALIAS), G["away"].replace(ALIAS)
    home_won = G["hs"] > G["as"]
    shootout = G["end"] == "SO"
    G["hg"] = G["hs"] - np.where(shootout & home_won, 1, 0)   # the league adds a goal for the shootout winner
    G["ag"] = G["as"] - np.where(shootout & ~home_won, 1, 0)
    G["y"] = home_won.astype(int)
    G["day"] = pd.to_datetime(G["date"])
    return G


class Ratings:
    """Running team strength. Call `features` before a game and `update` after."""

    def __init__(self):
        self.state, self.last, self.season = {}, {}, None

    def _team(self, t):
        return self.state.setdefault(t, [0.0, 0.0, 0.0, 0.0])

    def new_season(self, season):
        if self.season is not None and season != self.season:
            for s in self.state.values():
                for j in range(4):
                    s[j] *= config.PRED_SUMMER_FADE
                # rosters change over the summer: pull every team toward average
                s[0] *= config.PRED_SUMMER_REGRESS
                s[2] *= config.PRED_SUMMER_REGRESS
        self.season = season

    def values(self, t):
        s = self._team(t)
        return s[0] / (s[1] + config.PRED_CHANCES_PRIOR), s[2] / (s[3] + config.PRED_RESULTS_PRIOR)

    def played_yesterday(self, t, day) -> float:
        return 1.0 if t in self.last and (day - self.last[t]).days <= 1 else 0.0

    def features(self, home, away, day) -> list:
        h, a = self.values(home), self.values(away)
        return [h[0] - a[0], h[1] - a[1], self.played_yesterday(home, day), self.played_yesterday(away, day)]

    def update(self, home, away, day, hxg, axg, hg, ag):
        xd, gd = hxg - axg, hg - ag
        for t, sign in ((home, 1.0), (away, -1.0)):
            s = self._team(t)
            s[0] = s[0] * config.PRED_CHANCES_DECAY + sign * xd
            s[1] = s[1] * config.PRED_CHANCES_DECAY + 1.0
            s[2] = s[2] * config.PRED_RESULTS_DECAY + sign * (gd - xd)
            s[3] = s[3] * config.PRED_RESULTS_DECAY + 1.0
            self.last[t] = day


def walk(G: pd.DataFrame) -> tuple[np.ndarray, Ratings]:
    """Features for every past game, each using only games played before it."""
    r, X = Ratings(), np.zeros((len(G), len(FEATURES)))
    for i, g in enumerate(G.itertuples(index=False)):
        r.new_season(g.season)
        X[i] = r.features(g.home, g.away, g.day)
        r.update(g.home, g.away, g.day, g.hxg, g.axg, g.hg, g.ag)
    return X, r


def _fit(X, y):
    return LogisticRegression(C=100.0).fit(X, y)


def backtest(G: pd.DataFrame, X: np.ndarray) -> dict:
    """Honest test: predict each season with weights fitted on the other seasons."""
    seasons = sorted(G["season"].unique())
    if len(seasons) < 3:
        return {}
    p = np.full(len(G), np.nan)
    for s in seasons[1:]:
        test = (G["season"] == s).to_numpy()
        p[test] = _fit(X[~test], G["y"][~test]).predict_proba(X[test])[:, 1]
    ev = ~np.isnan(p)
    y = G["y"].to_numpy()[ev]
    q = p[ev]
    ll = float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))
    base = float(np.mean(y))
    bins = []
    for lo, hi in ((0, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, 1.01)):
        m = (q >= lo) & (q < hi)
        if m.sum() >= 30:
            bins.append({"games": int(m.sum()), "predicted": round(float(q[m].mean()), 3),
                         "actual": round(float(y[m].mean()), 3)})
    return {"games": int(ev.sum()), "log_loss": round(ll, 4),
            "baseline_log_loss": round(float(-(base * np.log(base) + (1 - base) * np.log(1 - base))), 4),
            "accuracy": round(float(((q > .5) == (y == 1)).mean()), 3),
            "home_win_rate": round(base, 3), "calibration": bins,
            "first_season_tested": int(seasons[1])}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def _overtime(p):
    """Chance a game goes past regulation, and the home side's share of those."""
    p_ot = np.clip(0.238 - 0.14 * np.abs(p - 0.5), 0.05, 0.3)
    q = np.clip(0.512 + 0.33 * (p - 0.5), 0.05, 0.95)
    return p_ot, q


def _series(ph, pa):
    """Chance the higher seed wins a best-of-seven (home for games 1, 2, 5, 7)."""
    ph, pa = np.asarray(ph, float), np.asarray(pa, float)
    state = {(0, 0): np.ones_like(ph)}
    won = np.zeros_like(ph)
    for at_home in (True, True, False, False, True, False, True):
        p = ph if at_home else pa
        nxt = {}
        for (w, l), prob in state.items():
            if w + 1 == 4:
                won = won + prob * p
            else:
                nxt[(w + 1, l)] = nxt.get((w + 1, l), 0) + prob * p
            if l + 1 < 4:
                nxt[(w, l + 1)] = nxt.get((w, l + 1), 0) + prob * (1 - p)
        state = nxt
    return won


def records(G: pd.DataFrame, season: int) -> pd.DataFrame:
    """Standings so far from our own stored games (regular season)."""
    g = G[(G["season"] == season) & (G["type"] == 2)]
    rows = {}
    for x in g.itertuples(index=False):
        extra, so = x.end in ("OT", "SO"), x.end == "SO"
        for team, won in ((x.home, bool(x.y)), (x.away, not bool(x.y))):
            r = rows.setdefault(team, {"gp": 0, "w": 0, "l": 0, "otl": 0, "rw": 0, "row": 0})
            r["gp"] += 1
            if won:
                r["w"] += 1
                r["rw"] += 0 if extra else 1
                r["row"] += 0 if so else 1
            elif extra:
                r["otl"] += 1
            else:
                r["l"] += 1
    d = pd.DataFrame.from_dict(rows, orient="index")
    if len(d):
        d["pts"] = 2 * d["w"] + d["otl"]
    return d


def simulate(teams: list, division_of: dict, rec: pd.DataFrame, remaining: list, strength: dict,
             model, n: int = 10000, seed: int = 7) -> dict:
    """Play out the rest of the season `n` times.

    remaining: [(home, away, home_played_yesterday, away_played_yesterday)]
    strength:  {team: (chances, results)}"""
    rng = np.random.default_rng(seed)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    b0 = float(model.intercept_[0])
    c = model.coef_[0]
    base = np.array([c[0] * strength.get(t, (0, 0))[0] + c[1] * strength.get(t, (0, 0))[1] for t in teams])
    # doubt about each team's true level, fixed within one simulated season
    S = base[None, :] + rng.normal(0.0, config.PRED_STRENGTH_DOUBT, size=(n, T))

    def start(col):
        return np.array([float(rec.at[t, col]) if t in rec.index else 0.0 for t in teams])

    pts = np.tile(start("pts"), (n, 1))
    wins = np.tile(start("w"), (n, 1))
    rw = np.tile(start("rw"), (n, 1))
    row = np.tile(start("row"), (n, 1))
    for home, away, hb, ab in remaining:
        if home not in idx or away not in idx:
            continue
        h, a = idx[home], idx[away]
        p = _sigmoid(b0 + S[:, h] - S[:, a] + c[2] * hb + c[3] * ab)
        p_ot, q = _overtime(p)
        home_reg = np.clip(p - p_ot * q, 0.0, 1.0)
        home_ot = p_ot * q
        away_ot = p_ot * (1 - q)
        u = rng.random(n)
        r_home = u < home_reg
        o_home = (u >= home_reg) & (u < home_reg + home_ot)
        o_away = (u >= home_reg + home_ot) & (u < home_reg + home_ot + away_ot)
        r_away = ~(r_home | o_home | o_away)
        pts[:, h] += 2 * (r_home | o_home) + o_away
        pts[:, a] += 2 * (r_away | o_away) + o_home
        wins[:, h] += r_home | o_home
        wins[:, a] += r_away | o_away
        rw[:, h] += r_home
        rw[:, a] += r_away
        # about a third of games past regulation end in a shootout, which does not count for ROW
        not_so = rng.random(n) > 0.33
        row[:, h] += r_home | (o_home & not_so)
        row[:, a] += r_away | (o_away & not_so)

    # ---- seeding: points, then regulation wins, then regulation + overtime wins
    key = pts * 1e6 + rw * 1e3 + row + rng.random((n, T))
    rows_ = np.arange(n)
    divisions = sorted(set(division_of.values()))
    conferences = sorted({CONFERENCE_OF.get(d, d) for d in divisions})
    made = np.zeros((n, T), dtype=bool)
    won_div = np.zeros((n, T), dtype=bool)
    reach = {r: np.zeros((n, T)) for r in ("r2", "r3", "final", "cup")}

    def play(t1, t2):
        hi = np.where(key[rows_, t1] >= key[rows_, t2], t1, t2)
        lo = np.where(hi == t1, t2, t1)
        gap = S[rows_, hi] - S[rows_, lo]
        p_series = _series(_sigmoid(b0 + gap), 1.0 - _sigmoid(b0 - gap))
        return np.where(rng.random(n) < p_series, hi, lo)

    champs = []
    for conf in conferences:
        divs = [d for d in divisions if CONFERENCE_OF.get(d, d) == conf]
        if len(divs) != 2:
            continue
        seeds, taken = {}, np.zeros((n, T), dtype=bool)
        for d in divs:
            members = np.array([idx[t] for t in teams if division_of.get(t) == d])
            order = np.argsort(-key[:, members], axis=1)
            seeds[d] = members[order[:, :3]]                       # n x 3
            for k in range(3):
                taken[rows_, seeds[d][:, k]] = True
            won_div[rows_, seeds[d][:, 0]] = True
        in_conf = np.array([idx[t] for t in teams if CONFERENCE_OF.get(division_of.get(t), "") == conf])
        rest = np.where(taken[:, in_conf], -np.inf, key[:, in_conf])
        wc = in_conf[np.argsort(-rest, axis=1)[:, :2]]              # n x 2, best first
        for k in range(3):
            made[rows_, seeds[divs[0]][:, k]] = True
            made[rows_, seeds[divs[1]][:, k]] = True
        made[rows_, wc[:, 0]] = True
        made[rows_, wc[:, 1]] = True
        w0, w1 = seeds[divs[0]][:, 0], seeds[divs[1]][:, 0]
        first_is_top = key[rows_, w0] >= key[rows_, w1]
        # the better division winner draws the second wild card
        opp0 = np.where(first_is_top, wc[:, 1], wc[:, 0])
        opp1 = np.where(first_is_top, wc[:, 0], wc[:, 1])
        semis = []
        for d, opp in ((divs[0], opp0), (divs[1], opp1)):
            a = play(seeds[d][:, 0], opp)
            b = play(seeds[d][:, 1], seeds[d][:, 2])
            reach["r2"][rows_, a] += 1
            reach["r2"][rows_, b] += 1
            w = play(a, b)
            reach["r3"][rows_, w] += 1
            semis.append(w)
        champ = play(semis[0], semis[1])
        reach["final"][rows_, champ] += 1
        champs.append(champ)
    if len(champs) == 2:
        cup = play(champs[0], champs[1])
        reach["cup"][rows_, cup] += 1

    out = {}
    for t, i in idx.items():
        out[t] = {
            "proj_pts": round(float(pts[:, i].mean()), 1),
            "pts_lo": int(np.percentile(pts[:, i], 10)), "pts_hi": int(np.percentile(pts[:, i], 90)),
            "proj_w": round(float(wins[:, i].mean()), 1),
            "playoffs": round(100 * float(made[:, i].mean()), 1),
            "division": round(100 * float(won_div[:, i].mean()), 1),
            "r2": round(100 * float(reach["r2"][:, i].mean()), 1),
            "r3": round(100 * float(reach["r3"][:, i].mean()), 1),
            "final": round(100 * float(reach["final"][:, i].mean()), 1),
            "cup": round(100 * float(reach["cup"][:, i].mean()), 1),
        }
    return out


def _divisions(data: Path, teams: set) -> dict:
    rows = store.read_json(Path(data) / "official" / "standings.json", []) or []
    found = {r["team"]: r["division"] for r in rows if r.get("team") and r.get("division")}
    if not teams or not teams <= set(found):
        found = {t: d for d, members in DIVISIONS.items() for t in members}
    return found


def build(data: Path, out: Path, log, sims: int | None = None) -> dict:
    """Write odds.json: upcoming games, projected standings, playoff and Cup odds."""
    data, out = Path(data), Path(out)
    G = history(out)
    if len(G) < 500:
        return {"skipped": "not enough games"}
    X, ratings = walk(G)
    model = _fit(X, G["y"])
    test = backtest(G, X)

    season = max(s for s in config.SEASONS if (data / "schedule" / f"{s}.json").exists()
                 or s == int(G["season"].max()))
    ratings.new_season(season)                      # fade once if the new season has not started
    sched = store.read_json(data / "schedule" / f"{season}.json", []) or []
    done = set(G.loc[G["season"] == season, "id"].astype(int))
    future = [g for g in sched if g["game_id"] not in done and g.get("home") and g.get("away")
              and g.get("schedule_state") in (None, "OK") and g.get("game_type") == 2]
    future.sort(key=lambda g: (g.get("start_utc") or g["date"], g["game_id"]))

    # who plays the day before whom, across the whole remaining schedule
    last = dict(ratings.last)
    remaining, upcoming = [], []
    today = dt.datetime.now(dt.timezone.utc).date()
    horizon = (today + dt.timedelta(days=8)).isoformat()
    for g in future:
        home, away = ALIAS.get(g["home"], g["home"]), ALIAS.get(g["away"], g["away"])
        day = pd.Timestamp(g["date"])
        hb = 1.0 if home in last and (day - last[home]).days <= 1 else 0.0
        ab = 1.0 if away in last and (day - last[away]).days <= 1 else 0.0
        last[home] = last[away] = day
        remaining.append((home, away, hb, ab))
        if g["date"] <= horizon and len(upcoming) < 80:
            h, a = ratings.values(home), ratings.values(away)
            p = float(model.predict_proba([[h[0] - a[0], h[1] - a[1], hb, ab]])[0, 1])
            upcoming.append({"id": g["game_id"], "date": g["date"], "start_utc": g.get("start_utc"),
                             "home": home, "away": away, "p_home": round(p, 3),
                             "home_b2b": bool(hb), "away_b2b": bool(ab)})

    rec = records(G, season)
    teams = sorted(set(rec.index) | {t for g in remaining for t in g[:2]})
    division_of = _divisions(data, set(teams))
    teams = [t for t in teams if t in division_of]
    strength = {t: ratings.values(t) for t in teams}
    c = model.coef_[0]
    table = []
    sim = simulate(teams, division_of, rec, remaining, strength, model,
                   n=sims or config.PRED_SIMULATIONS) if teams else {}
    for t in teams:
        s = strength[t]
        level = float(c[0] * s[0] + c[1] * s[1])
        r = rec.loc[t] if t in rec.index else None
        table.append({
            "team": t, "division": division_of[t], "conference": CONFERENCE_OF.get(division_of[t], ""),
            "gp": int(r["gp"]) if r is not None else 0, "w": int(r["w"]) if r is not None else 0,
            "l": int(r["l"]) if r is not None else 0, "otl": int(r["otl"]) if r is not None else 0,
            "pts": int(r["pts"]) if r is not None else 0,
            "strength": round(100 * float(_sigmoid(level)), 1),      # win % against an average team, neutral ice
            "chances": round(float(s[0]), 2), "results": round(float(s[1]), 2),
            **sim.get(t, {}),
        })
    table.sort(key=lambda r: -(r.get("proj_pts") or 0))
    doc = {
        "season": season, "sims": sims or config.PRED_SIMULATIONS,
        "games_left": len(remaining), "teams": table, "upcoming": upcoming,
        "model": {**test, "weights": {k: round(float(v), 3) for k, v in zip(FEATURES, c)},
                  "home_edge": round(100 * float(_sigmoid(model.intercept_[0])), 1)},
    }
    store.write_json(out / "odds.json", doc, compact=True)

    # keep a dated trail so the site can chart how the odds moved
    trail = store.read_json(data / "odds_history.json", {}) or {}
    if trail.get("season") != season:
        trail = {"season": season, "days": {}}
    trail["days"][today.isoformat()] = {r["team"]: [r.get("playoffs"), r.get("cup"), r.get("proj_pts")] for r in table}
    store.write_json(data / "odds_history.json", trail, compact=True)
    store.write_json(out / "odds_history.json", trail, compact=True)
    log(f"odds: {len(upcoming)} upcoming games, {len(remaining)} left to simulate, backtest {test.get('log_loss')}"
        f" vs {test.get('baseline_log_loss')}")
    return {"teams": len(table), "upcoming": len(upcoming), "games_left": len(remaining)}
