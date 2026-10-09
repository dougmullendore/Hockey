"""Reading the NHL's public feed: the schedule, the standings, box scores and rosters.

Every `parse_` function turns one document from the feed into the small,
plain form the rest of the job uses, and can be tested on a saved copy.
"""
from __future__ import annotations

import datetime as dt

from . import config, web

FINAL_STATES = ("FINAL", "OFF")
LIVE_STATES = ("LIVE", "CRIT")
NOT_PLAYED = {"PPD": "Postponed", "CNCL": "Canceled", "SUSP": "Suspended"}

# One stored row per skater per game, and one per goalie, in this order.
SK = ["id", "num", "name", "pos", "g", "a", "pm", "pim", "hits", "ppg", "sog", "toi", "blk", "shifts", "gv", "tk",
      "fo", "a1", "pt", "pd"]
GK = ["id", "num", "name", "sa", "sv", "ga", "toi", "start", "dec", "es_sa", "es_sv", "pp_sa", "pp_sv", "sh_sa",
      "sh_sv", "pim"]


def _text(v) -> str:
    """The feed gives names as {"default": "Stars", "fr": ...}."""
    if isinstance(v, dict):
        v = v.get("default")
    return (v or "").strip()


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def seconds(clock) -> int:
    """"19:52" -> 1192."""
    try:
        m, s = str(clock).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return 0


def _pair(v) -> tuple[int, int]:
    """"25/26" -> (25, 26)."""
    try:
        a, b = str(v).split("/")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return 0, 0


# ------------------------------------------------------------ the schedule --
def season_for(day: dt.date) -> int:
    """A season is named by the year it starts in: 2026 is 2026-27."""
    return day.year if (day.month, day.day) >= config.SEASON_FLIP else day.year - 1


def season_weeks(season: int) -> list[str]:
    """One date in each week of the season; the feed answers with that whole week."""
    d, end = dt.date(season, *config.SEASON_WEEKS_FROM), dt.date(season + 1, *config.SEASON_WEEKS_TO)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += dt.timedelta(days=7)
    return out


def watch(broadcasts: list) -> list[str]:
    """The channels to show for a game: national ones first, then the two
    teams' own, the United States before Canada."""
    order = []
    for country in config.WATCH_COUNTRIES:
        for market in ("N", "H", "A"):
            for b in broadcasts or []:
                name = (b.get("network") or "").strip()
                if b.get("countryCode") == country and b.get("market") == market and name and name not in order:
                    order.append(name)
    return order[:config.WATCH_MAX]


def parse_game(g: dict, date: str) -> dict | None:
    """One game from a week of the schedule, or None if it is not listed on the site."""
    away, home = g.get("awayTeam") or {}, g.get("homeTeam") or {}
    if g.get("gameType") not in config.GAME_TYPES or not g.get("id") or not away.get("abbrev") or not home.get("abbrev"):
        return None
    feed, sched = g.get("gameState") or "", g.get("gameScheduleState") or "OK"
    if feed in FINAL_STATES:
        state = "final"
    elif sched in NOT_PLAYED:
        state = "other"
    elif feed in LIVE_STATES:
        state = "live"
    else:
        state = "upcoming"
    start = None
    if g.get("startTimeUTC") and sched != "TBD":
        try:
            start = int(dt.datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")).timestamp())
        except ValueError:
            start = None

    def side(t):
        return {"id": t["abbrev"], "name": _text(t.get("commonName")) or _text(t.get("name")) or t["abbrev"],
                "score": _int(t.get("score"), None) if state in ("final", "live") else None}

    series = g.get("seriesStatus") or {}
    round_ = ""
    if g.get("gameType") == 3:
        round_ = _text(series.get("seriesTitle")) or "Playoffs"
        if series.get("gameNumberOfSeries"):
            round_ += f", Game {series['gameNumberOfSeries']}"
    period = g.get("periodDescriptor") or {}
    out = {"id": int(g["id"]), "date": date, "start": start, "type": g["gameType"], "state": state,
           "note": NOT_PLAYED.get(sched, "") if state == "other" else "", "round": round_,
           "away": side(away), "home": side(home), "tv": watch(g.get("tvBroadcasts"))}
    if g.get("neutralSite"):
        out["neutral"] = True
    if state == "final":
        out["end"] = (g.get("gameOutcome") or {}).get("lastPeriodType") or period.get("periodType") or "REG"
    if state == "live":
        out["period"] = [_int(period.get("number")), period.get("periodType") or "REG"]
    return out


def parse_week(doc: dict) -> list[dict]:
    out = []
    for day in doc.get("gameWeek") or []:
        for g in day.get("games") or []:
            game = parse_game(g, day.get("date") or "")
            if game and game["date"]:
                out.append(game)
    return out


def fetch_schedule(dates: list[str]):
    """Yields (date, games_or_None, error_or_None) for each week asked for."""
    for path, doc, err in web.get_many([f"schedule/{d}" for d in dates]):
        date = path.split("/")[1]
        yield (date, None, err) if err is not None else (date, parse_week(doc), None)


# ----------------------------------------------------------- the standings --
def parse_standings(doc: dict) -> list[dict]:
    """Every team, in league order, as the league itself ranks them (its tie-breaks included)."""
    out = []
    for t in doc.get("standings") or []:
        abbr = _text(t.get("teamAbbrev"))
        if not abbr:
            continue

        def rec(prefix):
            return f"{_int(t.get(prefix + 'Wins'))}-{_int(t.get(prefix + 'Losses'))}-{_int(t.get(prefix + 'OtLosses'))}"

        streak = (t.get("streakCode") or "") + (str(t["streakCount"]) if t.get("streakCount") else "")
        out.append({
            "id": abbr, "name": _text(t.get("teamName")) or abbr, "short": _text(t.get("teamCommonName")) or abbr,
            "place": _text(t.get("placeName")), "conf": _text(t.get("conferenceName")), "div": _text(t.get("divisionName")),
            "rank": _int(t.get("leagueSequence")), "conf_rank": _int(t.get("conferenceSequence")),
            "div_rank": _int(t.get("divisionSequence")), "wc": _int(t.get("wildcardSequence")),
            "clinch": t.get("clinchIndicator") or "",
            "gp": _int(t.get("gamesPlayed")), "w": _int(t.get("wins")), "l": _int(t.get("losses")), "otl": _int(t.get("otLosses")),
            "pts": _int(t.get("points")), "pct": round(float(t.get("pointPctg") or 0), 3),
            "rw": _int(t.get("regulationWins")), "row": _int(t.get("regulationPlusOtWins")),
            "gf": _int(t.get("goalFor")), "ga": _int(t.get("goalAgainst")), "diff": _int(t.get("goalDifferential")),
            "home": rec("home"), "away": rec("road"), "l10": rec("l10"), "streak": streak})
    out.sort(key=lambda t: (t["rank"] or 99, -t["pts"], t["name"]))
    for i, t in enumerate(out):
        t["rank"] = i + 1            # 1 to 32 with no gaps, whatever the feed sent
    return out


def fetch_standings() -> list[dict]:
    return parse_standings(web.get_json("standings/now"))


# -------------------------------------------------------------- box scores --
def parse_box(box: dict, landing: dict | None, rail: dict | None) -> dict:
    """One game's stored record: every player's line, the score by period, the
    goals, the three stars and each team's totals."""
    feed = box.get("gameState") or ""
    out = {"date": box.get("gameDate") or "", "status": "F" if feed in FINAL_STATES else "L" if feed in LIVE_STATES else "P",
           "full": landing is not None and rail is not None}
    by_number = {"away": {}, "home": {}}
    abbr = {"away": (box.get("awayTeam") or {}).get("abbrev"), "home": (box.get("homeTeam") or {}).get("abbrev")}
    stats = box.get("playerByGameStats") or {}
    for side in ("away", "home"):
        team = stats.get(side + "Team") or {}
        skaters, goalies = [], []
        for p in (team.get("forwards") or []) + (team.get("defense") or []):
            toi = seconds(p.get("toi"))
            if not p.get("playerId") or toi <= 0:
                continue
            row = dict.fromkeys(SK, 0)
            row.update(id=int(p["playerId"]), num=_int(p.get("sweaterNumber"), None), name=_text(p.get("name")),
                       pos=p.get("position") or "", g=_int(p.get("goals")), a=_int(p.get("assists")),
                       pm=_int(p.get("plusMinus")), pim=_int(p.get("pim")), hits=_int(p.get("hits")),
                       ppg=_int(p.get("powerPlayGoals")), sog=_int(p.get("sog")), toi=toi,
                       blk=_int(p.get("blockedShots")), shifts=_int(p.get("shifts")), gv=_int(p.get("giveaways")),
                       tk=_int(p.get("takeaways")), fo=round(100 * float(p.get("faceoffWinningPctg") or 0)))
            skaters.append(row)
            if row["num"] is not None:
                by_number[side][row["num"]] = row
        for p in team.get("goalies") or []:
            toi = seconds(p.get("toi"))
            if not p.get("playerId") or toi <= 0:
                continue
            es, pp, sh = _pair(p.get("evenStrengthShotsAgainst")), _pair(p.get("powerPlayShotsAgainst")), _pair(p.get("shorthandedShotsAgainst"))
            sv, sa = _pair(p.get("saveShotsAgainst"))
            if p.get("shotsAgainst") is not None:
                sa = _int(p.get("shotsAgainst"))
            if p.get("saves") is not None:
                sv = _int(p.get("saves"))
            goalies.append([int(p["playerId"]), _int(p.get("sweaterNumber"), None), _text(p.get("name")), sa, sv,
                            _int(p.get("goalsAgainst")), toi, 1 if p.get("starter") else 0, p.get("decision") or "",
                            es[1], es[0], pp[1], pp[0], sh[1], sh[0], _int(p.get("pim"))])
        out[side] = {"sk": skaters, "g": goalies,
                     "sog": _int((box.get(side + "Team") or {}).get("sog")),
                     "score": _int((box.get(side + "Team") or {}).get("score"))}

    # From the game summary: who had the first assist on each goal, who took
    # and who drew each minor penalty, the goals in order and the three stars.
    summary = (landing or {}).get("summary") or {}
    rows = {r["id"]: r for side in ("away", "home") for r in out[side]["sk"]}
    side_of = {abbr["away"]: "away", abbr["home"]: "home"}
    goals = []
    for per in summary.get("scoring") or []:
        d = per.get("periodDescriptor") or {}
        if d.get("periodType") == "SO":
            continue
        for g in per.get("goals") or []:
            helpers = [_int(a.get("playerId")) for a in g.get("assists") or [] if a.get("playerId")]
            if helpers and helpers[0] in rows:
                rows[helpers[0]]["a1"] += 1
            goals.append([_int(d.get("number")), d.get("periodType") or "REG", g.get("timeInPeriod") or "",
                          1 if side_of.get(_text(g.get("teamAbbrev"))) == "home" else 0, _int(g.get("playerId")), helpers,
                          g.get("strength") or "ev", g.get("goalModifier") or "none",
                          _int(g.get("awayScore")), _int(g.get("homeScore")), _text(g.get("name"))])
    for per in summary.get("penalties") or []:
        for pen in per.get("penalties") or []:
            minors = {2: 1, 4: 2}.get(_int(pen.get("duration")))
            side = side_of.get(_text(pen.get("teamAbbrev")))
            if not minors or not side:
                continue
            taker = by_number[side].get(_int((pen.get("committedByPlayer") or {}).get("sweaterNumber"), None))
            drawer = by_number["home" if side == "away" else "away"].get(_int((pen.get("drawnBy") or {}).get("sweaterNumber"), None))
            if taker:
                taker["pt"] += minors
            if drawer:
                drawer["pd"] += minors
    out["goals"] = goals
    out["stars"] = [[_int(s.get("playerId")), _text(s.get("teamAbbrev")), _text(s.get("name"))]
                    for s in sorted(summary.get("threeStars") or [], key=lambda s: _int(s.get("star")))]

    line = ((rail or {}).get("linescore") or {}).get("byPeriod") or []
    out["line"] = [[_int((p.get("periodDescriptor") or {}).get("number")), (p.get("periodDescriptor") or {}).get("periodType") or "REG",
                    _int(p.get("away")), _int(p.get("home"))] for p in line]
    team_stats = {"away": {}, "home": {}}
    for row in (rail or {}).get("teamGameStats") or []:
        cat = row.get("category")
        for side in ("away", "home"):
            v, t = row.get(side + "Value"), team_stats[side]
            if cat == "faceoffWins":
                t["fow"], t["fot"] = _pair(v)
            elif cat == "powerPlay":
                t["ppg"], t["ppo"] = _pair(v)
            elif cat in ("sog", "pim", "hits", "blockedShots", "giveaways", "takeaways"):
                t[{"blockedShots": "blk", "giveaways": "gv", "takeaways": "tk"}.get(cat, cat)] = _int(v)
    for side in ("away", "home"):
        t, sk = team_stats[side], out[side]["sk"]
        t.setdefault("sog", out[side]["sog"])          # without the team totals, add up the players'
        for key in ("pim", "hits", "blk", "gv", "tk"):
            t.setdefault(key, sum(r[key] for r in sk))
        out[side]["sk"] = [[r[c] for c in SK] for r in sk]
    out["tstats"] = team_stats
    return out


def fetch_box(game_id: int) -> dict:
    """A game's box score, with its summary and team totals when they can be read."""
    docs = {}
    for path, doc, err in web.get_many([f"gamecenter/{game_id}/{part}" for part in ("boxscore", "landing", "right-rail")]):
        if err is not None and path.endswith("boxscore"):
            raise err
        docs[path.rsplit("/", 1)[1]] = doc
    return parse_box(docs["boxscore"], docs.get("landing"), docs.get("right-rail"))


# ----------------------------------------------------------------- rosters --
def parse_person(p: dict, team: str | None) -> dict | None:
    """A player's details, from a team's roster or from his own page in the feed."""
    pid = p.get("id") or p.get("playerId")
    if not pid:
        return None
    place = [_text(p.get("birthCity")), _text(p.get("birthStateProvince")), p.get("birthCountry") or ""]
    out = {"first": _text(p.get("firstName")), "last": _text(p.get("lastName")),
           "num": _int(p.get("sweaterNumber"), None), "pos": p.get("positionCode") or p.get("position") or "",
           "sh": p.get("shootsCatches") or "", "ht": _int(p.get("heightInInches"), None),
           "wt": _int(p.get("weightInPounds"), None), "born": p.get("birthDate") or "",
           "from": ", ".join(x for x in place if x), "team": team or p.get("currentTeamAbbrev") or "",
           "photo": p.get("headshot") or ""}
    return {k: v for k, v in out.items() if v not in (None, "")} | {"id": int(pid)}


def parse_roster(doc: dict, team: str) -> list[dict]:
    out = []
    for group in ("forwards", "defensemen", "goalies"):
        for p in doc.get(group) or []:
            person = parse_person(p, team)
            if person:
                out.append(person)
    return out
