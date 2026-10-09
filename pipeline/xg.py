"""Expected goals: how likely each shot was to go in, from where and how it was taken.

The league's play-by-play gives every shot's place on the ice, its type and
what happened just before it. A model fitted on five seasons of shots
(2021-22 to 2025-26) turns that into a chance of scoring: a shot from the
slot might be worth 0.20 of a goal, one from the blue line 0.02. Add them up
and you have what a team, a player or a goalie "should" have scored or
allowed on the chances there were.

It counts unblocked shots: goals, saves and misses. Blocked shots are left
out because the feed records where the block happened, not where the shot
came from. Shootouts are left out. A penalty shot is worth a flat value, and
a shot at an empty net has its own, simpler estimate from distance.

The model is a set of small decision trees (150 of them, eight leaves each),
fitted once and stored in model/xg.json, so nothing needs installing to use
it. How it tested is in that file's "tested".
It sees where and how, not who: it does not know the shooter's skill, the
screen in front, or whether the goalie was set.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODEL_FILE = Path(__file__).resolve().parents[1] / "model" / "xg.json"
GOAL_X = 89.0
UNBLOCKED = ("goal", "shot-on-goal", "missed-shot")
ATTEMPTS = UNBLOCKED + ("blocked-shot",)
SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around"]
PREV_TYPES = ["faceoff", "hit", "giveaway", "takeaway", "shot-on-goal", "missed-shot", "blocked-shot", "goal"]
PENALTY_SHOT = 0.30          # the league converts roughly one in three
FEATURES = ["distance", "angle", "x", "y from the middle", "shot type", "what happened just before", "by the same team",
            "seconds since then", "where that was (x)", "where that was (y)", "how far the puck moved since", "angle change on a rebound",
            "rebound", "shooter's skaters", "defender's skaters"]

_PLAYERS = {"goal": ("scoringPlayerId", None), "shot-on-goal": ("shootingPlayerId", None), "missed-shot": ("shootingPlayerId", None),
            "blocked-shot": ("shootingPlayerId", "blockingPlayerId"), "faceoff": ("winningPlayerId", "losingPlayerId"),
            "hit": ("hittingPlayerId", "hitteePlayerId"), "giveaway": ("playerId", None), "takeaway": ("playerId", None)}

_model = None


def model() -> dict:
    global _model
    if _model is None:
        _model = json.loads(MODEL_FILE.read_text())
    return _model


def _clock(text) -> int | None:
    try:
        m, s = str(text).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def events(doc: dict) -> list[dict]:
    """A game's play-by-play as plain events, each seen from the acting team:
    x runs toward the net it is attacking."""
    home_id = (doc.get("homeTeam") or {}).get("id")
    team_of = {r.get("playerId"): r.get("teamId") for r in doc.get("rosterSpots") or []}
    out = []
    for p in sorted(doc.get("plays") or [], key=lambda p: p.get("sortOrder", 0)):
        d, per = p.get("details") or {}, p.get("periodDescriptor") or {}
        kind = p.get("typeDescKey")
        f1, f2 = _PLAYERS.get(kind, (None, None))
        p1, p2 = (d.get(f1) if f1 else None), (d.get(f2) if f2 else None)
        team = d.get("eventOwnerTeamId")
        if kind in ATTEMPTS and p1 in team_of:
            team = team_of[p1]           # the feed is not consistent about who "owns" a blocked shot
        home = None if team is None else int(team == home_id)
        x, y = d.get("xCoord"), d.get("yCoord")
        xa = ya = None
        if x is not None and y is not None and home is not None:
            home_attacks_right = p.get("homeTeamDefendingSide") != "right"
            flip = (home == 1) != home_attacks_right
            xa, ya = (-x, -y) if flip else (x, y)
        secs = _clock(p.get("timeInPeriod"))
        out.append({"type": kind, "period": per.get("number"), "ptype": per.get("periodType"), "secs": secs, "home": home,
                    "x": xa, "y": ya, "zone": d.get("zoneCode"), "p1": p1, "p2": p2, "goalie": d.get("goalieInNetId"),
                    "situation": str(p.get("situationCode") or ""), "shot_type": d.get("shotType")})
    # Which end the home team defends is occasionally wrong or missing in the
    # feed. Unblocked shots carry their own zone, so if most of a period's
    # offensive-zone shots end up behind the shooter, the period is mirrored.
    votes = {}
    for e in out:
        if e["type"] in UNBLOCKED and e["x"] is not None and e["zone"] in ("O", "D") and abs(e["x"]) >= 26:
            v = votes.setdefault(e["period"], [0, 0])
            v[0 if (e["x"] > 0) == (e["zone"] == "O") else 1] += 1
    wrong = {per for per, (good, bad) in votes.items() if bad > good}
    for e in out:
        if e["period"] in wrong and e["x"] is not None:
            e["x"], e["y"] = -e["x"], -e["y"]
    return out


def shots(evs: list[dict]) -> list[dict]:
    """Every unblocked shot of a game, with what the model needs to know about it."""
    out, prev, period = [], None, None
    for e in evs:
        if e["period"] != period:
            prev, period = None, e["period"]
        located = e["x"] is not None and e["home"] is not None
        if e["type"] in UNBLOCKED and e["ptype"] != "SO" and located:
            x, y, sit = float(e["x"]), float(e["y"]), e["situation"]
            away_goalie, away_sk, home_sk, home_goalie = (int(c) for c in sit) if len(sit) == 4 and sit.isdigit() else (1, 5, 5, 1)
            mine, theirs = (home_sk, away_sk) if e["home"] else (away_sk, home_sk)
            their_goalie = away_goalie if e["home"] else home_goalie
            s = {"home": e["home"], "shooter": e["p1"], "goalie": e["goalie"], "goal": int(e["type"] == "goal"),
                 "on_goal": int(e["type"] != "missed-shot"), "x": x, "y": y, "shot_type": e["shot_type"] or "",
                 "mine": mine, "theirs": theirs, "empty": int(their_goalie == 0 and not e["goalie"]),
                 "penalty_shot": int(sit in ("0101", "1010")), "period": e["period"], "secs": e["secs"],
                 "prev_type": None, "prev_same": 0, "since": 60.0, "prev_x": None, "prev_y": None}
            if prev is not None and e["secs"] is not None and prev["secs"] is not None:
                same = prev["home"] == e["home"]
                sign = 1.0 if same else -1.0
                s.update(prev_type=prev["type"], prev_same=int(same), since=float(min(60, max(0, e["secs"] - prev["secs"]))),
                         prev_x=sign * prev["x"], prev_y=sign * prev["y"])
            out.append(s)
        if located:
            prev = e
    return out


def features(s: dict) -> list[float]:
    """The numbers the model uses for one shot, in the order of FEATURES."""
    dx = GOAL_X - s["x"]
    dist = math.hypot(dx, s["y"])
    angle = math.degrees(math.atan2(abs(s["y"]), dx))        # 0 is straight in front; past 90 is from behind the goal line
    rebound = int(bool(s["prev_same"]) and s["prev_type"] in ("shot-on-goal", "missed-shot") and s["since"] <= 3)
    have = s["prev_x"] is not None
    turn = abs(math.degrees(math.atan2(s["y"], dx)) - math.degrees(math.atan2(s["prev_y"], GOAL_X - s["prev_x"]))) if have and rebound else 0.0
    return [dist, angle, s["x"], abs(s["y"]),
            float(SHOT_TYPES.index(s["shot_type"]) if s["shot_type"] in SHOT_TYPES else len(SHOT_TYPES)),
            float(PREV_TYPES.index(s["prev_type"]) if s["prev_type"] in PREV_TYPES else len(PREV_TYPES)),
            float(s["prev_same"]), s["since"],
            s["prev_x"] if have else -200.0, abs(s["prev_y"]) if have else -1.0,
            math.hypot(s["x"] - s["prev_x"], s["y"] - s["prev_y"]) if have else -1.0,
            turn, float(rebound), float(s["mine"]), float(s["theirs"])]


def _tree(nodes: list, x: list[float]) -> float:
    """Walk one small decision tree: a node is [value] at a leaf, or
    [feature, threshold, left, right] (go left when the feature is at most the threshold)."""
    n = nodes[0]
    while len(n) > 1:
        n = nodes[n[2] if x[n[0]] <= n[1] else n[3]]
    return n[0]


def chance(s: dict, m: dict | None = None) -> float:
    """The chance that this shot goes in."""
    m = m or model()
    if s["penalty_shot"]:
        return PENALTY_SHOT
    if s["empty"]:
        z = m["empty"][0] + m["empty"][1] * math.hypot(GOAL_X - s["x"], s["y"]) / 10.0
    else:
        x = features(s)
        z = m["base"] + sum(_tree(t, x) for t in m["trees"])
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def summarize(doc: dict) -> dict:
    """What the rest of the job keeps from one game's play-by-play:
      xg      expected goals for [away, home]
      sk      {skater: [shot attempts, unblocked attempts, expected goals, faceoffs won, faceoffs taken]}
      g       {goalie: [expected goals against, goals against]} on shots with him in net
    Shootouts are left out of everything."""
    evs = events(doc)
    out = {"v": model()["version"], "xg": [0.0, 0.0], "sk": {}, "g": {}}

    def skater(pid):
        return out["sk"].setdefault(str(pid), [0, 0, 0.0, 0, 0])

    for e in evs:
        if e["ptype"] == "SO":
            continue
        if e["type"] in ATTEMPTS and e["p1"]:
            skater(e["p1"])[0] += 1
        elif e["type"] == "faceoff" and e["p1"] and e["p2"]:
            skater(e["p1"])[3] += 1
            skater(e["p1"])[4] += 1
            skater(e["p2"])[4] += 1
    for s in shots(evs):
        p = chance(s)
        out["xg"][s["home"]] += p
        if s["shooter"]:
            row = skater(s["shooter"])
            row[1] += 1
            row[2] += p
        if s["goalie"] and not s["empty"] and not s["penalty_shot"]:
            g = out["g"].setdefault(str(s["goalie"]), [0.0, 0])
            g[0] += p
            g[1] += s["goal"]
    out["xg"] = [round(v, 3) for v in out["xg"]]
    for row in out["sk"].values():
        row[2] = round(row[2], 3)
    for row in out["g"].values():
        row[0] = round(row[0], 3)
    return out
