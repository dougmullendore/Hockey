"""Who was on the ice.

Shift charts say when each player stepped on and off. Laid over the
play-by-play, they tell us which ten skaters were out for every shot, and
that is what makes these numbers possible:

  * on-ice stats   what happened for and against while a skater was out
  * lines, pairs   the same, for forward trios and defence pairs
  * with/without   how two teammates do together and apart

Everything here is at five-on-five (five skaters and a goalie per side),
where most of the game is played and where special teams do not distort it."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ATTEMPTS = ("goal", "shot-on-goal", "missed-shot", "blocked-shot")
# what gets counted for and against, in this order
STATS = ["c", "f", "s", "xg", "g"]  # Corsi, Fenwick, shots on goal, xG, goals
FOR = [k + "f" for k in STATS]
AGAINST = [k + "a" for k in STATS]


def _weights(ev: pd.DataFrame) -> np.ndarray:
    """One column per STATS entry: how much each shot attempt adds."""
    typ = ev["type"].to_numpy()
    return np.column_stack([
        np.ones(len(ev)),
        (typ != "blocked-shot").astype(float),
        np.isin(typ, ["goal", "shot-on-goal"]).astype(float),
        ev["xg"].fillna(0.0).to_numpy(float),
        (typ == "goal").astype(float),
    ])


def _game(game, sh: pd.DataFrame, ro: pd.DataFrame, ev: pd.DataFrame):
    """On-ice sums for one game. Returns (players, combos, pairs, teams, checks)."""
    gid, home_id, away_id = int(game.game_id), int(game.home_id), int(game.away_id)
    pid = ro["player_id"].to_numpy("int64")
    team = ro["team_id"].to_numpy("int64")
    pos = ro["position"].fillna("").to_numpy(str)
    col = {p: i for i, p in enumerate(pid)}
    n = len(pid)

    max_period = int(sh["period"].max())
    if int(game.game_type) == 2:
        max_period = min(max_period, 4)  # no shifts in a shootout
    T = max_period * 1200
    on = np.zeros((T, n), dtype=bool)
    for p, per, a, b in zip(sh["player_id"].to_numpy("int64"), sh["period"].to_numpy("int64"),
                            sh["start"].to_numpy("int64"), sh["end"].to_numpy("int64")):
        c = col.get(p)
        if c is None or per > max_period:
            continue
        base = (per - 1) * 1200
        on[base + a: base + b, c] = True

    goalie = pos == "G"
    is_home = team == home_id
    hs = on[:, is_home & ~goalie].sum(1)
    as_ = on[:, ~is_home & ~goalie].sum(1)
    hg = on[:, is_home & goalie].sum(1)
    ag = on[:, ~is_home & goalie].sum(1)
    five = (hs == 5) & (as_ == 5) & (hg == 1) & (ag == 1)

    # ---- shot attempts, placed on the second just before they happened ----
    per = ev["period"].to_numpy("int64")
    sec = ev["period_seconds"].to_numpy("int64")
    idx = (per - 1) * 1200 + np.maximum(sec - 1, 0)
    ok = (per <= max_period) & (idx < T)
    ev, idx = ev[ok], idx[ok]
    all_goals = int((ev["type"] == "goal").sum())
    keep = five[idx]
    ev, idx = ev[keep], idx[keep]
    w = _weights(ev)                       # events x 5
    ev_team = ev["team_id"].to_numpy("int64")
    E = on[idx]                            # events x players
    same = team[None, :] == ev_team[:, None]
    F = (E & same).astype(float)
    A = (E & ~same).astype(float)
    p_for, p_against = F.T @ w, A.T @ w    # players x 5

    toi_all = on.sum(0)
    on5 = on[five]
    toi5 = on5.sum(0)
    skater = ~goalie
    played = toi_all > 0
    players = pd.DataFrame({
        "game_id": gid, "team_id": team[played & skater], "player_id": pid[played & skater],
        "toi_all": toi_all[played & skater], "toi5": toi5[played & skater],
    })
    for j, k in enumerate(STATS):
        players[k + "f"] = p_for[played & skater, j]
        players[k + "a"] = p_against[played & skater, j]

    # ---- team totals at 5v5 (for "relative to teammates") -----------------
    teams = []
    for t in (home_id, away_id):
        mine = ev_team == t
        teams.append([gid, t, int(five.sum()), *w[mine].sum(0), *w[~mine].sum(0)])
    teams = pd.DataFrame(teams, columns=["game_id", "team_id", "toi5", *FOR, *AGAINST])

    # ---- forward lines and defence pairs ---------------------------------
    combos = []
    for t in (home_id, away_id):
        mine = (ev_team == t)
        for kind, size, members in (("F", 3, np.isin(pos, ["C", "L", "R"])), ("D", 2, pos == "D")):
            cols = np.flatnonzero((team == t) & members)
            if len(cols) < size or len(cols) > 60:
                continue
            bits = (1 << np.arange(len(cols), dtype=np.int64))
            key = on[:, cols] @ bits
            exact = on[:, cols].sum(1) == size
            k5 = key[five & exact]
            if not len(k5):
                continue
            uniq, secs = np.unique(k5, return_counts=True)
            ek, eok = key[idx], exact[idx]
            sums = {}
            for u in np.unique(ek[eok]):
                m = eok & (ek == u)
                sums[int(u)] = (w[m & mine].sum(0), w[m & ~mine].sum(0))
            zero = np.zeros(len(STATS))
            for u, s in zip(uniq, secs):
                ids = tuple(sorted(int(pid[cols[b]]) for b in range(len(cols)) if (int(u) >> b) & 1))
                f, a = sums.get(int(u), (zero, zero))
                combos.append([gid, t, kind, "-".join(map(str, ids)), int(s), *f, *a])
    combos = pd.DataFrame(combos, columns=["game_id", "team_id", "kind", "key", "toi5", *FOR, *AGAINST])

    # ---- every pair of teammates, for with-or-without --------------------
    pairs = []
    for t in (home_id, away_id):
        cols = np.flatnonzero((team == t) & skater & played)
        if len(cols) < 2:
            continue
        S = on5[:, cols].astype(np.float32)
        together = S.T @ S
        mine = ev_team == t
        Ef, Ea = E[mine][:, cols].astype(float), E[~mine][:, cols].astype(float)
        wf, wa = w[mine], w[~mine]
        mats = [Ef.T @ (Ef * wf[:, [j]]) for j in range(len(STATS))] + \
               [Ea.T @ (Ea * wa[:, [j]]) for j in range(len(STATS))]
        i, j = np.triu_indices(len(cols), k=1)
        live = together[i, j] > 0
        i, j = i[live], j[live]
        a, b = pid[cols[i]], pid[cols[j]]
        frame = pd.DataFrame({"game_id": gid, "team_id": t, "p1": np.minimum(a, b),
                              "p2": np.maximum(a, b), "toi5": together[i, j]})
        for name, m in zip(FOR + AGAINST, mats):
            frame[name] = m[i, j]
        pairs.append(frame)
    pairs = pd.concat(pairs, ignore_index=True) if pairs else pd.DataFrame()

    goals5 = ev["type"].to_numpy() == "goal"
    checks = {
        "game_id": gid,
        "five_seconds": int(five.sum()),
        "goals": all_goals,
        "goals5": int(goals5.sum()),
        # at 5v5 exactly five skaters per side should be out for every goal
        "skaters_on_for_goal": float((E[goals5][:, skater].sum(1)).mean()) if goals5.any() else np.nan,
        "odd_seconds": int(((hs > 6) | (as_ > 6) | (hg > 1) | (ag > 1)).sum()),
    }
    return players, combos, pairs, teams, checks


def build(games: pd.DataFrame, events: pd.DataFrame, rosters: pd.DataFrame,
          shifts: pd.DataFrame, shots: pd.DataFrame, log=None) -> dict:
    """Run every game of a season. Returns per-game tables (not yet summed)."""
    att = events[events["type"].isin(ATTEMPTS) & (events["period_type"] != "SO")
                 & events["team_id"].notna()]
    att = att[["game_id", "idx", "period", "period_seconds", "type", "team_id"]].merge(
        shots[["game_id", "idx", "xg", "strength"]], on=["game_id", "idx"], how="left")
    # a penalty shot is not a five-on-five event even if the clock says so
    att = att[att["strength"].fillna("") != "PS"]
    by_game = {"sh": dict(tuple(shifts.groupby("game_id"))),
               "ro": dict(tuple(rosters.groupby("game_id"))),
               "ev": dict(tuple(att.groupby("game_id")))}
    out = {"players": [], "combos": [], "pairs": [], "teams": [], "checks": []}
    skipped = 0
    for game in games.itertuples(index=False):
        gid = int(game.game_id)
        sh, ro, ev = by_game["sh"].get(gid), by_game["ro"].get(gid), by_game["ev"].get(gid)
        if sh is None or ro is None or ev is None or len(sh) < 200:
            skipped += 1
            continue
        try:
            p, c, w, t, chk = _game(game, sh, ro, ev)
        except Exception as e:  # one broken game must not sink the season
            skipped += 1
            if log:
                log(f"on-ice: game {gid} skipped: {e!r}")
            continue
        out["players"].append(p); out["combos"].append(c); out["pairs"].append(w)
        out["teams"].append(t); out["checks"].append(chk)
    res = {k: (pd.concat(v, ignore_index=True) if v and k != "checks" else pd.DataFrame(v))
           for k, v in out.items()}
    res["skipped"] = skipped
    return res
