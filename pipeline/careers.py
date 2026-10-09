"""Career stats: every NHL season a player has had, and his totals.

Earlier seasons come from the player's own page in the league's feed, read
once and kept (they no longer change). This season's line is the site's own,
from the box scores, so it is as fresh as the rest of the card. The career
line is the two added together. Career playoff totals are the league's.
"""
from __future__ import annotations

from .nhl import _int, _text, seconds

# One row per season and team, in this order. Skaters:
SK_COLS = ["season", "team", "gp", "g", "a", "pts", "pm", "pim", "ppg", "ppp", "gwg", "sog", "toi"]     # toi: seconds a game
# Goalies:
G_COLS = ["season", "team", "gp", "gs", "w", "l", "otl", "sa", "ga", "so", "toi"]                       # toi: seconds in all


def _skater(r: dict, team: str) -> list:
    return [_int(r.get("season")) // 10000, team, _int(r.get("gamesPlayed")), _int(r.get("goals")), _int(r.get("assists")),
            _int(r.get("points")), _int(r.get("plusMinus")), _int(r.get("pim")), _int(r.get("powerPlayGoals")),
            _int(r.get("powerPlayPoints")), _int(r.get("gameWinningGoals")), _int(r.get("shots")), seconds(r.get("avgToi"))]


def _goalie(r: dict, team: str) -> list:
    return [_int(r.get("season")) // 10000, team, _int(r.get("gamesPlayed")), _int(r.get("gamesStarted")), _int(r.get("wins")),
            _int(r.get("losses")), _int(r.get("otLosses")), _int(r.get("shotsAgainst")), _int(r.get("goalsAgainst")),
            _int(r.get("shutouts")), seconds(r.get("timeOnIce"))]


def parse(doc: dict) -> dict:
    """What is kept from a player's page: his NHL regular seasons, his career
    playoff totals and where he was drafted."""
    goalie = (doc.get("position") or "") == "G"
    row = _goalie if goalie else _skater
    seasons = []
    for r in sorted(doc.get("seasonTotals") or [], key=lambda r: (_int(r.get("season")), _int(r.get("sequence")))):
        if r.get("leagueAbbrev") == "NHL" and r.get("gameTypeId") == 2:
            seasons.append(row(r, _text(r.get("teamCommonName")) or _text(r.get("teamName"))))
    out = {"g": int(goalie), "seasons": seasons}
    playoffs = (doc.get("careerTotals") or {}).get("playoffs") or {}
    if _int(playoffs.get("gamesPlayed")):
        out["playoffs"] = row({**playoffs, "season": 0}, "")[2:]
    draft = doc.get("draftDetails") or {}
    if draft.get("year"):
        out["draft"] = [_int(draft.get("year")), _int(draft.get("round")), _int(draft.get("overallPick")), draft.get("teamAbbrev") or ""]
    return out


def _total(rows: list[list], goalie: bool) -> list:
    """Add seasons up. A skater's ice time a game is averaged over his games."""
    if goalie:
        return ["", ""] + [sum(r[i] for r in rows) for i in range(2, len(G_COLS))]
    timed = sum(r[2] for r in rows if r[12])
    average = round(sum(r[12] * r[2] for r in rows) / timed) if timed else 0
    return ["", ""] + [sum(r[i] for r in rows) for i in range(2, 12)] + [average]


def build(stored: dict | None, player: dict, team_short: str, season: int) -> dict | None:
    """The career table for one card: earlier seasons from `stored`, this
    season from `player` (his row on the Players page), and the totals."""
    goalie = player["grp"] == "G"
    if stored is not None and bool(stored.get("g")) != goalie:
        stored = None
    tot, gp = player["tot"], player["gp"]
    if goalie:
        now = [season, team_short, gp, tot["gs"], tot["w"], tot["l"], tot["otl"], tot["sa"], tot["ga"], tot["so"], tot["toi"]]
    else:
        now = [season, team_short, gp, tot["g"], tot["a"], tot["pts"], tot["pm"], tot["pim"], tot["ppg"], tot["ppp"], tot["gwg"], tot["sog"],
               round(tot["toi"] / gp) if gp else 0]
    earlier = [r for r in (stored or {}).get("seasons") or [] if r[0] < season]
    rows = earlier + [now]
    out = {"seasons": rows, "total": _total(rows, goalie), "known": stored is not None}
    if stored and stored.get("playoffs"):
        out["playoffs"] = stored["playoffs"]
    if stored and stored.get("draft"):
        out["draft"] = stored["draft"]
    return out
