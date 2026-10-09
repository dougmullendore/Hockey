"""Line combinations: who plays with whom, worked out from the shift charts.

The league publishes every shift of every game: who went on the ice and when.
From that this module counts, second by second, which three forwards and
which two defensemen were out together at five-on-five, and which groups
were out on the power play and the penalty kill.

A team's lines are then read off its latest game: the three forwards who
spent the most time together are a line, then the next three among the
rest, and so on; defense pairs the same way. Lines are numbered by how much
their players play: their ice time a game this season in all situations. So
the first pair is the one on the ice most, even if its two also take shifts
with others. Power-play and penalty-kill units come from the last few games
(PP_GAMES), because one game has too little of either to go on.

With the play-by-play alongside, it also counts what happened while each
line and pair was out at five-on-five: shot attempts, expected goals and
goals, for and against. A shot counts for the five skaters on the ice in the
second before it (so a goal counts for the line that scored it, not the one
that came on for the faceoff).

Nobody tells this what the coach intends: it shows what he did. A line
broken up mid-game, an injury or a benching shows as it happened.
"""
from __future__ import annotations

from .nhl import seconds

VERSION = "lines-2"
KEEP_SECONDS = 20            # groups together for less than this in a game are not kept
SPECIAL_GAMES = 3            # power-play and penalty-kill units are taken from this many latest games
FORWARDS = ("C", "L", "R")
SHOWN_SECONDS = 600          # a line or pair is listed among the season's once it has this long together (10 minutes)
SHOWN_MOST = 15              # and at most this many are listed
ON_ICE = ["cf", "ca", "xgf", "xga", "gf", "ga"]     # what is counted while a line is out: attempts, expected goals, goals; for and against


def key_of(ids) -> str:
    return "-".join(str(p) for p in sorted(ids))


def parse_shifts(doc: dict) -> list[tuple]:
    """A game's shift chart as (team, player, period, start, end), in seconds of the period."""
    seen, out = set(), []
    for r in doc.get("data") or []:
        if r.get("typeCode") != 517 or not r.get("playerId") or not r.get("teamAbbrev"):
            continue
        try:
            period = int(r.get("period"))
        except (TypeError, ValueError):
            continue
        start, end = seconds(r.get("startTime")), seconds(r.get("endTime"))
        if end <= start:                 # some rows carry a duration but a blank or wrapped end time
            end = start + seconds(r.get("duration"))
        end = min(end, 1200)
        key = (r["teamAbbrev"], int(r["playerId"]), period, start, end)
        if not (1 <= period <= 12) or end <= start or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def count(shifts: list[tuple], pos: dict, shots: list[tuple] | None = None, home: str | None = None) -> dict:
    """{team: {"f": [[ids, seconds]], "d": [...], "pp": [...], "pk": [...], "ppt": {id: seconds}, "pkt": {...},
               "fs": {"id-id-id": [attempts for, against, expected goals for, against, goals for, against]}, "ds": {...}}}
    for one game. `pos` is {player id: position} for the skaters who played;
    goalies are left out, so a pulled goalie's extra skater shows as six.
    `shots` is xg.attempts() for the game and `home` the home team; without
    them nothing is counted for "fs" and "ds"."""
    ice = {}                             # (team, period) -> one set of skaters per second
    for team, pid, period, start, end in shifts:
        if pid not in pos:
            continue
        row = ice.setdefault((team, period), [set() for _ in range(1200)])
        for t in range(start, end):
            row[t].add(pid)
    teams = sorted({team for team, _ in ice})
    out = {t: {"f": {}, "d": {}, "pp": {}, "pk": {}, "ppt": {}, "pkt": {}} for t in teams}
    if len(teams) != 2:
        return {}
    for period in sorted({p for _, p in ice}):
        a, b = ice.get((teams[0], period)), ice.get((teams[1], period))
        if a is None or b is None:
            continue
        for t in range(1200):
            for team, mine, theirs in ((teams[0], a[t], b[t]), (teams[1], b[t], a[t])):
                n, m, o = len(mine), len(theirs), out[team]
                if n == 5 and m == 5:
                    fwd = frozenset(p for p in mine if pos[p] in FORWARDS)
                    if len(fwd) == 3:
                        o["f"][fwd] = o["f"].get(fwd, 0) + 1
                        dmen = frozenset(mine - fwd)
                        o["d"][dmen] = o["d"].get(dmen, 0) + 1
                elif n in (4, 5) and 3 <= m < n:
                    o["pp"][frozenset(mine)] = o["pp"].get(frozenset(mine), 0) + 1
                    for p in mine:
                        o["ppt"][p] = o["ppt"].get(p, 0) + 1
                elif n in (3, 4) and n < m <= 5:
                    o["pk"][frozenset(mine)] = o["pk"].get(frozenset(mine), 0) + 1
                    for p in mine:
                        o["pkt"][p] = o["pkt"].get(p, 0) + 1
    # what happened at five-on-five while each trio and pair was out
    seen = {t: {"f": {}, "d": {}} for t in teams}
    for period, secs, by_home, worth, goal in shots or []:
        if home not in teams:
            break
        shooting = home if by_home else teams[0] if teams[1] == home else teams[1]
        other = teams[0] if teams[1] == shooting else teams[1]
        a, b = ice.get((shooting, period)), ice.get((other, period))
        t = min(1199, max(0, secs - 1))
        if a is None or b is None or len(a[t]) != 5 or len(b[t]) != 5:
            continue
        for team, mine, first in ((shooting, a[t], 0), (other, b[t], 1)):
            fwd = frozenset(p for p in mine if pos[p] in FORWARDS)
            if len(fwd) != 3:
                continue
            for kind, group in (("f", fwd), ("d", frozenset(mine - fwd))):
                row = seen[team][kind].setdefault(group, [0, 0, 0.0, 0.0, 0, 0])
                row[first] += 1
                row[2 + first] += worth
                row[4 + first] += goal
    for team, o in out.items():
        for kind in ("f", "d"):
            o[kind + "s"] = {key_of(ids): row[:2] + [round(row[2], 3), round(row[3], 3)] + row[4:] for ids, row in seen[team][kind].items()
                             if o[kind].get(ids, 0) >= KEEP_SECONDS and any(row)}
    for o in out.values():
        for kind in ("f", "d", "pp", "pk"):
            o[kind] = sorted(([sorted(ids), secs] for ids, secs in o[kind].items() if secs >= KEEP_SECONDS), key=lambda x: (-x[1], x[0]))
        for kind in ("ppt", "pkt"):
            o[kind] = {str(p): s for p, s in o[kind].items()}
    return out


def _greedy(groups: list, size: int, want: int, pool: list[int], skip: set | None = None) -> list[list]:
    """Pick groups in order of time together, never using a player twice.
    Players left over (in `pool` order) fill up the last groups."""
    used, out = set(skip or ()), []
    for ids, secs in groups:
        if len(out) >= want:
            break
        if len(ids) == size and not used & set(ids):
            out.append([list(ids), secs])
            used |= set(ids)
    rest = [p for p in pool if p not in used]
    while rest and len(out) < want:
        out.append([rest[:size], 0])
        rest = rest[size:]
    return out


def _merge(games: list[dict], kind: str) -> list:
    total = {}
    for g in games:
        for ids, secs in g.get(kind) or []:
            total[tuple(ids)] = total.get(tuple(ids), 0) + secs
    return sorted(([list(k), v] for k, v in total.items()), key=lambda x: (-x[1], x[0]))


def _unit(games: list[dict], kind: str, times: str, size: int) -> list[list]:
    """Two special-teams units: the group out together most, then the best
    group that shares nobody with it (or, failing that, the next busiest players)."""
    busy = {}
    for g in games:
        for p, s in (g.get(times) or {}).items():
            busy[int(p)] = busy.get(int(p), 0) + s
    pool = sorted(busy, key=lambda p: (-busy[p], p))
    return [[ids, secs] for ids, secs in _greedy(_merge(games, kind), size, 2, pool) if len(ids) >= size - 1]


def arrange(ids: list[int], pos: dict, faceoffs: dict) -> list[int]:
    """A forward line left to right: left wing, center, right wing. With two
    centers on a line, the one who took more faceoffs is the center."""
    slots, left = {"L": None, "C": None, "R": None}, []
    for p in sorted(ids, key=lambda p: (-faceoffs.get(p, 0), p)):
        want = pos.get(p)
        if want in slots and slots[want] is None:
            slots[want] = p
        else:
            left.append(p)
    for key in ("C", "L", "R"):
        if slots[key] is None and left:
            slots[key] = left.pop(0)
    return [p for p in (slots["L"], slots["C"], slots["R"]) if p is not None]


def team_lines(latest: dict, recent: list[dict], season: list[dict], dressed: list[dict], others: dict | None = None) -> dict:
    """One team's lines. `latest` is its newest game's counts, `recent` its
    last few games' (newest first), `season` all of them; `dressed` is who
    played in the newest game: [{"id", "pos", "toi", "fo", "sh", "avg"}]
    ("avg" is his ice time a game this season); `others`
    is {id: {"pos", "sh"}} for anyone else who has played this season."""
    pos = {p["id"]: p["pos"] for p in dressed}
    faceoffs = {p["id"]: p.get("fo", 0) for p in dressed}
    hand = {p["id"]: p.get("sh") for p in dressed}
    for pid, who in (others or {}).items():
        pos.setdefault(pid, who.get("pos"))
        hand.setdefault(pid, who.get("sh"))
    by_time = sorted(dressed, key=lambda p: -p["toi"])
    fwd_pool = [p["id"] for p in by_time if p["pos"] in FORWARDS]
    def_pool = [p["id"] for p in by_time if p["pos"] == "D"]
    together, games, on_ice = {}, {}, {}
    for g in season:
        for kind in ("f", "d"):
            for ids, secs in g.get(kind) or []:
                key = tuple(ids)
                together[key] = together.get(key, 0) + secs
                games[key] = games.get(key, 0) + 1
            for name, row in (g.get(kind + "s") or {}).items():
                key = tuple(int(p) for p in name.split("-"))
                mine = on_ice.setdefault(key, [0, 0, 0.0, 0.0, 0, 0])
                for i, v in enumerate(row):
                    mine[i] += v

    def stats(key):
        row = on_ice.get(key) or [0, 0, 0.0, 0.0, 0, 0]
        return row[:2] + [round(row[2], 2), round(row[3], 2)] + row[4:]

    def with_season(rows):
        return [{"ids": ids, "toi": secs, "season": together.get(tuple(sorted(ids)), 0), "games": games.get(tuple(sorted(ids)), 0),
                 "on": stats(tuple(sorted(ids)))} for ids, secs in rows]

    def every(size, place):
        """The season's lines (or pairs) with the most time together."""
        rows = sorted(((k, v) for k, v in together.items() if len(k) == size and v >= SHOWN_SECONDS), key=lambda x: (-x[1], x[0]))
        return [{"ids": place(list(k)), "season": v, "games": games[k], "on": stats(k)} for k, v in rows[:SHOWN_MOST]]

    def left_first(ids):
        return sorted(ids, key=lambda p: (hand.get(p) != "L", ids.index(p))) if {hand.get(p) for p in ids} == {"L", "R"} else ids

    ice_time = {p["id"]: p.get("avg", p["toi"]) for p in dressed}

    def busiest_first(rows):
        """Number the lines by how much their players play: their ice time a
        game this season, all situations counted. The top pair is the one
        that is out there most, even when its two share their five-on-five
        time with others."""
        return sorted(rows, key=lambda r: -sum(ice_time.get(p, 0) for p in r[0]) / max(1, len(r[0])))

    forwards = busiest_first(_greedy(latest.get("f") or [], 3, (len(fwd_pool) + 2) // 3, fwd_pool))
    forwards = [[arrange(ids, pos, faceoffs), secs] for ids, secs in forwards]
    pairs = busiest_first(_greedy(latest.get("d") or [], 2, (len(def_pool) + 1) // 2, def_pool))
    # a left shot on the left when the two shoot different ways
    pairs = [[left_first(ids), secs] for ids, secs in pairs]
    return {"f": with_season(forwards), "d": with_season(pairs),
            "all": {"f": every(3, lambda ids: arrange(ids, pos, faceoffs)), "d": every(2, left_first)},
            "pp": [{"ids": ids, "toi": secs} for ids, secs in _unit(recent, "pp", "ppt", 5)],
            "pk": [{"ids": ids, "toi": secs} for ids, secs in _unit(recent, "pk", "pkt", 4)]}
