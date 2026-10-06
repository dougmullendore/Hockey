"""Isolating one player's impact from everyone else on the ice.

A skater's raw on-ice numbers depend on his linemates, his opponents, the
score and where his shifts start. Here every stint (a stretch with the same
ten skaters on the ice) becomes one line of a big regression: "this many
expected goals per hour happened with these five attacking and those five
defending". Solving it for all players at once gives each skater an offensive
and a defensive rating with everybody else's contribution taken out.

The method is called RAPM (regularized adjusted plus-minus). "Regularized"
means every rating is pulled toward zero unless there is plenty of evidence,
which keeps small samples from producing wild numbers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse

from . import onice

N_FOLDS = 5
H = ["h1", "h2", "h3", "h4", "h5"]
A = ["a1", "a2", "a3", "a4", "a5"]
SCORES = [-3, -2, -1, 1, 2, 3]


def _design(off: np.ndarray, deff: np.ndarray, controls: np.ndarray, players: np.ndarray):
    """Sparse matrix: attacker columns, defender columns, then the controls."""
    P, n = len(players), len(off)
    lookup = {p: i for i, p in enumerate(players)}
    get = np.vectorize(lambda p: lookup.get(p, -1), otypes=[np.int64])
    oi, di = get(off), get(deff)
    rows = np.repeat(np.arange(n), off.shape[1])
    r = np.concatenate([rows[(oi >= 0).ravel()], rows[(di >= 0).ravel()]])
    c = np.concatenate([oi.ravel()[oi.ravel() >= 0], P + di.ravel()[di.ravel() >= 0]])
    X = sparse.csr_matrix((np.ones(len(r)), (r, c)), shape=(n, 2 * P))
    return sparse.hstack([X, sparse.csr_matrix(controls)], format="csr")


def _rows_ev(st: pd.DataFrame):
    """Two lines per five-on-five stint: home attacking, then away attacking."""
    st = st[st["state"] == onice.EV]
    h, a = st[H].to_numpy("int64"), st[A].to_numpy("int64")
    off, deff = np.vstack([h, a]), np.vstack([a, h])
    xg = np.concatenate([st["hxg"].to_numpy(float), st["axg"].to_numpy(float)])
    hours = np.tile(st["dur"].to_numpy(float) / 3600.0, 2)
    game = np.tile(st["game_id"].to_numpy("int64"), 2)
    n = len(st)
    home = np.r_[np.ones(n), np.zeros(n)]
    score = np.clip(np.r_[st["score"].to_numpy(), -st["score"].to_numpy()], -3, 3)
    fo_home = st["fo"].to_numpy()
    fo = np.r_[fo_home, np.where(fo_home == 9, 9, -fo_home)]
    controls = np.column_stack(
        [np.ones(2 * n), home] + [(score == s).astype(float) for s in SCORES]
        + [(fo == z).astype(float) for z in (1, 0, -1)])
    names = ["intercept", "home"] + [f"score{s:+d}" for s in SCORES] + ["fo_off", "fo_neutral", "fo_def"]
    return off, deff, xg, hours, game, controls, names


def _rows_pp(st: pd.DataFrame):
    """One line per power-play stint: the team with the extra man attacking."""
    st = st[st["state"].isin([onice.HOME_PP, onice.AWAY_PP])]
    hp = (st["state"] == onice.HOME_PP).to_numpy()
    h, a = st[H].to_numpy("int64"), st[A].to_numpy("int64")
    off = np.where(hp[:, None], h, a)
    deff = np.where(hp[:, None], a, h)
    xg = np.where(hp, st["hxg"], st["axg"]).astype(float)
    hours = st["dur"].to_numpy(float) / 3600.0
    n_off, n_def = (off > 0).sum(1), (deff > 0).sum(1)
    fo_home = st["fo"].to_numpy()
    fo = np.where(fo_home == 9, 9, np.where(hp, fo_home, -fo_home))
    controls = np.column_stack([
        np.ones(len(st)), hp.astype(float), (n_def == 3).astype(float),
        ((n_off == 4) & (n_def == 3)).astype(float),
        (fo == 1).astype(float), (fo == -1).astype(float)])
    names = ["intercept", "home", "two_man_advantage", "four_on_three", "fo_off", "fo_def"]
    return off, deff, xg, hours, st["game_id"].to_numpy("int64"), controls, names


def _group_counts(ids: np.ndarray, group_of: dict, n_groups: int) -> np.ndarray:
    """For each line, how many of the listed skaters fall in each role group."""
    get = np.vectorize(lambda p: group_of.get(p, -1), otypes=[np.int64])
    g = get(ids)
    out = np.zeros((len(ids), n_groups))
    for k in range(n_groups):
        out[:, k] = (g == k).sum(axis=1)
    return out


def fit(st: pd.DataFrame, kind: str, lam: float, cv: bool = False,
        prior: dict | None = None, roles: tuple | None = None) -> dict:
    """Solve for every skater's attacking and defending rating.

    kind is "ev" (five-on-five) or "pp" (power play attack / penalty kill).
    `lam` is the pull toward zero, in hours of ice time: a skater's rating is
    roughly his raw effect times hours / (hours + lam).
    `prior` maps a player id to (attack, defence) ratings to pull toward
    instead of zero, normally a faded copy of last season's ratings.
    `roles` is (attack_role_of, defence_role_of, labels_attack, labels_defence):
    each skater's role on his team (first line, third pair ...). The model
    then estimates what a typical skater in each role is worth, and each
    individual rating is pulled toward his role's level rather than toward
    the league average. Without this, little-used players would all look
    average simply because there is not enough evidence about them.
    Returns ratings in expected goals per 60 minutes, centred on the
    ice-time-weighted league average."""
    off, deff, xg, hours, game, controls, names = (_rows_ev if kind == "ev" else _rows_pp)(st)
    ids = np.unique(np.concatenate([off.ravel(), deff.ravel()]))
    players = ids[ids > 0]
    P = len(players)
    if P == 0 or hours.sum() <= 0:
        return {"players": players, "off": np.zeros(0), "def": np.zeros(0),
                "off_hours": np.zeros(0), "def_hours": np.zeros(0), "controls": {}}
    n_role = 0
    if roles:
        role_off, role_def, lab_off, lab_def = roles
        extra = np.column_stack([_group_counts(off, role_off, len(lab_off)),
                                 _group_counts(deff, role_def, len(lab_def))])
        n_role = extra.shape[1]
        controls = np.column_stack([extra, controls])
        names = [f"off:{x}" for x in lab_off] + [f"def:{x}" for x in lab_def] + names
    X = _design(off, deff, controls, players)
    k = X.shape[1]
    y = np.divide(xg * 60.0, hours * 60.0, out=np.zeros_like(xg), where=hours > 0)  # xG per 60
    W = sparse.diags(hours)
    # role levels get a light pull (they share one degree of freedom with the
    # intercept); the remaining controls are left free
    penalty = np.r_[np.ones(2 * P), np.full(n_role, 0.02), np.full(k - 2 * P - n_role, 1e-6)]

    mu = np.zeros(k)
    if prior:
        for i, pl in enumerate(players):
            if int(pl) in prior:
                mu[i], mu[P + i] = prior[int(pl)]

    def solve(Amat, b):
        lhs, rhs = Amat + lam * np.diag(penalty), b + lam * penalty * mu
        try:
            return np.linalg.solve(lhs, rhs)
        except np.linalg.LinAlgError:      # e.g. a control that never varies in a tiny sample
            return np.linalg.lstsq(lhs, rhs, rcond=None)[0]

    XtW = (X.T @ W).tocsr()
    Amat = (XtW @ X).toarray()
    b = XtW @ y
    beta = solve(Amat, b)

    out = {"players": players, "controls": dict(zip(names, np.round(beta[2 * P:], 4)))}
    oh = np.asarray(X[:, :P].T @ hours).ravel()
    dh = np.asarray(X[:, P:2 * P].T @ hours).ravel()
    o, d = beta[:P].copy(), beta[P:2 * P].copy()
    out["off_dev"], out["def_dev"] = o.copy(), d.copy()      # each skater relative to his role
    if roles:
        n_off = len(lab_off)
        lvl_off, lvl_def = beta[2 * P: 2 * P + n_off], beta[2 * P + n_off: 2 * P + n_role]
        o += np.array([lvl_off[role_off[int(pl)]] if int(pl) in role_off else 0.0 for pl in players])
        d += np.array([lvl_def[role_def[int(pl)]] if int(pl) in role_def else 0.0 for pl in players])
    # centre on the league average so "0" means an average skater
    out["off"] = o - np.average(o, weights=oh) if oh.sum() else o
    out["def"] = d - np.average(d, weights=dh) if dh.sum() else d
    out["off_hours"], out["def_hours"] = oh, dh

    if cv:  # how well do ratings fitted on four fifths of the games predict the rest?
        fold = game % N_FOLDS
        yWy = float((hours * y * y).sum())
        err = 0.0
        for f in range(N_FOLDS):
            m = fold == f
            Xf, hf, yf = X[m], hours[m], y[m]
            XtWf = (Xf.T @ sparse.diags(hf)).tocsr()
            Af, bf = (XtWf @ Xf).toarray(), XtWf @ yf
            bt = solve(Amat - Af, b - bf)
            err += float((hf * yf * yf).sum()) - 2 * float(bt @ bf) + float(bt @ Af @ bt)
        out["cv_error"] = err / hours.sum()
        out["null_error"] = yWy / hours.sum() - (float((hours * y).sum()) / hours.sum()) ** 2
    return out
