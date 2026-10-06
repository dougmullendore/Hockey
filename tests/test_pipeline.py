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

from pipeline import aggregate, config, features, store, xg
from pipeline.parse import parse_game

FIX = Path(__file__).parent / "fixtures"


def load_all():
    out = []
    for f in sorted(glob.glob(str(FIX / "*.json.gz"))):
        out.append(parse_game(json.load(gzip.open(f))))
    return out


@module_fixture
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    by_season = {}
    for g, e, r in load_all():
        s = by_season.setdefault(g[1], ([], [], []))
        s[0].append(g); s[1].extend(e); s[2].extend(r)
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
    monkeypatch.setattr(config, "XG_TRAIN_SEASONS", [20212022, 20242025, 20252026])
    monkeypatch.setattr(xg, "MIN_GAMES_PER_SEASON", 1)
    monkeypatch.setitem(xg.PARAMS, "min_samples_leaf", 10)
    monkeypatch.setitem(xg.PARAMS, "max_iter", 30)
    res = xg.ensure_model(data_dir, print)
    assert res["trained"] and xg.load(data_dir) is not None
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

    recent = json.loads((out / "games_20252026_regular.json").read_text())
    assert len(recent) == len(games) and all(r["hxg"] > 0 and r["axg"] > 0 for r in recent)
