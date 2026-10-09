"""Checks on documents in the shape the NHL's feed sends them.
Run with:  python tests/run_local.py   (or pytest)

The small documents written out below copy the feed's own field names; the
files in tests/fixtures are copies of real answers from the feed."""
import datetime as dt
import gzip
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline import awards, careers, config, goat, lines, nhl, odds, players, run, teams, xg

FIX = Path(__file__).parent / "fixtures"
UTC = dt.timezone.utc


def fixture(name):
    return json.load(gzip.open(FIX / name))


def team(abbr, common, score=None):
    t = {"id": 1, "commonName": {"default": common}, "placeName": {"default": "Somewhere"}, "abbrev": abbr}
    if score is not None:
        t["score"] = score
    return t


def sched(gid=2026020056, state="OFF", away=("UTA", "Mammoth", 1), home=("BOS", "Bruins", 6), **more):
    g = {"id": gid, "season": 20262027, "gameType": 2, "neutralSite": False, "startTimeUTC": "2026-10-08T23:00:00Z",
         "gameState": state, "gameScheduleState": "OK",
         "tvBroadcasts": [{"id": 558, "market": "A", "countryCode": "US", "network": "Utah16"},
                          {"id": 131, "market": "N", "countryCode": "CA", "network": "TSN2"},
                          {"id": 31, "market": "H", "countryCode": "US", "network": "NESN"},
                          {"id": 9, "market": "N", "countryCode": "US", "network": "ESPN+"},
                          {"id": 10, "market": "A", "countryCode": "US", "network": "ABTV "}],
         "awayTeam": team(*away), "homeTeam": team(*home),
         "periodDescriptor": {"number": 3, "periodType": "REG", "maxRegulationPeriods": 3}}
    if state in ("OFF", "FINAL"):
        g["gameOutcome"] = {"lastPeriodType": "REG"}
    g.update(more)
    return g


# ------------------------------------------------------------ the schedule --
def test_a_finished_game_is_read():
    g = nhl.parse_game(sched(), "2026-10-08")
    assert g["id"] == 2026020056 and g["date"] == "2026-10-08" and g["state"] == "final" and g["end"] == "REG"
    assert g["away"] == {"id": "UTA", "name": "Mammoth", "score": 1} and g["home"] == {"id": "BOS", "name": "Bruins", "score": 6}
    assert g["start"] == int(dt.datetime(2026, 10, 8, 23, 0, tzinfo=UTC).timestamp())
    assert g["type"] == 2 and g["round"] == "" and "neutral" not in g


def test_game_states():
    coming = nhl.parse_game(sched(state="FUT", away=("DAL", "Stars"), home=("COL", "Avalanche")), "2026-10-14")
    assert coming["state"] == "upcoming" and coming["away"]["score"] is None and "end" not in coming
    live = nhl.parse_game(sched(state="LIVE", periodDescriptor={"number": 2, "periodType": "REG"}), "2026-10-08")
    assert live["state"] == "live" and live["period"] == [2, "REG"] and live["home"]["score"] == 6
    assert nhl.parse_game(sched(state="CRIT"), "2026-10-08")["state"] == "live"
    off = nhl.parse_game(sched(state="FUT", gameScheduleState="PPD", away=("DAL", "Stars"), home=("COL", "Avalanche")), "2026-10-14")
    assert off["state"] == "other" and off["note"] == "Postponed"
    overtime = nhl.parse_game(sched(gameOutcome={"lastPeriodType": "SO"}), "2026-10-08")
    assert overtime["end"] == "SO"
    unset = nhl.parse_game(sched(state="FUT", gameScheduleState="TBD", away=("DAL", "Stars"), home=("COL", "Avalanche")), "2026-10-14")
    assert unset["start"] is None and unset["state"] == "upcoming"


def test_only_regular_season_and_playoff_games_are_listed():
    assert nhl.parse_game(sched(gameType=1), "2026-09-25") is None                 # preseason
    assert nhl.parse_game(sched(gameType=4), "2027-02-06") is None                 # all-star game
    assert nhl.parse_game(sched(state="FUT", away=("", "TBD"), home=("COL", "Avalanche")), "2027-04-20") is None
    playoff = nhl.parse_game(sched(gameType=3, seriesStatus={"round": 1, "seriesTitle": "1st Round", "gameNumberOfSeries": 3}), "2027-04-20")
    assert playoff["type"] == 3 and playoff["round"] == "1st Round, Game 3"
    week = nhl.parse_week({"gameWeek": [{"date": "2026-10-08", "games": [sched(), sched(gid=1, gameType=1)]},
                                        {"date": "2026-10-09", "games": []}]})
    assert [g["id"] for g in week] == [2026020056]


def test_channels_national_first_and_this_country_first():
    assert nhl.parse_game(sched(), "2026-10-08")["tv"] == ["ESPN+", "NESN", "Utah16", "ABTV"]      # at most four, names trimmed
    assert nhl.watch([{"market": "H", "countryCode": "CA", "network": "TSN2"}, {"market": "N", "countryCode": "CA", "network": "SN"}]) == ["SN", "TSN2"]
    assert nhl.watch([]) == [] and nhl.watch(None) == []


def test_seasons_and_weeks():
    assert nhl.season_for(dt.date(2026, 10, 9)) == 2026 and nhl.season_for(dt.date(2027, 6, 10)) == 2026
    assert nhl.season_for(dt.date(2027, 8, 31)) == 2026 and nhl.season_for(dt.date(2027, 9, 1)) == 2027
    weeks = nhl.season_weeks(2026)
    assert weeks[0] == "2026-09-15" and weeks[-1] >= "2027-06-24" and len(weeks) == 42
    gaps = {(dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days for a, b in zip(weeks, weeks[1:])}
    assert gaps == {7}                               # the feed answers with seven days from the date asked for


def test_a_real_week_of_the_schedule_is_read():
    week = nhl.parse_week(fixture("schedule_2026-10-09.json.gz"))
    assert len(week) == 53 and {g["date"] for g in week} == {f"2026-10-{d:02d}" for d in range(9, 16)}
    first = week[0]
    assert first == {"id": 2026020066, "date": "2026-10-09", "start": 1791586800, "type": 2, "state": "upcoming", "note": "", "round": "",
                     "away": {"id": "SEA", "name": "Kraken", "score": None}, "home": {"id": "DET", "name": "Red Wings", "score": None},
                     "tv": ["DSN", "Prime Video", "KING", "KONG"]}
    assert all(g["start"] and 1 <= len(g["tv"]) <= config.WATCH_MAX for g in week)


# ----------------------------------------------------------- the standings --
def standing(abbr, name, seq, w, l, o, conf="Western", div="Central", **more):
    t = {"teamAbbrev": {"default": abbr}, "teamName": {"default": name}, "teamCommonName": {"default": name.split()[-1]},
         "placeName": {"default": name.split()[0]}, "conferenceName": conf, "divisionName": div, "leagueSequence": seq,
         "conferenceSequence": seq, "divisionSequence": seq, "wildcardSequence": 0, "gamesPlayed": w + l + o, "wins": w,
         "losses": l, "otLosses": o, "points": 2 * w + o, "pointPctg": (2 * w + o) / (2 * (w + l + o) or 1),
         "regulationWins": w, "regulationPlusOtWins": w, "goalFor": 3 * w, "goalAgainst": 3 * l, "goalDifferential": 3 * (w - l),
         "homeWins": w, "homeLosses": 0, "homeOtLosses": 0, "roadWins": 0, "roadLosses": l, "roadOtLosses": o,
         "l10Wins": w, "l10Losses": l, "l10OtLosses": o, "streakCode": "W", "streakCount": 4}
    t.update(more)
    return t


def test_standings_are_read():
    table = nhl.parse_standings({"standings": [standing("VGK", "Vegas Golden Knights", 2, 4, 1, 0),
                                               standing("NYR", "New York Rangers", 1, 4, 1, 0, conf="Eastern", div="Metropolitan"),
                                               standing("EDM", "Edmonton Oilers", 3, 3, 0, 1, clinchIndicator="x")]})
    assert [t["id"] for t in table] == ["NYR", "VGK", "EDM"] and [t["rank"] for t in table] == [1, 2, 3]
    r = table[0]
    assert r["name"] == "New York Rangers" and r["short"] == "Rangers" and r["conf"] == "Eastern" and r["div"] == "Metropolitan"
    assert (r["gp"], r["w"], r["l"], r["otl"], r["pts"], r["pct"]) == (5, 4, 1, 0, 8, 0.8)
    assert r["home"] == "4-0-0" and r["away"] == "0-1-0" and r["l10"] == "4-1-0" and r["streak"] == "W4" and r["diff"] == 9
    assert table[2]["clinch"] == "x" and table[2]["otl"] == 1 and table[2]["pts"] == 7


def test_the_real_standings_are_read():
    table = nhl.parse_standings(fixture("standings_now.json.gz"))
    assert len(table) == 32 and [t["rank"] for t in table] == list(range(1, 33))
    assert table[0] == {"id": "NYR", "name": "New York Rangers", "short": "Rangers", "place": "NY Rangers", "conf": "Eastern",
                        "div": "Metropolitan", "rank": 1, "conf_rank": 1, "div_rank": 1, "wc": 0, "clinch": "", "gp": 5, "w": 4, "l": 1,
                        "otl": 0, "pts": 8, "pct": 0.8, "rw": 4, "row": 4, "gf": 16, "ga": 8, "diff": 8, "home": "3-0-0", "away": "1-1-0",
                        "l10": "4-1-0", "streak": "W4"}
    sizes = {}
    for t in table:
        sizes[(t["conf"], t["div"])] = sizes.get((t["conf"], t["div"]), 0) + 1
    assert sizes == {("Eastern", "Atlantic"): 8, ("Eastern", "Metropolitan"): 8, ("Western", "Central"): 8, ("Western", "Pacific"): 8}
    assert all(t["pts"] == 2 * t["w"] + t["otl"] and t["gp"] == t["w"] + t["l"] + t["otl"] for t in table)


# -------------------------------------------------------------- box scores --
def skater(pid, num, name, pos, g=0, a=0, toi="15:00", **more):
    p = {"playerId": pid, "sweaterNumber": num, "name": {"default": name}, "position": pos, "goals": g, "assists": a,
         "points": g + a, "plusMinus": 0, "pim": 0, "hits": 1, "powerPlayGoals": 0, "sog": 2, "faceoffWinningPctg": 0,
         "toi": toi, "blockedShots": 1, "shifts": 20, "giveaways": 0, "takeaways": 1}
    p.update(more)
    return p


def goalie(pid, num, name, saves, shots, toi="60:00", starter=True, decision="W"):
    return {"playerId": pid, "sweaterNumber": num, "name": {"default": name}, "position": "G",
            "evenStrengthShotsAgainst": f"{saves - 2}/{shots - 2}", "powerPlayShotsAgainst": "2/2", "shorthandedShotsAgainst": "0/0",
            "saveShotsAgainst": f"{saves}/{shots}", "goalsAgainst": shots - saves, "toi": toi, "starter": starter,
            "decision": decision, "shotsAgainst": shots, "saves": saves, "pim": 0}


def game_docs(state="OFF"):
    box = {"id": 2026020056, "gameDate": "2026-10-08", "gameState": state,
           "awayTeam": {"abbrev": "UTA", "score": 1, "sog": 37}, "homeTeam": {"abbrev": "BOS", "score": 2, "sog": 22},
           "playerByGameStats": {
               "awayTeam": {"forwards": [skater(11, 8, "N. Schmaltz", "C", g=1, faceoffWinningPctg=0.8), skater(12, 9, "C. Keller", "L", toi="00:00")],
                            "defense": [skater(13, 6, "J. Marino", "D", toi="19:33", pim=2)],
                            "goalies": [goalie(14, 33, "S. Cossa", 20, 22, decision="L"), goalie(15, 70, "K. Vejmelka", 0, 0, toi="00:00", starter=False, decision="")]},
               "homeTeam": {"forwards": [skater(21, 88, "D. Pastrnak", "R", g=1, a=1, powerPlayGoals=1), skater(22, 28, "E. Lindholm", "C", a=2)],
                            "defense": [skater(23, 6, "M. Lohrei", "D", g=1, a=1, toi="15:43")],
                            "goalies": [goalie(24, 1, "J. Swayman", 36, 37)]}}}
    def goal(pid, name, abbr, helpers, away, home, strength="ev", time="10:06"):
        return {"strength": strength, "playerId": pid, "name": {"default": name}, "teamAbbrev": {"default": abbr}, "timeInPeriod": time,
                "goalModifier": "none", "awayScore": away, "homeScore": home, "assists": [{"playerId": h, "name": {"default": "x"}} for h in helpers]}
    landing = {"summary": {
        "scoring": [{"periodDescriptor": {"number": 1, "periodType": "REG"}, "goals": [goal(21, "D. Pastrnak", "BOS", [22, 23], 0, 1, "pp")]},
                    {"periodDescriptor": {"number": 2, "periodType": "REG"}, "goals": [goal(11, "N. Schmaltz", "UTA", [], 1, 1)]},
                    {"periodDescriptor": {"number": 3, "periodType": "REG"}, "goals": [goal(23, "M. Lohrei", "BOS", [21, 22], 1, 2, time="19:01")]},
                    {"periodDescriptor": {"number": 5, "periodType": "SO"}, "goals": [{"playerId": 21}]}],
        "threeStars": [{"star": 2, "playerId": 23, "teamAbbrev": "BOS", "name": {"default": "M. Lohrei"}},
                       {"star": 1, "playerId": 21, "teamAbbrev": "BOS", "name": {"default": "D. Pastrnak"}}],
        "penalties": [{"periodDescriptor": {"number": 1}, "penalties": [
            {"type": "MIN", "duration": 2, "committedByPlayer": {"sweaterNumber": 6}, "teamAbbrev": {"default": "UTA"}, "drawnBy": {"sweaterNumber": 88}},
            {"type": "MIN", "duration": 4, "committedByPlayer": {"sweaterNumber": 28}, "teamAbbrev": {"default": "BOS"}, "drawnBy": {"sweaterNumber": 8}},
            {"type": "MAJ", "duration": 5, "committedByPlayer": {"sweaterNumber": 6}, "teamAbbrev": {"default": "BOS"}, "drawnBy": {"sweaterNumber": 6}},
            {"type": "BEN", "duration": 2, "teamAbbrev": {"default": "BOS"}}]}]}}
    rail = {"gameInfo": {"awayTeam": {"headCoach": {"default": "Andre Tourigny"}}, "homeTeam": {"headCoach": {"default": "Marco Sturm"}}},
            "linescore": {"byPeriod": [{"periodDescriptor": {"number": n, "periodType": "REG"}, "away": a, "home": h} for n, a, h in ((1, 0, 1), (2, 1, 0), (3, 0, 1))],
                          "totals": {"away": 1, "home": 2}},
            "teamGameStats": [{"category": "sog", "awayValue": 37, "homeValue": 22}, {"category": "faceoffWinningPctg", "awayValue": 0.536, "homeValue": 0.464},
                              {"category": "faceoffWins", "awayValue": "37/69", "homeValue": "32/69"}, {"category": "powerPlay", "awayValue": "0/7", "homeValue": "1/4"},
                              {"category": "pim", "awayValue": 8, "homeValue": 14}, {"category": "hits", "awayValue": 19, "homeValue": 23},
                              {"category": "blockedShots", "awayValue": 6, "homeValue": 23}, {"category": "giveaways", "awayValue": 12, "homeValue": 18},
                              {"category": "takeaways", "awayValue": 3, "homeValue": 6}]}
    return box, landing, rail


def test_a_box_score_is_read():
    b = nhl.parse_box(*game_docs())
    assert b["status"] == "F" and b["full"] and b["date"] == "2026-10-08"
    away = [dict(zip(nhl.SK, r)) for r in b["away"]["sk"]]
    home = {r[0]: dict(zip(nhl.SK, r)) for r in b["home"]["sk"]}
    assert [p["id"] for p in away] == [11, 13]                          # the forward who did not play is left out
    assert away[0]["name"] == "N. Schmaltz" and away[0]["toi"] == 900 and away[0]["fo"] == 80 and away[1]["toi"] == 1173
    assert (home[21]["g"], home[21]["a"], home[21]["a1"], home[21]["ppg"]) == (1, 1, 1, 1)
    # points on the power play, and the game-winning goal: Boston's second in a 2-1 win
    assert (home[21]["ppp"], home[22]["ppp"], home[23]["ppp"], away[0]["ppp"]) == (1, 1, 1, 0)
    assert (home[23]["gwg"], home[21]["gwg"], away[0]["gwg"]) == (1, 0, 0) and "adv" not in b
    assert (home[22]["a"], home[22]["a1"]) == (2, 1) and (home[23]["a"], home[23]["a1"]) == (1, 0)
    # minor penalties: taken and drawn, a double minor counts twice, majors and bench minors do not count
    assert (away[1]["pt"], away[1]["pd"]) == (1, 0) and (home[21]["pt"], home[21]["pd"]) == (0, 1)
    assert (home[22]["pt"], away[0]["pd"]) == (2, 2) and home[23]["pt"] == 0
    goalies = [dict(zip(nhl.GK, r)) for r in b["away"]["g"]]
    assert len(goalies) == 1 and goalies[0]["name"] == "S. Cossa"       # the backup who did not play is left out
    g = goalies[0]
    assert (g["sa"], g["sv"], g["ga"], g["toi"], g["start"], g["dec"]) == (22, 20, 2, 3600, 1, "L")
    assert (g["es_sa"], g["es_sv"], g["pp_sa"], g["pp_sv"], g["sh_sa"]) == (20, 18, 2, 2, 0)
    assert b["line"] == [[1, "REG", 0, 1], [2, "REG", 1, 0], [3, "REG", 0, 1]]
    assert [x[:5] for x in b["goals"]] == [[1, "REG", "10:06", 1, 21], [2, "REG", "10:06", 0, 11], [3, "REG", "19:01", 1, 23]]
    assert b["goals"][0][5] == [22, 23] and b["goals"][0][6] == "pp" and b["goals"][2][8:10] == [1, 2]
    assert b["stars"] == [[21, "BOS", "D. Pastrnak"], [23, "BOS", "M. Lohrei"]]
    assert b["tstats"]["away"] == {"sog": 37, "fow": 37, "fot": 69, "ppg": 0, "ppo": 7, "pim": 8, "hits": 19, "blk": 6, "gv": 12, "tk": 3}
    assert b["tstats"]["home"]["ppg"] == 1 and b["tstats"]["home"]["ppo"] == 4
    assert b["coach"] == {"away": "Andre Tourigny", "home": "Marco Sturm"}


def test_a_box_score_without_its_summary_is_kept_but_marked():
    box, _, _ = game_docs("LIVE")
    b = nhl.parse_box(box, None, None)
    assert b["status"] == "L" and not b["full"] and b["goals"] == [] and b["line"] == []
    assert not run.complete(b) and not run.complete(nhl.parse_box(*game_docs())) and not run.complete(None)
    whole = nhl.parse_box(*game_docs(), plays=fixture("play-by-play_2025020500.json.gz"))
    assert run.complete(whole) and whole["adv"]["xg"][1] > whole["adv"]["xg"][0]
    assert not run.complete({**whole, "adv": {**whole["adv"], "v": "an older model"}})
    assert not run.complete({k: v for k, v in whole.items() if k != "coach"})          # stored before coaches were kept
    assert b["tstats"]["away"]["sog"] == 37 and b["tstats"]["home"]["hits"] == 3     # added up from the players
    assert "ppo" not in b["tstats"]["home"]


def test_a_real_box_score_is_read():
    """Toronto at Vegas, October 8, 2026: Vegas won 4-3 in a shootout."""
    b = nhl.parse_box(*(fixture(f"gamecenter_2026020065_{part}.json.gz") for part in ("boxscore", "landing", "right-rail")))
    assert b["status"] == "F" and b["full"] and b["date"] == "2026-10-08"
    assert len(b["away"]["sk"]) == 18 and len(b["home"]["sk"]) == 18 and len(b["away"]["g"]) == 1 and len(b["home"]["g"]) == 1
    assert b["line"] == [[1, "REG", 3, 1], [2, "REG", 0, 2], [3, "REG", 0, 0], [4, "OT", 0, 0], [5, "SO", 0, 1]]
    assert len(b["goals"]) == 6                                        # the shootout winner is not a goal scored
    assert b["goals"][0] == [1, "REG", "00:34", 0, 8478458, [8479318, 8480893], "ev", "none", 1, 0, "J. Roslovic"]
    assert b["goals"][5][7] == "penalty-shot" and b["goals"][5][5] == [] and b["goals"][5][8:10] == [3, 3]
    assert [s[1] for s in b["stars"]] == ["VGK", "VGK", "VGK"] and b["stars"][1][0] == 8478403
    for side, goals in (("away", 3), ("home", 3)):
        rows = [dict(zip(nhl.SK, r)) for r in b[side]["sk"]]
        assert sum(r["g"] for r in rows) == goals and sum(r["sog"] for r in rows) == b["tstats"][side]["sog"]
        assert sum(r["a1"] for r in rows) == sum(1 for g in b["goals"] if g[3] == (side == "home") and g[5])
        assert all(300 < r["toi"] < 2100 for r in rows)
    hill = dict(zip(nhl.GK, b["home"]["g"][0]))
    assert (hill["name"], hill["sa"], hill["sv"], hill["ga"], hill["dec"], hill["start"]) == ("A. Hill", 24, 21, 3, "W", 1)
    assert hill["es_sa"] + hill["pp_sa"] + hill["sh_sa"] == hill["sa"] and b["away"]["g"][0][8] == "O"
    assert b["tstats"]["home"] == {"sog": 43, "fow": 25, "fot": 62, "ppg": 0, "ppo": 4, "pim": 2, "hits": 27, "blk": 15, "gv": 17, "tk": 3}
    # Toronto took four minors (Vegas had four power plays) and Vegas one; each was drawn by someone
    taken = {side: sum(r[nhl.SK.index("pt")] for r in b[side]["sk"]) for side in ("away", "home")}
    drawn = {side: sum(r[nhl.SK.index("pd")] for r in b[side]["sk"]) for side in ("away", "home")}
    assert taken == {"away": 4, "home": 1} and drawn == {"away": 1, "home": 4}


def test_a_real_roster_is_read():
    roster = nhl.parse_roster(fixture("roster_DAL_current.json.gz"), "DAL")
    assert len(roster) == 24 and all(p["team"] == "DAL" and p["first"] and p["last"] and p["photo"].startswith("https://") for p in roster)
    assert roster[0] == {"id": 8473994, "first": "Jamie", "last": "Benn", "num": 14, "pos": "L", "sh": "L", "ht": 75, "wt": 210,
                         "born": "1989-07-18", "from": "Victoria, BC, CAN", "team": "DAL",
                         "photo": "https://assets.nhle.com/mugs/nhl/20262027/DAL/8473994.png"}
    assert {p["pos"] for p in roster} == {"C", "L", "R", "D", "G"}


def test_a_roster_is_read():
    doc = {"forwards": [{"id": 8473994, "headshot": "https://assets.nhle.com/mugs/nhl/20262027/DAL/8473994.png", "firstName": {"default": "Jamie"},
                         "lastName": {"default": "Benn"}, "sweaterNumber": 14, "positionCode": "L", "shootsCatches": "L", "heightInInches": 75,
                         "weightInPounds": 210, "birthDate": "1989-07-18", "birthCity": {"default": "Victoria"}, "birthCountry": "CAN",
                         "birthStateProvince": {"default": "BC"}}],
           "defensemen": [{"id": 8483425, "firstName": {"default": "Lian"}, "lastName": {"default": "Bichsel"}, "positionCode": "D",
                           "birthCity": {"default": "Olten"}, "birthCountry": "CHE"}], "goalies": []}
    benn, bichsel = nhl.parse_roster(doc, "DAL")
    assert benn == {"id": 8473994, "first": "Jamie", "last": "Benn", "num": 14, "pos": "L", "sh": "L", "ht": 75, "wt": 210, "born": "1989-07-18",
                    "from": "Victoria, BC, CAN", "team": "DAL", "photo": "https://assets.nhle.com/mugs/nhl/20262027/DAL/8473994.png"}
    assert bichsel["from"] == "Olten, CHE" and "num" not in bichsel and "photo" not in bichsel


# --------------------------------------------------------------- the odds --
def played(gid, date, away, home, vs, hs, end="REG", kind=2):
    return {"id": gid, "date": date, "start": gid, "type": kind, "state": "final", "end": end,
            "away": {"id": away, "name": away, "score": vs}, "home": {"id": home, "name": home, "score": hs}}


def test_odds():
    assert odds.game_chance(0.0, 0.0, neutral=True) == 0.5
    assert 0.52 < odds.game_chance(0.0, 0.0) < 0.55                          # home ice
    assert abs(odds.game_chance(0.2, -0.1, neutral=True) + odds.game_chance(-0.1, 0.2, neutral=True) - 1) < 1e-12
    assert odds.game_chance(0.3, -0.3) > 0.75 > odds.game_chance(0.1, -0.1)
    games = [played(1, "2026-10-01", "AAA", "BBB", 1, 5), played(2, "2026-10-03", "BBB", "AAA", 4, 2),
             {**played(3, "2026-10-05", "AAA", "BBB", None, None), "state": "upcoming"}]
    rating, pregame = odds.rate(games, {"AAA": 0.2, "BBB": 0.2})
    assert rating["BBB"] > config.ODDS_KEEP * 0.2 > rating["AAA"] and abs(rating["AAA"] + rating["BBB"] - 2 * config.ODDS_KEEP * 0.2) < 1e-9
    assert set(pregame) == {1, 2} and abs(pregame[1] - odds.game_chance(0.16, 0.16)) < 1e-9
    assert odds.capped(9, 1) == (1 + config.ODDS_MARGIN_CAP, 1) and odds.capped(2, 3) == (2, 3)
    seed = odds.seed()
    assert seed["season"] == 2025 and len(seed["ratings"]) == 32 and abs(sum(seed["ratings"].values())) < 0.5


def test_goat_ranking():
    table = nhl.parse_standings({"standings": [standing("AAA", "Alpha Aces", 1, 3, 0, 0), standing("BBB", "Beta Bears", 2, 2, 1, 0),
                                               standing("CCC", "Gamma Cats", 3, 0, 4, 0)]})
    games = [played(1, "2026-10-01", "CCC", "AAA", 1, 5), played(2, "2026-10-02", "CCC", "BBB", 0, 3), played(3, "2026-10-03", "BBB", "AAA", 2, 3, "SO"),
             played(4, "2026-10-04", "CCC", "BBB", 1, 2), played(5, "2026-10-05", "CCC", "AAA", 0, 1)]
    assert goat.win_streaks(games) == {"AAA": 3, "BBB": 1, "CCC": 0}
    assert goat.hot_boost(2) == 0 and goat.hot_boost(3) == 3 * config.GOAT_HOT_STEP and goat.hot_boost(40) == config.GOAT_HOT_MAX
    chances = {"AAA": [9.0, 5.0], "BBB": [8.0, 6.0], "CCC": [5.0, 11.0]}
    r = goat.rank(games, {"AAA": 0.2, "BBB": 0.0, "CCC": -0.2}, table, chances)
    assert r["order"] == ["AAA", "BBB", "CCC"] and r["streak"]["AAA"] == 3 and r["boost"]["AAA"] > 0 == r["boost"]["BBB"]
    assert abs(r["xg_pct"]["AAA"] - 9 / 14) < 1e-9 and abs(r["goal_pct"]["AAA"] - 8 / 11) < 1e-9      # the shootout win is not a goal
    assert r["sos"]["CCC"] > r["sos"]["AAA"]                             # the bottom team has played only the top two
    assert abs(sum(config.GOAT_WEIGHTS.values()) - 1) < 1e-9 and set(config.GOAT_WEIGHTS) == {"record", "sos", "xg", "goals"}
    # better chances lift a team: swap the expected goals of the top two and the gap between them narrows
    swapped = goat.rank(games, {"AAA": 0.2, "BBB": 0.0, "CCC": -0.2}, table, {**chances, "AAA": chances["BBB"], "BBB": chances["AAA"]})
    assert swapped["score"]["AAA"] - swapped["score"]["BBB"] < r["score"]["AAA"] - r["score"]["BBB"]
    # with no play-by-play yet every team is level on chances and the rest decides
    assert goat.rank(games, {}, table, {})["order"] == ["AAA", "BBB", "CCC"]


# -------------------------------------------------------- expected goals --
def shot(x, y, **more):
    s = {"home": 1, "shooter": 1, "goalie": 2, "goal": 0, "on_goal": 1, "x": x, "y": y, "shot_type": "wrist", "mine": 5, "theirs": 5,
         "empty": 0, "penalty_shot": 0, "period": 1, "secs": 600, "prev_type": "faceoff", "prev_same": 1, "since": 30.0, "prev_x": 0.0, "prev_y": 0.0}
    s.update(more)
    return s


def test_expected_goals_make_sense():
    m = xg.model()
    assert m["version"] and len(m["trees"]) == 150 and len(xg.FEATURES) == len(xg.features(shot(60, 0)))
    slot, point, corner = xg.chance(shot(80, 0)), xg.chance(shot(30, 20)), xg.chance(shot(85, 38))
    assert 0.10 < slot < 0.45 and point < 0.04 and corner < 0.04 and slot > 5 * point
    rebound = xg.chance(shot(80, 4, prev_type="shot-on-goal", since=2.0, prev_x=70.0, prev_y=-15.0))
    assert rebound > xg.chance(shot(80, 4))
    assert xg.chance(shot(60, 0, mine=5, theirs=4)) > xg.chance(shot(60, 0))                    # a power play
    assert xg.chance(shot(-40, 0, empty=1, goalie=None)) > 0.3 > xg.chance(shot(-40, 0))        # an empty net from his own end
    assert xg.chance(shot(60, 0, penalty_shot=1)) == xg.PENALTY_SHOT
    assert all(0 < xg.chance(shot(x, y)) < 1 for x in range(-99, 100, 9) for y in range(-42, 43, 7))


def test_a_real_play_by_play_is_read():
    """Montreal at the Rangers, 2025-26: the Rangers won 5-4."""
    doc = fixture("play-by-play_2025020500.json.gz")
    evs = xg.events(doc)
    taken = [e for e in evs if e["type"] in xg.UNBLOCKED and e["x"] is not None]
    assert sum(e["x"] > 0 for e in taken) > 0.9 * len(taken)            # every team is turned to shoot toward +x
    shots = xg.shots(evs)
    assert sum(s["goal"] for s in shots) == 9 and len(shots) == 9 + 38 + 43
    a = xg.summarize(doc)
    assert a["v"] == xg.model()["version"] and 2.0 < a["xg"][0] < 3.5 and 4.0 < a["xg"][1] < 6.0
    assert abs(sum(v[2] for v in a["sk"].values()) - sum(a["xg"])) < 0.05
    assert sum(v[1] for v in a["sk"].values()) == len(shots) and sum(v[0] for v in a["sk"].values()) == len(shots) + 43     # plus the blocked ones
    assert sum(v[3] for v in a["sk"].values()) == 49 and sum(v[4] for v in a["sk"].values()) == 98                # 49 faceoffs, two players in each
    assert len(a["g"]) == 2 and sum(g[1] for g in a["g"].values()) == 8        # one of the nine goals was into an empty net
    assert all(v[0] >= v[1] and v[4] >= v[3] for v in a["sk"].values())


# ------------------------------------------------------------------- lines --
def test_lines_are_read_off_a_real_shift_chart():
    """Chicago at Florida, the first game of 2025-26."""
    who = fixture("positions_2025020001.json.gz")
    pos = {int(p): v[0] for p, v in who.items() if v[0] != "G"}
    name = lambda ids: sorted(who[str(p)][1] for p in ids)
    shifts = lines.parse_shifts(fixture("shiftcharts_2025020001.json.gz"))
    assert len(shifts) > 800 and {s[0] for s in shifts} == {"CHI", "FLA"} and all(0 <= s[3] < s[4] <= 1200 for s in shifts)
    counted = lines.count(shifts, pos)
    fla = counted["FLA"]
    assert name(fla["f"][0][0]) == ["Bennett", "Marchand", "Verhaeghe"] and 700 < fla["f"][0][1] < 1000       # about 14 minutes together
    assert name(fla["d"][0][0]) == ["Jones", "Mikkola"] and all(len(ids) == 3 for ids, _ in fla["f"]) and all(len(ids) == 2 for ids, _ in fla["d"])
    assert all(4 <= len(ids) <= 5 for ids, _ in fla["pp"]) and all(3 <= len(ids) <= 4 for ids, _ in fla["pk"])
    ice = {}
    for team, pid, _, start, end in shifts:
        if team == "FLA" and pid in pos:
            ice[pid] = ice.get(pid, 0) + end - start
    dressed = [{"id": p, "pos": pos[p], "toi": t, "fo": 0, "sh": "L"} for p, t in ice.items()]
    found = lines.team_lines(fla, [fla], [fla, fla], dressed)
    assert len(found["f"]) == 4 and len(found["d"]) == 3 and len(found["pp"]) == 2 and len(found["pk"]) == 2
    everyone = [p for row in found["f"] for p in row["ids"]]
    assert len(everyone) == 12 == len(set(everyone))                                # each forward on one line only
    assert [name(r["ids"]) for r in found["d"]][:2] == [["Jones", "Mikkola"], ["Ekblad", "Forsling"]]
    assert found["f"][0]["season"] == 2 * found["f"][0]["toi"] and found["f"][0]["games"] == 2
    assert not set(found["pp"][0]["ids"]) & set(found["pp"][1]["ids"]) and len(found["pk"][0]["ids"]) == 4
    assert pos[found["f"][0]["ids"][0]] == "L"                                      # Marchand, the listed left wing, on the left


def test_a_forward_line_is_set_out_left_to_right():
    pos = {1: "C", 2: "L", 3: "R", 4: "C", 5: "C"}
    assert lines.arrange([1, 2, 3], pos, {}) == [2, 1, 3]
    assert lines.arrange([3, 1, 4], pos, {4: 12, 1: 3}) == [1, 4, 3]               # two centers: the one taking the faceoffs is in the middle
    assert lines.arrange([1, 4, 5], pos, {5: 9}) == [1, 5, 4] and lines.arrange([2, 3], pos, {}) == [2, 3]


# ------------------------------------------------------- players and teams --
def small_season():
    """Two finished games between UTA and BOS, with standings, as the job stores them."""
    table = nhl.parse_standings({"standings": [standing("BOS", "Boston Bruins", 1, 2, 0, 0), standing("UTA", "Utah Mammoth", 2, 0, 2, 0)]})
    games = [played(2026020056, "2026-10-08", "UTA", "BOS", 1, 2), played(2026020090, "2026-10-10", "UTA", "BOS", 1, 2)]
    boxes = {str(g["id"]): nhl.parse_box(*game_docs()) for g in games}
    for box in boxes.values():           # what the play-by-play adds: expected goals [away, home], skaters' attempts and faceoffs, goalies' chances faced
        box["adv"] = {"v": xg.model()["version"], "xg": [1.5, 3.0],
                      "sk": {"21": [6, 4, 1.2, 0, 0], "22": [3, 2, 0.6, 9, 12], "11": [5, 4, 1.0, 3, 12]},
                      "g": {"24": [1.5, 1], "14": [3.0, 2]}}
    return table, games, boxes


def test_players_are_rated_against_their_position():
    table, games, boxes = small_season()
    people = {"21": {"first": "David", "last": "Pastrnak", "photo": "p.png", "ht": 72, "sh": "R"}}
    rated = players.compute(table, games, boxes, people)
    by = {p["id"]: p for p in rated["players"]}
    v = lambda p, key: by[p]["v"][rated["metrics"].index(key)]
    assert by[21]["name"] == "David Pastrnak" and by[21]["photo"] == "p.png" and by[21]["bio"] == {"sh": "R", "ht": 72}
    assert by[11]["name"] == "N. Schmaltz" and "photo" not in by[11]            # no roster details: the box score's short name
    assert by[21]["gp"] == 2 and by[21]["tot"]["g"] == 2 and by[21]["tot"]["pts"] == 4 and by[21]["tot"]["a1"] == 2 and by[21]["tot"]["pd"] == 2
    assert by[21]["grp"] == "F" and by[23]["grp"] == "D" and by[24]["grp"] == "G" and by[21]["team_id"] == "BOS"
    assert abs(v(21, "toi_gp") - 15.0) < 1e-9 and abs(v(21, "g60") - 4.0) < 1e-9 and abs(v(21, "p60") - 8.0) < 1e-9
    # Impact is measured against the position's average, so the forwards' impacts add up to nothing
    forwards = [p for p in rated["players"] if p["grp"] == "F"]
    assert abs(sum(v(p["id"], "impact_gp") * p["gp"] for p in forwards)) < 0.01
    assert by[21]["impact"] > 0 > by[22]["impact"] and by[21]["rank"] < by[22]["rank"]
    assert sorted(p["rank"] for p in rated["players"] if p["grp"] != "G") == [1, 2, 3, 4, 5]
    assert abs(v(24, "svp") - 100 * 36 / 37) < 0.01 and abs(v(24, "gaa") - 1.0) < 1e-9 and by[24]["tot"]["w"] == 2
    assert by[24]["impact"] > 0 > by[14]["impact"] and by[24]["rank"] == 1 and by[14]["rank"] == 2      # goalies ranked on their own
    assert by[14]["tot"]["l"] == 2 and rated["regulars"] == 5 and rated["pos_regulars"] == {"F": 3, "D": 2, "G": 2}
    assert all(p["regular"] for p in rated["players"]) and by[21]["pct"][0] is None       # too few players for percentiles
    # from the play-by-play: attempts, expected goals, finishing, faceoffs; goals saved above expected
    assert by[21]["tot"]["att"] == 12 and by[21]["tot"]["ixg"] == 2.4 and abs(v(21, "ixg60") - 4.8) < 1e-6 and abs(v(21, "gax60") + 0.8) < 1e-6
    assert by[22]["tot"]["fow"] == 18 and abs(v(22, "fo_pct") - 75.0) < 1e-9 and v(23, "fo_pct") is None and v(23, "ixg60") is None
    assert by[24]["tot"]["gsax"] == 1.0 and by[14]["tot"]["gsax"] == 2.0 and abs(v(24, "gsax60") - 0.5) < 1e-9
    assert by[21]["tot"]["ppp"] == 2 and by[23]["tot"]["gwg"] == 2
    scaled = players.compute(table, games, boxes, people, xg_scale=0.5)
    assert {p["id"]: p for p in scaled["players"]}[21]["tot"]["ixg"] == 1.2
    log = rated["logs"][21]
    assert len(log) == 2 and log[0][:5] == [2026020090, "2026-10-10", "UTA", 1, "W 2-1"] and log[0][5:] == [1, 1, 0, 2, 1, 1, 0, 900, 1.2]
    assert rated["logs"][14][0] == [2026020090, "2026-10-10", "BOS", 0, "L 1-2", 22, 20, 2, 3600, "L", 1.0]


def career_page():
    """A player's own page in the feed, cut down to what is read: Connor McDavid's last seasons."""
    def nhl_row(season, kind, gp, g, a, **more):
        return {"season": season, "gameTypeId": kind, "leagueAbbrev": "NHL", "sequence": 1, "gamesPlayed": gp, "goals": g, "assists": a,
                "points": g + a, "plusMinus": 17, "pim": 44, "powerPlayGoals": 13, "powerPlayPoints": 54, "gameWinningGoals": 4,
                "shots": 306, "avgToi": "22:59", "teamCommonName": {"default": "Oilers"}, "teamName": {"default": "Edmonton Oilers"}, **more}
    return {"position": "C", "draftDetails": {"year": 2015, "teamAbbrev": "EDM", "round": 1, "pickInRound": 1, "overallPick": 1},
            "careerTotals": {"regularSeason": {"gamesPlayed": 798}, "playoffs": {"gamesPlayed": 102, "goals": 45, "assists": 111, "points": 156,
                                                                                "plusMinus": 23, "pim": 30, "powerPlayGoals": 14, "powerPlayPoints": 58,
                                                                                "gameWinningGoals": 5, "shots": 350, "avgToi": "23:38"}},
            "seasonTotals": [{"season": 20142015, "gameTypeId": 2, "leagueAbbrev": "OHL", "gamesPlayed": 47, "goals": 44, "assists": 76, "points": 120,
                              "teamName": {"default": "Erie Otters"}},
                             nhl_row(20242025, 2, 67, 26, 74, avgToi="22:00"), nhl_row(20252026, 2, 82, 48, 90), nhl_row(20252026, 3, 6, 1, 5),
                             nhl_row(20262027, 2, 4, 3, 9)]}


def test_a_career_is_read_and_joined_to_this_season():
    kept = careers.parse(career_page())
    assert kept["g"] == 0 and [r[0] for r in kept["seasons"]] == [2024, 2025, 2026]          # NHL regular seasons only
    assert kept["seasons"][1] == [2025, "Oilers", 82, 48, 90, 138, 17, 44, 13, 54, 4, 306, 1379]
    assert kept["playoffs"] == [102, 45, 111, 156, 23, 30, 14, 58, 5, 350, 1418] and kept["draft"] == [2015, 1, 1, "EDM"]
    card = {"grp": "F", "gp": 5, "tot": {"g": 4, "a": 9, "pts": 13, "pm": 11, "pim": 2, "ppg": 1, "ppp": 3, "gwg": 1, "sog": 10, "toi": 7000}}
    c = careers.build(kept, card, "Oilers", 2026)
    # this season's line is the site's own, not the feed's older copy of it
    assert [r[0] for r in c["seasons"]] == [2024, 2025, 2026] and c["seasons"][2] == [2026, "Oilers", 5, 4, 9, 13, 11, 2, 1, 3, 1, 10, 1400]
    assert c["total"][2:6] == [67 + 82 + 5, 26 + 48 + 4, 74 + 90 + 9, 100 + 138 + 13] and c["known"] and c["draft"][0] == 2015
    assert c["total"][12] == round((1320 * 67 + 1379 * 82 + 1400 * 5) / 154) and c["playoffs"][0] == 102
    rookie = careers.build(None, card, "Oilers", 2026)
    assert rookie["seasons"] == [c["seasons"][2]] and rookie["total"][2:] == c["seasons"][2][2:] and not rookie["known"] and "draft" not in rookie
    goalie_page = {"position": "G", "seasonTotals": [{"season": 20252026, "gameTypeId": 2, "leagueAbbrev": "NHL", "gamesPlayed": 60, "gamesStarted": 58,
                                                     "wins": 35, "losses": 18, "otLosses": 5, "shotsAgainst": 1700, "goalsAgainst": 150, "shutouts": 4,
                                                     "timeOnIce": "3480:30", "teamCommonName": {"default": "Stars"}}]}
    g = careers.parse(goalie_page)
    assert g["g"] == 1 and g["seasons"] == [[2025, "Stars", 60, 58, 35, 18, 5, 1700, 150, 4, 208830]] and "playoffs" not in g
    mask = {"grp": "G", "gp": 3, "tot": {"gs": 3, "w": 2, "l": 1, "otl": 0, "sa": 61, "ga": 2, "so": 2, "toi": 10697}}
    assert careers.build(g, mask, "Stars", 2026)["total"] == ["", "", 63, 61, 37, 19, 5, 1761, 152, 6, 219527]
    assert careers.build(kept, mask, "Stars", 2026)["known"] is False             # a skater's kept seasons are not a goalie's


def test_team_stats_come_from_the_box_scores():
    table, games, boxes = small_season()
    out = teams.compute(table, games, boxes, {"BOS": 0.2, "UTA": -0.1})
    bos, uta = out["teams"]
    assert out["through"] == "2026-10-10" and bos["id"] == "BOS" and bos["games"] == 2
    assert (bos["gf_gp"], bos["ga_gp"], bos["sf_gp"], bos["sa_gp"]) == (2.0, 1.0, 22.0, 37.0)
    assert bos["pp_pct"] == 25.0 and bos["pk_pct"] == 100.0 and uta["pp_pct"] == 0.0 and uta["pk_pct"] == 75.0
    assert bos["fo_pct"] == 46.4 and uta["fo_pct"] == 53.6 and bos["sv_pct"] == round(1 - 1 / 37, 3)
    assert (bos["power"], uta["power"]) == (1, 2) and bos["hits_gp"] == 23.0
    assert (bos["xgf_gp"], bos["xga_gp"], bos["xg_pct"], uta["xg_pct"]) == (3.0, 1.5, 66.7, 33.3) and bos["g_pct"] == 66.7
    shootout = [{**games[0], "end": "SO"}]
    assert teams.compute(table, shootout, boxes, {})["teams"][0]["gf_gp"] == 1.0      # the shootout winner's extra goal is not a goal scored


# ------------------------------------------------------------- the awards --
def test_who_is_a_rookie():
    season = lambda year, games: [year, "Team", games]
    assert awards.is_rookie([], "2006-06-13", 2026)                                           # first NHL games this season
    assert awards.is_rookie([season(2025, 25)], "2004-01-01", 2026)                           # 25 games is still a rookie
    assert not awards.is_rookie([season(2025, 26)], "2004-01-01", 2026)
    assert not awards.is_rookie([season(2024, 6), season(2025, 6)], "2004-01-01", 2026)       # two seasons of six games
    assert awards.is_rookie([season(2024, 5), season(2025, 6)], "2004-01-01", 2026)
    assert not awards.is_rookie([season(2025, 10), season(2025, 16)], "2004-01-01", 2026)     # 26 games for two teams in one season
    assert not awards.is_rookie([], "2000-09-15", 2026) and awards.is_rookie([], "2000-09-16", 2026)      # 26 on September 15
    assert not awards.is_rookie(None, "2006-06-13", 2026)                                     # earlier seasons not read yet
    assert awards.is_rookie([season(2026, 40)], "2006-06-13", 2026)                           # this season's own games do not count


def test_the_awards_races():
    table, games, boxes = small_season()
    people = {"21": {"first": "David", "last": "Pastrnak", "born": "1996-05-25"}, "22": {"born": "2006-01-01"}}
    rated = players.compute(table, games, boxes, people)
    kept = {"21": {"seasons": [[2025, "Bruins", 82]]}, "22": {"seasons": []}, "23": {"seasons": [[2025, "Bruins", 70]]}}
    races = awards.compute(rated, table, kept, people, {"22": 300}, {"BOS": "Marco Sturm"}, {"BOS": 0.2, "UTA": -0.2}, {"BOS": [2, 2], "UTA": [4, 2]}, 2026)
    by = {r["key"]: r for r in races}
    assert [r["key"] for r in races] == [a[0] for a in awards.ABOUT] and all(abs(sum(r.values()) - 1) < 1e-9 for r in awards.RECIPES.values())
    ross = by["art_ross"]["rows"]
    assert ross[0]["name"] == "David Pastrnak" and ross[0]["stats"][:3] == ["4 PTS", "2 G", "2 A"] and ross[0]["score"] is None and by["art_ross"]["counted"]
    assert [r["id"] for r in ross][:3] == [21, 23, 22]                    # 4 points each: goals break the tie, then games, then the lower number
    assert {r["id"] for r in by["richard"]["rows"]} == {21, 23, 11}        # only players with a goal
    assert [r["id"] for r in by["norris"]["rows"]] == [23, 13] and [r["id"] for r in by["vezina"]["rows"]] == [24, 14]
    assert [r["id"] for r in by["calder"]["rows"]] == [22]                 # the only one known to be in his first season
    assert by["selke"]["rows"][0]["id"] == 22 and "5 min killing penalties" in by["selke"]["rows"][0]["stats"]
    hart = by["hart"]["rows"]
    assert hart[0]["team"] == "BOS" and 0 <= hart[-1]["score"] <= hart[0]["score"] <= 100 and len(hart) == 7
    adams = by["adams"]["rows"]
    assert adams[0]["name"] == "Marco Sturm" and adams[0]["sub"] == "Boston Bruins" and adams[1]["name"] == "Utah Mammoth" and adams[1]["sub"] is None
    assert by["jennings"]["rows"][0]["team"] == "BOS" and by["jennings"]["rows"][0]["stats"][:2] == ["2 goals against", "1.00 a game"]
    assert by["jennings"]["rows"][0]["name"] == "J. Swayman" and by["presidents"]["rows"][0]["stats"][0] == "4 PTS"
    assert awards.expected_pct(0.0) == 0.5575 and awards.expected_pct(0.3) > awards.expected_pct(-0.3)
    # who has moved since a week ago
    snap = awards.snapshot(races)
    assert snap["art_ross"][:2] == ["21", "23"] and snap["presidents"] == ["BOS", "UTA"]
    awards.movement(races, {}, "2026-10-11")
    assert "was" not in ross[0]
    then = {"2026-10-02": {**snap, "art_ross": ["23", "21"], "presidents": ["UTA"]}, "2026-10-09": snap}
    awards.movement(races, then, "2026-10-11")                             # nine days back is the nearest snapshot at least a week old
    assert [r["was"] for r in ross][:3] == [2, 1, 0] and by["art_ross"]["since"] == "2026-10-02"
    assert [r["was"] for r in by["presidents"]["rows"]] == [0, 1]


# ----------------------------------------------------------------- the job --
def test_which_box_scores_are_fetched():
    done = {"status": "F", "full": True, "coach": {}, "adv": {"v": xg.model()["version"]}}
    games = [played(1, "2026-10-01", "A", "B", 1, 2), played(2, "2026-10-01", "A", "B", 1, 2), played(3, "2026-10-08", "A", "B", 1, 2),
             {**played(4, "2026-10-09", "A", "B", None, None), "state": "upcoming"}, played(5, "2026-10-01", "A", "B", 1, 2)]
    stored = {"1": done, "3": done, "5": {**done, "full": False}}
    want = run.boxes_wanted(games, stored, dt.date(2026, 10, 9))
    assert [g["id"] for g in want] == [2, 3, 5]       # not stored; recent, so read again for corrections; stored without its summary
    stored["5"] = {"status": "F", "full": True, "coach": {}}        # stored before the play-by-play was read
    assert [g["id"] for g in run.boxes_wanted(games, stored, dt.date(2026, 10, 9))] == [2, 3, 5]


def test_game_night_runs_only_work_when_a_game_is_on():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        at = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)
        start = int(at("2026-10-09T23:00").timestamp())
        games = {"1": {**played(1, "2026-10-09", "A", "B", None, None), "state": "upcoming", "start": start},
                 "2": {**played(2, "2026-10-08", "A", "B", 3, 2), "start": start - 86400}}
        run.write_json(state / "schedule.json", {"season": 2026, "games": games})
        ids = lambda when: [g["id"] for g in run.live_now(state, at(when))]
        assert ids("2026-10-09T15:00") == [] and ids("2026-10-09T22:30") == []
        assert ids("2026-10-09T22:45") == [1] and ids("2026-10-10T01:30") == [1] and ids("2026-10-10T04:30") == []
        games["1"].update(state="final")
        run.write_json(state / "schedule.json", {"season": 2026, "games": games})
        assert ids("2026-10-10T01:30") == [1]                       # over, but its box score is not in yet
        run.write_json(state / "box.json", {"1": {"status": "F", "full": True, "coach": {}, "adv": {"v": xg.model()["version"]}}})
        assert ids("2026-10-10T01:30") == []


def test_the_wording_file_is_complete():
    words = run.read_words()
    assert words["nav.games"] == "Games" and "{from}" in words["standings.note_goat_how"]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        for name in ("app.js", "index.html", "words.txt"):
            shutil.copy(run.SITE_SRC / name, src / name)
        text = (src / "words.txt").read_text()
        (src / "words.txt").write_text(text.replace("nav.games = Games", "nav.games Games"))
        try:
            run.read_words(src)
            raise AssertionError("a broken line was accepted")
        except RuntimeError as e:
            assert "nav.games" in str(e)


def doc_xg(out):
    return json.loads((out / "game" / "2026020056.json").read_text())["xg"]


def test_the_site_is_built_from_what_is_stored():
    table, games, boxes = small_season()
    coming = {**played(2026020120, "2026-10-12", "BOS", "UTA", None, None), "state": "upcoming", "tv": ["ESPN+"]}
    with tempfile.TemporaryDirectory() as tmp:
        state, out = Path(tmp) / "state", Path(tmp) / "out"
        run.write_json(state / "schedule.json", {"season": 2026, "games": {str(g["id"]): g for g in games + [coming]}})
        run.write_json(state / "standings.json", {"read": "2026-10-11T10:00:00+00:00", "teams": table})
        run.write_json(state / "box.json", boxes)
        run.write_json(state / "people.json", {"read": "2026-10-11", "players": {"21": {"first": "David", "last": "Pastrnak", "photo": "p.png"}}})
        shift_counts = {"v": lines.VERSION, "BOS": {"f": [[[21, 22], 400]], "d": [], "pp": [], "pk": [], "ppt": {}, "pkt": {}},
                        "UTA": {"f": [], "d": [], "pp": [], "pk": [], "ppt": {}, "pkt": {}}}
        run.write_json(state / "lines.json", {"2026020090": shift_counts})
        run.write_json(state / "careers.json", {"21": {"at": "2026-10-11", "g": 0, "seasons": [[2025, "Bruins", 82, 40, 50, 90, 5, 20, 10, 30, 6, 250, 1100]]}})
        res = run.build_site(state, out, dt.datetime(2026, 10, 11, 11, tzinfo=UTC))
        assert res["games"] == 3 and res["played"] == 2 and res["game_pages"] == 2 and res["with_odds"] == 1 and res["missing_box"] == []
        data = json.loads((out / "data.json").read_text())
        assert data["site"] == config.SITE_NAME and data["season"] == 2026 and [t["id"] for t in data["teams"]] == ["BOS", "UTA"]
        bos = data["teams"][0]
        assert bos["goat"] == 1 and data["teams"][1]["goat"] == 2 and bos["sos_rank"] in (1, 2) and "beat" not in bos
        assert bos["xg_pct"] == 66.7 and bos["g_pct"] == 66.7 and bos["hot"] == 0 and 0 < data["xg"]["scale"] < 1.01
        assert abs(data["xg"]["scale"] - (6 + config.XG_STEADY_GOALS) / (9 + config.XG_STEADY_GOALS)) < 1e-4
        log = json.loads((out / "player" / "21.json").read_text())
        assert len(log["games"]) == 2 and log["games"][0][0] == 2026020090 and doc_xg(out) == [1.5, 3.0]
        assert log["career"]["seasons"] == [[2025, "Bruins", 82, 40, 50, 90, 5, 20, 10, 30, 6, 250, 1100], [2026, "Bruins", 2, 2, 2, 4, 0, 0, 2, 2, 0, 4, 900]]
        assert log["career"]["total"][2:6] == [84, 42, 52, 94] and log["career"]["known"]
        assert json.loads((out / "player" / "11.json").read_text())["career"]["known"] is False
        races = json.loads((out / "awards.json").read_text())
        assert len(races["races"]) == 11 and races["through"] == "2026-10-10" and races["races"][1]["rows"][0]["id"] == 21
        assert list(json.loads((state / "awards.json").read_text())) == ["2026-10-11"]
        combos = json.loads((out / "lines.json").read_text())["teams"]
        assert set(combos) == {"BOS", "UTA"} and combos["BOS"]["game"] == {"id": 2026020090, "date": "2026-10-10", "opp": "UTA", "home": 1}
        assert [g["id"] for g in combos["BOS"]["g"]] == [24] and combos["BOS"]["g"][0]["role"] == "start"
        assert combos["BOS"]["d"] == [{"ids": [23], "toi": 0, "season": 0, "games": 0}] and combos["BOS"]["players"]["21"]["name"] == "David Pastrnak"
        assert sorted(combos["BOS"]["f"][0]["ids"]) == [21, 22]
        by = {g["id"]: g for g in data["games"]}
        assert by[2026020056]["box"] == 1 and 0 < by[2026020056]["p0"] < 1 and by[2026020056]["home"]["rank"] == 1
        # Utah, at home, has less of a chance than a home team level with its visitor
        assert 0 < by[2026020120]["p"] < odds.game_chance(0.0, 0.0) and by[2026020120]["tv"] == ["ESPN+"]
        doc = json.loads((out / "game" / "2026020056.json").read_text())
        assert doc["status"] == "F" and doc["goals"][0][5] == "David Pastrnak" and doc["goals"][0][6][0] == [22, "E. Lindholm"]
        assert doc["home"]["sk"][0][2] == "David Pastrnak" and doc["home"]["sk"][0][-1] == "p.png" and doc["stars"][0][:3] == [21, "BOS", "David Pastrnak"]
        assert len(json.loads((out / "players.json").read_text())["players"]) == 7
        page = (out / "index.html").read_text()
        assert "app.js?v=" in page and "styles.css?v=" in page and (out / ".nojekyll").exists() and not (out / "words.txt").exists()
        ratings = json.loads((state / "ratings.json").read_text())
        assert set(ratings) == {"2026"} and ratings["2026"]["BOS"] > ratings["2026"]["UTA"]


def test_the_page_script_has_no_syntax_errors():
    node = shutil.which("node")
    if node:
        done = subprocess.run([node, "--check", str(run.SITE_SRC / "app.js")], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
