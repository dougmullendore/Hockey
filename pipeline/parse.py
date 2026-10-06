"""Turn one raw NHL play-by-play file into tidy rows.

Every game becomes:
  * one `game` row (who played, final score, how it ended)
  * many `event` rows (every faceoff, hit, shot, goal, penalty ...)
  * forty-ish `roster` rows (who dressed)
"""
from __future__ import annotations

import re

GAME_COLS = [
    "game_id", "season", "game_type", "date", "start_utc", "state",
    "home_id", "home_abbrev", "away_id", "away_abbrev",
    "home_score", "away_score", "last_period_type", "periods",
]

EVENT_COLS = [
    "game_id", "idx", "event_id", "period", "period_type", "period_seconds",
    "game_seconds", "type", "team_id", "is_home", "x", "y", "x_adj", "y_adj",
    "zone", "shot_type", "reason", "player1_id", "player2_id", "player3_id",
    "goalie_id", "situation", "home_skaters", "away_skaters",
    "home_goalie_in", "away_goalie_in", "home_score", "away_score",
    "penalty_type", "penalty_minutes", "desc_key",
]

ROSTER_COLS = [
    "game_id", "team_id", "player_id", "first_name", "last_name",
    "position", "sweater",
]

SHIFT_COLS = ["game_id", "team_id", "player_id", "period", "start", "end"]

SHOT_TYPES = ("goal", "shot-on-goal", "missed-shot", "blocked-shot")

# Which fields of an event hold the "main" player and the supporting ones.
_PLAYER_FIELDS = {
    "goal": ("scoringPlayerId", "assist1PlayerId", "assist2PlayerId"),
    "shot-on-goal": ("shootingPlayerId", None, None),
    "missed-shot": ("shootingPlayerId", None, None),
    "blocked-shot": ("shootingPlayerId", "blockingPlayerId", None),
    "faceoff": ("winningPlayerId", "losingPlayerId", None),
    "hit": ("hittingPlayerId", "hitteePlayerId", None),
    "giveaway": ("playerId", None, None),
    "takeaway": ("playerId", None, None),
    "penalty": ("committedByPlayerId", "drawnByPlayerId", "servedByPlayerId"),
}


def _clock(text) -> int | None:
    """'12:34' -> 754 seconds."""
    try:
        m, s = str(text).split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return None


def _situation(code):
    """'1541' -> (away_goalie_in, away_skaters, home_skaters, home_goalie_in)."""
    if not code or len(str(code)) != 4 or not str(code).isdigit():
        return None, None, None, None
    c = str(code)
    return int(c[0]), int(c[1]), int(c[2]), int(c[3])


def is_final(state: str | None) -> bool:
    return state in ("OFF", "FINAL")


def parse_game(raw: dict):
    """Returns (game_row, event_rows, roster_rows) as plain tuples."""
    game_id = raw["id"]
    home, away = raw["homeTeam"], raw["awayTeam"]
    home_id, away_id = home["id"], away["id"]

    roster_rows, player_team = [], {}
    for r in raw.get("rosterSpots", []):
        player_team[r["playerId"]] = r["teamId"]
        roster_rows.append((
            game_id, r["teamId"], r["playerId"],
            (r.get("firstName") or {}).get("default"),
            (r.get("lastName") or {}).get("default"),
            r.get("positionCode"), r.get("sweaterNumber"),
        ))

    plays = sorted(raw.get("plays", []), key=lambda p: p.get("sortOrder", 0))
    rows = []
    h_score = a_score = 0
    max_period = 0
    for p in plays:
        pd_ = p.get("periodDescriptor") or {}
        period = pd_.get("number")
        ptype = pd_.get("periodType")
        max_period = max(max_period, period or 0)
        psecs = _clock(p.get("timeInPeriod"))
        gsecs = None
        if period is not None and psecs is not None:
            gsecs = (period - 1) * 1200 + psecs
        typ = p.get("typeDescKey")
        d = p.get("details") or {}

        f1, f2, f3 = _PLAYER_FIELDS.get(typ, (None, None, None))
        p1 = d.get(f1) if f1 else None
        p2 = d.get(f2) if f2 else None
        p3 = d.get(f3) if f3 else None

        # The acting team. The feed has not always been consistent about who
        # "owns" a blocked shot, so trust the shooter's roster entry first.
        team_id = d.get("eventOwnerTeamId")
        if typ in SHOT_TYPES and p1 in player_team:
            team_id = player_team[p1]
        is_home = None if team_id is None else int(team_id == home_id)

        x, y = d.get("xCoord"), d.get("yCoord")
        x_adj = y_adj = None
        if x is not None and y is not None and is_home is not None:
            # Flip so the acting team always attacks toward +x.
            side = p.get("homeTeamDefendingSide")
            home_attacks_pos = side != "right"  # 'left' or unknown
            flip = (is_home == 1) != home_attacks_pos
            x_adj, y_adj = (-x, -y) if flip else (x, y)

        ag, ask, hsk, hg = _situation(p.get("situationCode"))

        rows.append([
            game_id, p.get("sortOrder"), p.get("eventId"), period, ptype, psecs,
            gsecs, typ, team_id, is_home, x, y, x_adj, y_adj,
            d.get("zoneCode"), d.get("shotType"), d.get("reason"), p1, p2, p3,
            d.get("goalieInNetId"), p.get("situationCode"), hsk, ask, hg, ag,
            h_score, a_score,  # score BEFORE this event
            d.get("typeCode") if typ == "penalty" else None,
            d.get("duration") if typ == "penalty" else None,
            d.get("descKey"),
        ])

        if typ == "goal" and ptype != "SO":
            if is_home == 1:
                h_score += 1
            elif is_home == 0:
                a_score += 1

    _fix_orientation(rows)

    outcome = raw.get("gameOutcome") or {}
    game_row = (
        game_id, raw.get("season"), raw.get("gameType"), raw.get("gameDate"),
        raw.get("startTimeUTC"), raw.get("gameState"),
        home_id, home.get("abbrev"), away_id, away.get("abbrev"),
        home.get("score"), away.get("score"),
        outcome.get("lastPeriodType") or (raw.get("periodDescriptor") or {}).get("periodType"),
        max_period,
    )
    return game_row, [tuple(r) for r in rows], roster_rows


# column positions used by the orientation check
_I = {c: i for i, c in enumerate(EVENT_COLS)}


def _fix_orientation(rows):
    """Sanity-check which way each team is shooting, period by period.

    The feed says which end the home team defends, but that flag is
    occasionally wrong or missing. Unblocked shots carry their own zone
    ('O' = offensive), so if most of a period's offensive-zone shots end up
    with a negative x, the whole period is mirrored."""
    votes = {}
    for r in rows:
        if r[_I["type"]] in ("goal", "shot-on-goal", "missed-shot") and r[_I["x_adj"]] is not None:
            zone = r[_I["zone"]]
            xa = r[_I["x_adj"]]
            if zone not in ("O", "D") or abs(xa) < 26:
                continue
            good = (xa > 0) == (zone == "O")
            v = votes.setdefault(r[_I["period"]], [0, 0])
            v[0 if good else 1] += 1
    bad_periods = {p for p, (good, bad) in votes.items() if bad > good}
    if not bad_periods:
        return
    for r in rows:
        if r[_I["period"]] in bad_periods and r[_I["x_adj"]] is not None:
            r[_I["x_adj"]] = -r[_I["x_adj"]]
            r[_I["y_adj"]] = -r[_I["y_adj"]]


def parse_shifts(raw: dict, game_id: int) -> list[tuple]:
    """Shift chart rows -> (game, team, player, period, start, end) in seconds.

    Each row says one player was on the ice from `start` to `end` of a
    period. Goal markers and broken rows are dropped, and exact duplicates
    (the feed repeats some shifts) are removed."""
    seen, out = set(), []
    for r in raw.get("data", []) or []:
        if r.get("typeCode") != 517 or r.get("playerId") is None or r.get("teamId") is None:
            continue
        period, start, end = r.get("period"), _clock(r.get("startTime")), _clock(r.get("endTime"))
        if period is None or start is None or end is None:
            continue
        if end <= start:
            # some rows carry a duration but a blank or wrapped end time
            dur = _clock(r.get("duration"))
            if not dur:
                continue
            end = start + dur
        end = min(end, 1200)
        if not (1 <= int(period) <= 12) or end <= start:
            continue
        key = (r["teamId"], r["playerId"], int(period), start, end)
        if key in seen:
            continue
        seen.add(key)
        out.append((game_id, *key))
    return out


_REPORT_PLAYER = re.compile(r'class="playerHeading[^"]*"[^>]*>\s*(\d+)\s+([^<]*)<')
_REPORT_ROW = re.compile(
    r"<td[^>]*>\s*\d+\s*</td>\s*"                      # shift number
    r"<td[^>]*>\s*(\d+|OT)\s*</td>\s*"                 # period
    r"<td[^>]*>\s*(\d+:\d+)\s*/[^<]*</td>\s*"          # start (elapsed)
    r"<td[^>]*>\s*(\d+:\d+)\s*/[^<]*</td>", re.I)      # end (elapsed)


def parse_shift_report(html: str, game_id: int, team_id: int, by_sweater: dict) -> list[tuple]:
    """Read one team's shifts from the league's printable ice-time report.

    This is the fallback for games whose shift chart feed is empty. The
    report lists players by sweater number, so `by_sweater` maps the number
    to a player id for this team in this game."""
    out, seen = [], set()
    heads = list(_REPORT_PLAYER.finditer(html))
    for i, h in enumerate(heads):
        pid = by_sweater.get(int(h.group(1)))
        if pid is None:
            continue
        block = html[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        for per, a, b in _REPORT_ROW.findall(block):
            period = 4 if per.upper() == "OT" else int(per)
            start, end = _clock(a), _clock(b)
            if start is None or end is None:
                continue
            end = min(end, 1200)
            if end <= start or not (1 <= period <= 12):
                continue
            key = (team_id, pid, period, start, end)
            if key not in seen:
                seen.add(key)
                out.append((game_id, *key))
    return out
