"""The scheduled job. It keeps four things up to date and builds the page:

  1. the season's schedule: every game, played or still to come, with its
     score, its start time and where to watch it
  2. the league standings
  3. the box score of every game played
  4. every player's details (full name, photo, height, weight, birthplace)

Usage:  python -m pipeline.run <state_dir> <site_output_dir>

<state_dir> is the repository's `state` branch:
  schedule.json    the season's games
  standings.json   the league table as of the last look
  box.json         the box score of every game played this season
  people.json      players' details, from the teams' rosters
  careers.json     players' earlier NHL seasons, from each player's own page
  lines.json       who was on the ice together in each game, from the shift charts
  ratings.json     every team's rating, this season and last (behind the odds)
  playoffs.json    the playoff odds as last worked out, and each day's playoff chances
  status.json      what happened on the last run
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

from . import careers, config, goat, lines, nhl, odds, players, playoffs, teams, web, xg

SITE_SRC = Path(__file__).resolve().parents[1] / "site"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path: Path, obj, indent=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent, separators=None if indent else (",", ":"), allow_nan=False))


def in_order(games) -> list[dict]:
    return sorted(games, key=lambda g: (g["date"], g["start"] or 0, g["id"]))


# ----------------------------------------------------------------- stages --
def update_schedule(state: Path, season: int, only: list[str] | None = None) -> dict:
    """Read the season's schedule a week at a time. `only` (dates) reads just
    the weeks starting on those dates, on a game-night run."""
    stored = read_json(state / "schedule.json", {})
    if stored.get("season") != season:
        stored = {"season": season, "games": {}}
    weeks = only or nhl.season_weeks(season)
    found, failed = {}, []
    for date, games, err in nhl.fetch_schedule(weeks):
        if err is not None:
            failed.append(date)
            continue
        for g in games:
            if nhl.season_for(dt.date.fromisoformat(g["date"])) == season:
                found[str(g["id"])] = g
    if len(failed) == len(weeks):
        raise RuntimeError("the schedule could not be reached for any week")
    if only or failed:
        stored["games"].update(found)          # part of the season was read: keep the rest as it was
    elif found:
        stored["games"] = found                # all of it was read: a game no longer listed is dropped
    write_json(state / "schedule.json", stored)
    n = len(stored["games"])
    log(f"schedule: {len(weeks) - len(failed)} of {len(weeks)} weeks read, {n:,} games in season {season}-{(season + 1) % 100:02d}"
        + (f"; kept the old copy of {len(failed)} weeks" if failed else ""))
    return {"season": season, "weeks": len(weeks), "weeks_failed": len(failed), "games": n,
            "final": sum(1 for g in stored["games"].values() if g["state"] == "final")}


def update_standings(state: Path, now: dt.datetime) -> dict:
    table = nhl.fetch_standings()
    if len(table) < 30:
        raise RuntimeError(f"the standings did not read cleanly: {len(table)} teams")
    write_json(state / "standings.json", {"read": now.isoformat(timespec="seconds"), "teams": table}, indent=0)
    log(f"standings: {len(table)} teams; first is {table[0]['name']} ({table[0]['pts']} points in {table[0]['gp']} games)")
    return {"teams": len(table), "first": table[0]["id"]}


def season_games(state: Path) -> dict:
    """The stored schedule and standings, joined: every game in order, each
    side carrying its place in the standings."""
    sched = read_json(state / "schedule.json", {})
    table = read_json(state / "standings.json", {}).get("teams") or []
    if not sched.get("games") or not table:
        raise RuntimeError("nothing to build yet: " + ("no schedule" if not sched.get("games") else "no standings"))
    rank = {t["id"]: t["rank"] for t in table}
    games = in_order(sched["games"].values())
    for g in games:
        for s in (g["away"], g["home"]):
            s["rank"] = rank.get(s["id"])
    return {"season": sched["season"], "games": games, "teams": table}


def complete(have: dict | None) -> bool:
    """A stored game with everything in: the final box score, its summary, and
    the play-by-play read with the expected-goals model in use today."""
    have = have or {}
    return have.get("status") == "F" and bool(have.get("full")) and (have.get("adv") or {}).get("v") == xg.model()["version"]


def boxes_wanted(games: list[dict], stored: dict, today: dt.date) -> list[dict]:
    """Finished games not completely stored yet, and games from the last few
    days, whose numbers the league may have corrected."""
    recent = (today - dt.timedelta(days=config.BOX_REFRESH_DAYS)).isoformat()
    return [g for g in games if g["state"] == "final" and (not complete(stored.get(str(g["id"]))) or g["date"] >= recent)]


def fetch_boxes(stored: dict, games: list[dict]) -> dict:
    got, failed = 0, []
    for g in games:
        try:
            box = nhl.fetch_box(g["id"])
        except Exception as e:
            failed.append(f"{g['id']}: {e!r}"[:120])
            continue
        if not box["away"]["sk"] and not box["home"]["sk"]:
            continue                            # nobody has played yet
        stored[str(g["id"])] = box
        got += 1
    return {"asked": len(games), "read": got, "failed": failed[:10], "failed_count": len(failed)}


def update_boxes(state: Path, now: dt.datetime) -> dict:
    sel = season_games(state)
    stored = read_json(state / "box.json", {})
    keep = {str(g["id"]) for g in sel["games"]}
    stored = {k: v for k, v in stored.items() if k in keep}          # earlier seasons' box scores are not used again
    todo = boxes_wanted(sel["games"], stored, now.date())
    res = fetch_boxes(stored, todo)
    write_json(state / "box.json", stored)
    log(f"box scores: {res['read']} of {res['asked']} read; {len(stored):,} stored"
        + (f"; {res['failed_count']} could not be read, e.g. {res['failed'][:2]}" if res["failed_count"] else ""))
    if res["asked"] and res["failed_count"] == res["asked"]:
        raise RuntimeError("no box score could be read: " + "; ".join(res["failed"])[:300])
    return res | {"stored": len(stored)}


def update_people(state: Path, now: dt.datetime) -> dict:
    """Players' full names, photos and details: each team's roster, and for a
    player who has played but is on no roster today (sent down, say), his own page."""
    sel = season_games(state)
    stored = read_json(state / "people.json", {})
    people, tried = stored.get("players") or {}, stored.get("tried") or {}
    res = {"rosters_read": 0, "looked_up": 0}
    today = now.date().isoformat()
    age = (now.date() - dt.date.fromisoformat(stored["read"])).days if stored.get("read") else 10**6
    if age >= config.ROSTER_REFRESH_DAYS:
        failed = []
        for path, doc, err in web.get_many([f"roster/{t['id']}/current" for t in sel["teams"]], tries=2):
            team = path.split("/")[1]
            if err is not None:
                failed.append(team)
                continue
            for p in nhl.parse_roster(doc, team):
                people[str(p.pop("id"))] = p
            res["rosters_read"] += 1
        if failed:
            log(f"people: could not read the roster of {failed}")
        if res["rosters_read"]:
            stored["read"] = today
    boxes = read_json(state / "box.json", {})
    played = {str(row[0]) for b in boxes.values() for side in ("away", "home") for kind in ("sk", "g")
              for row in (b.get(side) or {}).get(kind) or []}
    missing = sorted(pid for pid in played if pid not in people and tried.get(pid) != today)[:60]
    for path, doc, err in web.get_many([f"player/{pid}/landing" for pid in missing], tries=2):
        pid = path.split("/")[1]
        tried[pid] = today
        person = nhl.parse_person(doc, None) if err is None else None
        if person:
            person.pop("id")
            people[pid] = person
            res["looked_up"] += 1
    write_json(state / "people.json", {"read": stored.get("read"), "players": people,
                                       "tried": {k: v for k, v in tried.items() if k not in people}}, indent=0)
    res |= {"players": len(people), "played": len(played), "without_details": len(played - set(people))}
    log(f"people: {res['rosters_read']} rosters read, {res['looked_up']} players looked up one by one; "
        f"details for {len(played & set(people))} of the {len(played)} who have played")
    return res


def update_careers(state: Path, now: dt.datetime) -> dict:
    """Earlier seasons, career playoff totals and draft details of everyone
    who has played this season, from each player's own page in the feed."""
    stored = read_json(state / "careers.json", {})
    boxes = read_json(state / "box.json", {})
    played = sorted({str(row[0]) for b in boxes.values() for side in ("away", "home") for kind in ("sk", "g")
                     for row in (b.get(side) or {}).get(kind) or []})
    today = now.date()

    def stale(pid):
        have = stored.get(pid)
        return not have or (today - dt.date.fromisoformat(have["at"])).days >= config.CAREER_REFRESH_DAYS

    todo = [pid for pid in played if stale(pid)][:config.CAREER_MAX_PER_RUN]
    failed = 0
    for path, doc, err in web.get_many([f"player/{pid}/landing" for pid in todo], tries=2):
        if err is not None:
            failed += 1
            continue
        stored[path.split("/")[1]] = {"at": today.isoformat(), **careers.parse(doc)}
    write_json(state / "careers.json", stored)
    have = sum(1 for pid in played if pid in stored)
    log(f"careers: {len(todo) - failed} of {len(todo)} players read; earlier seasons for {have} of the {len(played)} who have played")
    if todo and failed == len(todo):
        raise RuntimeError("no player's career could be read")
    return {"asked": len(todo), "failed": failed, "have": have, "played": len(played)}


def update_lines(state: Path, now: dt.datetime) -> dict:
    """Read the shift chart of every finished game not yet counted, and keep
    who was on the ice together (see pipeline/lines.py)."""
    sel = season_games(state)
    boxes = read_json(state / "box.json", {})
    stored = read_json(state / "lines.json", {})
    keep = {str(g["id"]) for g in sel["games"]}
    stored = {k: v for k, v in stored.items() if k in keep and v.get("v") == lines.VERSION}
    todo = [g for g in sel["games"] if g["state"] == "final" and str(g["id"]) not in stored
            and (boxes.get(str(g["id"])) or {}).get("status") == "F"]
    by_url = {config.SHIFTS_URL.format(game=g["id"]): g for g in todo}
    read = empty = failed = 0
    old = (now.date() - dt.timedelta(days=config.SHIFTS_GIVE_UP_DAYS)).isoformat()
    for url, doc, err in web.get_urls(list(by_url), tries=2):
        g = by_url[url]
        if err is not None:
            failed += 1
            continue
        box = boxes[str(g["id"])]
        pos = {row[0]: row[3] for side in ("away", "home") for row in box[side]["sk"]}
        counted = lines.count(lines.parse_shifts(doc), pos)
        if set(counted) == {g["away"]["id"], g["home"]["id"]}:
            stored[str(g["id"])] = {"v": lines.VERSION, **counted}
            read += 1
        else:
            empty += 1                      # the league has not put the shifts up yet; some never arrive
            if g["date"] < old:
                stored[str(g["id"])] = {"v": lines.VERSION, "none": 1}
    write_json(state / "lines.json", stored)
    log(f"lines: {read} of {len(todo)} shift charts read" + (f", {empty} empty" if empty else "") + (f", {failed} could not be read" if failed else "")
        + f"; {sum(1 for v in stored.values() if not v.get('none')):,} games counted")
    if todo and failed == len(todo):
        raise RuntimeError("no shift chart could be read")
    return {"asked": len(todo), "read": read, "empty": empty, "failed": failed, "stored": len(stored)}


def team_lines(games: list[dict], boxes: dict, counted: dict, people: dict, table: list[dict]) -> dict:
    """The Lines page's data: each team's forward lines and defense pairs from
    its latest game with a shift chart, its special-teams units from its last
    few, the goalies, and the details of everyone named."""
    out = {}
    for t in table:
        team = t["id"]
        mine = [g for g in games if g["state"] == "final" and team in (g["away"]["id"], g["home"]["id"])
                and team in (counted.get(str(g["id"])) or {}) and (boxes.get(str(g["id"])) or {}).get("status") == "F"]
        if not mine:
            continue
        mine.sort(key=lambda g: (g["date"], g["start"] or 0, g["id"]), reverse=True)
        last = mine[0]
        side = "home" if last["home"]["id"] == team else "away"
        box = boxes[str(last["id"])]
        faced = (box.get("adv") or {}).get("sk") or {}
        info = {}

        def note(pid, short, num, pos):
            who = people.get(str(pid)) or {}
            info[str(pid)] = {"name": (who.get("first", "") + " " + who.get("last", "")).strip() or short,
                              "num": num if num is not None else who.get("num"), "pos": pos}
            if who.get("photo") and config.SHOW_PHOTOS:
                info[str(pid)]["photo"] = who["photo"]

        dressed = []
        for row in box[side]["sk"]:
            r = dict(zip(nhl.SK, row))
            dressed.append({"id": r["id"], "pos": r["pos"], "toi": r["toi"], "fo": (faced.get(str(r["id"])) or [0] * 5)[4],
                            "sh": (people.get(str(r["id"])) or {}).get("sh")})
        per_game = [counted[str(g["id"])][team] for g in mine]
        found = lines.team_lines(per_game[0], per_game[:lines.SPECIAL_GAMES], per_game, dressed)
        # everyone in a special-teams unit, forwards before defensemen
        seen = {}
        for g in mine[:lines.SPECIAL_GAMES]:
            for row in boxes[str(g["id"])]["home" if g["home"]["id"] == team else "away"]["sk"]:
                seen.setdefault(row[0], row)
        for unit in found["pp"] + found["pk"]:
            order = list(unit["ids"])
            unit["ids"] = sorted(order, key=lambda p: ((seen.get(p) or [0, 0, "", "D"])[3] == "D", order.index(p)))
        for row in list(seen.values()):
            note(row[0], row[2], row[1], row[3])
        goalies = []
        for row in sorted(box[side]["g"], key=lambda r: -r[7]):
            note(row[0], row[2], row[1], "G")
            goalies.append({"id": row[0], "role": "start" if row[7] else "relief"})
        for pid, who in sorted(people.items(), key=lambda kv: kv[1].get("last", "")):
            if who.get("team") == team and who.get("pos") == "G" and pid not in info:
                note(int(pid), "", who.get("num"), "G")
                goalies.append({"id": int(pid), "role": "roster"})
        out[team] = {"game": {"id": last["id"], "date": last["date"], "opp": last["away" if side == "home" else "home"]["id"], "home": int(side == "home")},
                     **found, "g": goalies, "players": info, "games": len(mine), "special_games": min(len(mine), lines.SPECIAL_GAMES)}
    return out


def live_now(state: Path, now: dt.datetime) -> list[dict]:
    """The games to look at on a game-night run: those that started in the last
    five hours, or start in the next twenty minutes, and are not known to be
    over with their box score in. Empty when there is nothing to do."""
    sched = read_json(state / "schedule.json", {})
    boxes = read_json(state / "box.json", {})
    t, out = now.timestamp(), []
    for g in (sched.get("games") or {}).values():
        if not g.get("start") or not (t - 5 * 3600 <= g["start"] <= t + 20 * 60) or g["state"] == "other":
            continue
        if not (g["state"] == "final" and complete(boxes.get(str(g["id"])))):
            out.append(g)
    return out


def update_live_boxes(state: Path, now: dt.datetime) -> dict:
    """Box scores of games under way, or finished in the last five hours
    without a final box score yet."""
    sel = season_games(state)
    stored = read_json(state / "box.json", {})
    t = now.timestamp()
    todo = [g for g in sel["games"] if g.get("start") and t - 5 * 3600 <= g["start"] <= t and g["state"] in ("live", "final")
            and not (g["state"] == "final" and complete(stored.get(str(g["id"]))))]
    res = fetch_boxes(stored, todo)
    write_json(state / "box.json", stored)
    log(f"box scores now: {res['read']} of {res['asked']} games under way or just finished")
    return res


# ------------------------------------------------------------ the page --
def game_files(out: Path, games: list[dict], boxes: dict, people: dict) -> int:
    """One small file per game with a box score, for the game's page:
    game/<id>.json with both teams' players, the score by period, the goals,
    the three stars and the team totals."""
    def full(pid, short):
        who = people.get(str(pid)) or {}
        return (who.get("first", "") + " " + who.get("last", "")).strip() or short

    def photo(pid):
        return (people.get(str(pid)) or {}).get("photo") if config.SHOW_PHOTOS else None

    (out / "game").mkdir(exist_ok=True)
    n = 0
    for g in games:
        b = boxes.get(str(g["id"]))
        if not b or not (b["away"]["sk"] or b["home"]["sk"]):
            continue
        short = {}
        doc = {"id": g["id"], "status": b.get("status", ""), "line": b.get("line") or [], "tstats": b.get("tstats") or {},
               "xg": (b.get("adv") or {}).get("xg")}
        for side in ("away", "home"):
            sk, gk = [], []
            for row in b[side]["sk"]:
                r = dict(zip(nhl.SK, row))
                short[r["id"]] = r["name"]
                sk.append([r["id"], r["num"], full(r["id"], r["name"]), r["pos"], r["g"], r["a"], r["pm"], r["sog"], r["hits"],
                           r["blk"], r["pim"], r["toi"], r["shifts"], r["gv"], r["tk"], r["fo"], r["ppg"], photo(r["id"])])
            for row in b[side]["g"]:
                r = dict(zip(nhl.GK, row))
                short[r["id"]] = r["name"]
                gk.append([r["id"], r["num"], full(r["id"], r["name"]), r["sa"], r["sv"], r["ga"], r["toi"], r["start"],
                           r["dec"], photo(r["id"])])
            doc[side] = {"sk": sk, "g": gk, "sog": b[side].get("sog")}
        doc["goals"] = [[x[0], x[1], x[2], x[3], x[4], full(x[4], x[10] if len(x) > 10 else short.get(x[4], "")),
                         [[a, full(a, short.get(a, ""))] for a in x[5]], x[6], x[7], x[8], x[9]] for x in b.get("goals") or []]
        doc["stars"] = [[s[0], s[1], full(s[0], s[2]), photo(s[0])] for s in b.get("stars") or []]
        write_json(out / "game" / f"{g['id']}.json", doc)
        g["box"] = 1
        n += 1
    return n


def read_words(src: Path = SITE_SRC) -> dict:
    """The site's wording from site/words.txt ("name = words" lines). Fails,
    before anything is published, if a line is broken or a name the pages use
    is missing, so a slip in the file leaves yesterday's site up."""
    words, bad = {}, []
    for n, line in enumerate((src / "words.txt").read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, text = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", key):
            bad.append(f"line {n}: {line.strip()[:60]!r}")
            continue
        words[key] = text.strip()
    used = set(re.findall(r'W\("([a-z0-9_.]+)"', (src / "app.js").read_text()))
    used |= set(re.findall(r'data-w="([a-z0-9_.]+)"', (src / "index.html").read_text()))
    missing = sorted(used - set(words))
    if bad or missing:
        raise RuntimeError("site/words.txt needs fixing; the site was not updated. "
                           + (f"Lines not in the form 'name = words': {bad}. " if bad else "")
                           + (f"Missing names (put these lines back): {missing}." if missing else ""))
    return words


def build_site(state: Path, out: Path, now: dt.datetime) -> dict:
    sel = season_games(state)
    season, games, table = sel["season"], sel["games"], sel["teams"]
    names = {t["id"]: t for t in table}
    counted = [g for g in games if g["type"] in config.STATS_GAME_TYPES]

    # Odds: rate every team from this season's results, starting from where
    # each finished last season, and give each coming game a chance.
    kept = read_json(state / "ratings.json", {})
    start = kept.get(str(season - 1))
    if start is None:
        first = odds.seed()
        start = first.get("ratings", {}) if first.get("season", season) < season else {}
    rating, pregame = odds.rate(games, start)
    kept = {k: v for k, v in kept.items() if int(k) >= season - 1}
    kept[str(season)] = {t: round(v, 4) for t, v in rating.items()}
    write_json(state / "ratings.json", kept)
    for g in games:
        h, a = g["home"]["id"], g["away"]["id"]
        if g["state"] in ("upcoming", "live") and h in rating and a in rating:
            g["p"] = round(odds.game_chance(rating[h], rating[a], bool(g.get("neutral"))), 3)   # the home team's chance
        elif g["id"] in pregame:
            g["p0"] = round(pregame[g["id"]], 3)      # what the home team's chance was before a finished game

    # Playoff odds: the rest of the season and the playoffs played out many times
    # (see pipeline/playoffs.py). Worked out again only when a result, the
    # schedule or a rating has changed.
    today = now.date().isoformat()
    po = playoffs.update(read_json(state / "playoffs.json", {}), table, games, rating, today)
    write_json(state / "playoffs.json", po)
    before = playoffs.week_ago(po["days"], today)
    for t in table:
        t["po"] = dict(po["odds"].get(t["id"]) or {})
        if t["id"] in before:
            t["po"]["was"] = before[t["id"]]

    # Expected goals, from the play-by-play kept with each box score: each
    # team's total for and against, and the scale that makes the league's
    # expected goals equal its goals (see XG_STEADY_GOALS in config.py).
    boxes = read_json(state / "box.json", {})
    chances, goals = {t["id"]: [0.0, 0.0] for t in table}, 0
    for g in counted:
        box = boxes.get(str(g["id"])) or {}
        pair = (box.get("adv") or {}).get("xg")
        if g["state"] != "final" or box.get("status") != "F" or not pair:
            continue
        goals += g["away"]["score"] + g["home"]["score"] - (1 if g.get("end") == "SO" else 0)
        for side, mine, theirs in (("away", pair[0], pair[1]), ("home", pair[1], pair[0])):
            if g[side]["id"] in chances:
                chances[g[side]["id"]][0] += mine
                chances[g[side]["id"]][1] += theirs
    expected = sum(v[0] for v in chances.values())
    xg_scale = (goals + config.XG_STEADY_GOALS) / (expected + config.XG_STEADY_GOALS)

    # The GOAT ranking: record, strength of schedule, expected-goal share, goal
    # share and a boost for a hot streak (see pipeline/goat.py). Regular season only.
    ranking = goat.rank(counted, rating, table, chances)
    spot = {t: i + 1 for i, t in enumerate(ranking["order"])}
    by_schedule = sorted(ranking["sos"], key=lambda t: -ranking["sos"][t])
    for t in table:
        tid = t["id"]
        t["goat"] = spot[tid]
        t["goat_score"] = round(ranking["score"][tid], 3)
        t["sos_rank"] = by_schedule.index(tid) + 1
        t["xg_pct"] = round(100 * ranking["xg_pct"][tid], 1) if sum(chances[tid]) else None
        t["g_pct"] = round(100 * ranking["goal_pct"][tid], 1)
        t["hot"] = ranking["streak"][tid] if ranking["boost"][tid] else 0
    goat_info = {"weights": config.GOAT_WEIGHTS, "hot_from": config.GOAT_HOT_FROM, "hot_step": config.GOAT_HOT_STEP,
                 "hot_max": config.GOAT_HOT_MAX}

    words = read_words()                       # checked before anything is written
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out, ignore=shutil.ignore_patterns("words.txt"))
    # Give the script and stylesheet an address that changes whenever they do.
    # Otherwise a browser can pair a new page with the copy of the old script
    # it kept, and the page breaks until that copy expires.
    page = (out / "index.html").read_text()
    for name in ("app.js", "styles.css"):
        stamp = hashlib.sha256((out / name).read_bytes()).hexdigest()[:10]
        assert f'"{name}"' in page, f"index.html no longer refers to {name}"
        page = page.replace(f'"{name}"', f'"{name}?v={stamp}"')
    (out / "index.html").write_text(page)

    people = read_json(state / "people.json", {}).get("players") or {}
    if not config.SHOW_PHOTOS:
        people = {k: {x: y for x, y in v.items() if x != "photo"} for k, v in people.items()}
    rated = players.compute(table, counted, boxes, people, xg_scale)
    rated["through"] = max((g["date"] for g in counted if g["state"] == "final"), default=None)
    # One small file per player for his card: his game-by-game lines and his career.
    (out / "player").mkdir(exist_ok=True)
    past = read_json(state / "careers.json", {})
    logs = rated.pop("logs")
    for p in rated["players"]:
        write_json(out / "player" / f"{p['id']}.json", {
            "id": p["id"], "games": logs.get(p["id"]) or [],
            "career": careers.build(past.get(str(p["id"])), p, names[p["team_id"]]["short"], season)})
    with_box = game_files(out, games, boxes, people)
    write_json(out / "data.json", {
        "site": config.SITE_NAME, "league": config.LEAGUE, "updated": now.isoformat(timespec="seconds"), "season": season,
        "standings_read": read_json(state / "standings.json", {}).get("read"),
        "teams": table, "goat": goat_info, "games": games, "words": words,
        "game_page": config.GAME_PAGE, "player_page": config.PLAYER_PAGE, "logo": config.LOGO_URL,
        "live_feed": config.ESPN_SCOREBOARD, "live_seconds": config.LIVE_SECONDS, "espn_abbr": config.ESPN_ABBR,
        "odds_tested": config.ODDS_TESTED, "playoffs": {"sims": config.PLAYOFF_SIMS, "tested": config.PLAYOFF_TESTED}, "xg": {"scale": round(xg_scale, 4), "tested": xg.model().get("tested")}})
    write_json(out / "players.json", rated)
    write_json(out / "teams.json", teams.compute(table, counted, boxes, rating, xg_scale))
    combos = team_lines(games, boxes, read_json(state / "lines.json", {}), people, table)
    write_json(out / "lines.json", {"teams": combos})
    (out / ".nojekyll").write_text("")
    done = sum(1 for g in games if g["state"] == "final")
    log(f"site: {len(games):,} games ({done:,} played, {with_box:,} with a box score), {len(table)} teams, "
        f"{len(rated['players']):,} players of whom {rated['regulars']} skaters and "
        f"{rated['pos_regulars'].get('G', 0)} goalies are ranked")
    return {"games": len(games), "played": done, "game_pages": with_box, "teams": len(table),
            "players": len(rated["players"]), "regulars": rated["regulars"],
            "with_odds": sum(1 for g in games if "p" in g), "xg_scale": round(xg_scale, 4),
            "with_play_by_play": sum(1 for g in games if (boxes.get(str(g["id"])) or {}).get("adv")), "with_channel": sum(1 for g in games if g["state"] != "final" and g.get("tv")),
            "teams_with_lines": len(combos),
            "missing_box": [g["id"] for g in games if g["state"] == "final" and not g.get("box")][:20]}


def main(state_dir: str, out_dir: str) -> int:
    state, out = Path(state_dir), Path(out_dir)
    state.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    season = nhl.season_for(now.date())
    status = {"started_utc": now.isoformat(timespec="seconds"),
              "commit": os.environ.get("GITHUB_SHA", "local")[:12], "stages": {}}
    offline = os.environ.get("SKIP_FETCH") == "1"       # rebuild the page from what is stored
    live = os.environ.get("RUN_MODE") == "live" and not offline

    def stage(name, fn):
        try:
            status["stages"][name] = {"ok": True, "result": fn()}
        except Exception as e:
            log(f"STAGE {name} FAILED: {e!r}")
            traceback.print_exc()
            status["stages"][name] = {"ok": False, "error": repr(e)}
        write_json(state / "status.json", status, indent=1)

    if live:
        # a game-night run: only the games under way or just finished
        todo = live_now(state, now)
        if not todo:
            log("game-night run: no game is being played right now; nothing to do")
            return 0
        stage("scores now", lambda: update_schedule(state, season, sorted({g["date"] for g in todo})))
        stage("box scores now", lambda: update_live_boxes(state, now))
        stage("standings", lambda: update_standings(state, now))
    elif not offline:
        # a failed look at any of these leaves the stored copy in use
        stage("schedule", lambda: update_schedule(state, season))
        stage("standings", lambda: update_standings(state, now))
        stage("box scores", lambda: update_boxes(state, now))
        stage("people", lambda: update_people(state, now))
        stage("careers", lambda: update_careers(state, now))
        stage("lines", lambda: update_lines(state, now))
    stage("site", lambda: build_site(state, out, now))
    status["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    status["ok"] = all(s["ok"] for s in status["stages"].values())
    write_json(state / "status.json", status, indent=1)
    log(("game-night run" if live else "run") + " finished: " + ("OK" if status["ok"] else "WITH ERRORS"))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
