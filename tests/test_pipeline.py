"""End-to-end check on four real games stored in tests/fixtures."""
import glob
import gzip
import json
from pathlib import Path

try:  # pytest is optional; tests/run_local.py works without it
    import pytest
    module_fixture = pytest.fixture(scope="module")
except ImportError:  # pragma: no cover
    def module_fixture(fn):
        return fn

from pipeline import aggregate, config, features, onice, rapm, store, war, xg
from pipeline.parse import parse_game, parse_shifts

FIX = Path(__file__).parent / "fixtures"


def load_all():
    out = []
    for f in sorted(glob.glob(str(FIX / "pbp_*.json.gz"))):
        out.append(parse_game(json.load(gzip.open(f))))
    return out


@module_fixture
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    by_season = {}
    for g, e, r in load_all():
        s = by_season.setdefault(g[1], ([], [], []))
        s[0].append(g); s[1].extend(e); s[2].extend(r)
    shifts = parse_shifts(json.load(gzip.open(FIX / "shifts_2025020001.json.gz")), 2025020001)
    store.write(d, "shifts", 20252026, store.frame("shifts", shifts))
    for season, (g, e, r) in by_season.items():
        store.write(d, "games", season, store.frame("games", g))
        store.write(d, "events", season, store.frame("events", e))
        store.write(d, "rosters", season, store.frame("rosters", r))
    return d


def test_scores_match_goal_events():
    for g, e, _ in load_all():
        ev = store.frame("events", e)
        goals = ev[(ev["type"] == "goal") & (ev["period_type"] != "SO")]
        home, away = int((goals["is_home"] == 1).sum()), int((goals["is_home"] == 0).sum())
        if g[12] != "SO":
            assert (home, away) == (g[10], g[11])


def test_shots_point_at_the_net():
    for g, e, _ in load_all():
        ev = store.frame("events", e)
        sh = ev[ev["type"].isin(["goal", "shot-on-goal", "missed-shot"]) & (ev["zone"] == "O")]
        assert (sh["x_adj"] > 0).mean() > 0.97
        blk = ev[ev["type"] == "blocked-shot"]
        assert (blk["x_adj"] > 0).mean() > 0.9


def test_roundtrip(data_dir):
    for season in (20212022, 20242025, 20252026):
        a = store.read(data_dir, "events", season)
        store.write(data_dir, "events", season, a)
        assert a.equals(store.read(data_dir, "events", season))


def test_features_complete(data_dir):
    games = store.read(data_dir, "games", 20252026)
    shots = features.build_shots(store.read(data_dir, "events", 20252026), games)
    assert len(shots) > 150
    assert not shots[features.FEATURES].isna().any().any()
    assert shots["dist"].between(0, 200).all()
    assert set(features.strength(shots)) <= {"PS", "EN", "EA", "5v5", "PP", "SH", "EV"}


def test_model_and_tables(data_dir, monkeypatch):
    monkeypatch.setattr(config, "SEASONS", [20212022, 20242025, 20252026])
    monkeypatch.setattr(xg, "MIN_GAMES_PER_SEASON", 1)
    # two finished seasons to learn from, one season still in progress
    store.write_json(data_dir / "manifest.json", {
        "20212022": {"complete": True, "games": 1},
        "20242025": {"complete": True, "games": 1},
        "20252026": {"complete": False, "games": 2}})
    assert xg.train_seasons(data_dir) == [20212022, 20242025]
    monkeypatch.setitem(xg.PARAMS, "min_samples_leaf", 10)
    monkeypatch.setitem(xg.PARAMS, "max_iter", 30)
    res = xg.ensure_model(data_dir, print)
    assert res["trained"] and xg.load(data_dir) is not None
    assert len(xg.load(data_dir)["folds"]) == xg.N_FOLDS
    assert xg.ensure_model(data_dir, print)["trained"] is False

    aggregate.build_all(data_dir, print)
    out = data_dir / "site_data"
    meta = json.loads((out / "meta.json").read_text())
    assert [s["id"] for s in meta["seasons"]] == [20252026, 20242025, 20212022]

    games = store.read(data_dir, "games", 20252026)
    teams = json.loads((out / "teams_20252026_regular.json").read_text())
    assert sum(t["gf"] for t in teams) == sum(t["ga"] for t in teams)
    # NYR-MTL ended in OT (no shootout) so goal events equal the final score
    assert sum(t["gf"] for t in teams) == int((games["home_score"] + games["away_score"]).sum())
    assert sum(t["w"] for t in teams) == len(games)

    goalies = json.loads((out / "goalies_20252026_regular.json").read_text())
    assert all(g["name"] for g in goalies)
    assert all(g["sa"] >= g["ga"] and g["fa"] >= g["sa"] for g in goalies)
    assert all(abs(g["gsax"] - (g["xga"] - g["ga"])) < 0.11 for g in goalies)

    skaters = json.loads((out / "skaters_20252026_regular.json").read_text())
    assert sum(s["g"] for s in skaters) == sum(t["gf"] for t in teams)
    assert all(s["pos"] in ("F", "D") for s in skaters)

    # WAR is produced for the one season that has shift data
    table = json.loads((out / "war_20252026_regular.json").read_text())
    assert {r["pos"] for r in table} == {"F", "D", "G"}
    assert all(abs(r["war"]) < 3 for r in table)          # one game cannot be worth much
    assert not (out / "war_20212022_regular.json").exists()

    # every player in the WAR table gets a card with percentiles from 0 to 100
    deck = json.loads((out / "cards.json").read_text())
    assert len(deck["players"]) == len(table)
    for card in deck["players"].values():
        year = card["y"]["20252026"]
        n = len(deck["goalie_metrics"] if card["p"] == "G" else deck["skater_metrics"])
        assert len(year["p1"]) == len(year["p3"]) == len(year["v1"]) == n
        assert all(p is None or 0 <= p <= 100 for p in year["p1"] + year["p3"])

    recent = json.loads((out / "games_20252026_regular.json").read_text())
    assert len(recent) == len(games) and all(r["hxg"] > 0 and r["axg"] > 0 for r in recent)


def test_shifts_parse():
    rows = parse_shifts(json.load(gzip.open(FIX / "shifts_2025020001.json.gz")), 2025020001)
    df = store.frame("shifts", rows)
    assert len(df) > 600 and (df["end"] > df["start"]).all()
    # six players a side for sixty minutes is twelve player-hours, less penalties
    assert 11.5 < (df["end"] - df["start"]).sum() / 3600 <= 12.0


def test_on_ice(data_dir):
    season, gid = 20252026, 2025020001
    games = store.read(data_dir, "games", season)
    events = store.read(data_dir, "events", season)
    rosters = store.read(data_dir, "rosters", season)
    shifts = store.read(data_dir, "shifts", season)
    shots = features.build_shots(events, games)
    shots["xg"] = 0.07
    shots["strength"] = features.strength(shots)
    res = onice.build(games, events, rosters, shifts, shots)
    assert res["skipped"] == 1 and len(res["checks"]) == 1   # only one game has shifts
    chk = res["checks"].iloc[0]
    assert chk["skaters_on_for_goal"] == 10 and chk["odd_seconds"] == 0
    p, t = res["players"], res["teams"]
    assert p["toi5"].sum() == 10 * chk["five_seconds"]
    assert p["cf"].sum() == 5 * t["cf"].sum() and p["gf"].sum() == 5 * t["gf"].sum()
    # each team's forward lines cannot add up to more than the 5v5 clock
    lines = res["combos"].groupby(["team_id", "kind"])["toi5"].sum()
    assert (lines <= chk["five_seconds"]).all() and (lines > 0.9 * chk["five_seconds"]).all()

    names = aggregate._names(rosters[rosters["game_id"] == gid], games[games["game_id"] == gid])
    abbr = aggregate._abbrevs(games)
    table = aggregate.onice_table(res, {gid}, names)
    assert len(table) == 36 and all(r["name"] for r in table)
    combos = aggregate.combo_tables(res, {gid}, names, abbr)
    assert combos["lines"] and combos["pairs"] and all(" / " in r["name"] for r in combos["pairs"])
    w = aggregate.wowy_table(res, {gid}, names, abbr)
    a, b, team, toi = w["pairs"][0][:4]
    assert toi <= min(w["totals"][f"{a}|{team}"][0], w["totals"][f"{b}|{team}"][0])


def test_penalties_ignore_offsetting_minors():
    import pandas as pd
    ev = pd.DataFrame({
        "type": ["penalty"] * 5, "game_id": [1] * 5, "period": [1, 2, 2, 3, 3],
        "period_seconds": [100, 300, 300, 50, 60], "team_id": [10, 10, 20, 20, 10],
        "penalty_minutes": [2, 2, 2, 4, 5], "penalty_type": ["MIN", "MIN", "MIN", "MIN", "MAJ"],
        "player1_id": [1, 2, 3, 4, 5], "player2_id": [3, 3, 2, 1, 4],
    })
    taken, drawn, n = war.penalties(ev, {1})
    assert n == 3                       # one minor + one double minor; the matching pair cancels
    assert taken.to_dict() == {1: 1.0, 4: 2.0} and drawn.to_dict() == {3: 1.0, 1: 2.0}


def test_rapm_recovers_a_planted_effect():
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(3)
    n, players = 6000, np.arange(1, 41)
    lines = np.array([rng.choice(players, 10, replace=False) for _ in range(n)])
    dur = rng.integers(20, 60, n)
    # player 1 lifts his own team's chances by 2 per hour, home or away
    star_home, star_away = (lines[:, :5] == 1).any(axis=1), (lines[:, 5:] == 1).any(axis=1)
    hxg = rng.poisson((2.5 + 2.0 * star_home) * dur / 3600.0 * 20, n) / 20.0
    axg = rng.poisson((2.5 + 2.0 * star_away) * dur / 3600.0 * 20, n) / 20.0
    st = pd.DataFrame(np.column_stack([np.arange(n) % 50, np.zeros(n), dur, np.ones(n), lines]),
                      columns=onice.STINT_COLS[:14]).astype("int64")
    st["hxg"], st["axg"], st["hgoals"], st["agoals"], st["score"], st["fo"] = hxg, axg, 0.0, 0.0, 0, 9
    fit = rapm.fit(st, "ev", 1.0)
    off = dict(zip(fit["players"], fit["off"]))
    assert off[1] == max(off.values()) and 1.5 < off[1] < 2.5
    others = [v for k, v in off.items() if k != 1]
    assert max(abs(v) for v in others) < 0.5              # nobody else gets his credit


def test_card_percentiles_rank_within_position():
    from pipeline import cards
    blended = {i: {"toi": 3600.0 * 20, "war": float(i), "gp": 82} for i in range(1, 11)}
    blended[99] = {"toi": 3600.0, "war": 50.0, "gp": 4}            # too little ice time to rank
    pct = cards._percentiles(blended, [("war", "toi", 0.25)], True)
    assert pct[1][0] == [5] and pct[10][0] == [95] and pct[99][0] == [None]
    assert pct[10][1] == [10.0]
