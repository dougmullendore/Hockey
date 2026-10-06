"""Download whatever games we do not have yet and add them to the data folder.

The first run downloads every season in config.SEASONS (a few thousand
games). After that each run only picks up new games, plus a re-download of
the last few days to catch the league's stat corrections."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pandas as pd

from . import config, nhl_api, store
from .parse import is_final, parse_game, parse_shift_report, parse_shifts

CHUNK = 350  # games per checkpoint


def season_dates(log) -> dict:
    """{season: (first_day, last_day)} from the league's season list."""
    out = {}
    try:
        for s in nhl_api.get_json(nhl_api.seasons_url())["data"]:
            # preseasonStartdate is the earliest date that can hold games
            start = (s.get("startDate") or "")[:10]
            end = (s.get("endDate") or "")[:10]
            if start and end:
                out[int(s["id"])] = (start, end)
    except Exception as e:  # fall back to a generous guess
        log(f"season list unavailable ({e!r}); using default date ranges")
    for season in config.SEASONS:
        y = season // 10000
        out.setdefault(season, (f"{y}-09-25", f"{y + 1}-07-05"))
    return out


def walk_schedule(start: str, end: str, season: int, log) -> list[dict]:
    """Every regular-season and playoff game scheduled between two dates."""
    games, date, guard = {}, start, 0
    while date and date <= end and guard < 80:
        guard += 1
        week = nhl_api.get_json(nhl_api.schedule_url(date))
        for day in week.get("gameWeek", []):
            for g in day.get("games", []):
                if g.get("season") != season or g.get("gameType") not in config.GAME_TYPES:
                    continue
                home, away = g.get("homeTeam") or {}, g.get("awayTeam") or {}
                games[g["id"]] = {
                    "game_id": g["id"], "date": day.get("date"),
                    "game_type": g["gameType"], "state": g.get("gameState"),
                    "start_utc": g.get("startTimeUTC"),
                    "schedule_state": g.get("gameScheduleState"),
                    "home": home.get("abbrev"), "away": away.get("abbrev"),
                    "home_id": home.get("id"), "away_id": away.get("id"),
                }
        nxt = week.get("nextStartDate")
        if not nxt or nxt <= date:
            nxt = (dt.date.fromisoformat(date) + dt.timedelta(days=7)).isoformat()
        date = nxt
    return list(games.values())


def _merge(old: pd.DataFrame, table: str, new_rows, replaced_ids, sort_cols):
    new = store.frame(table, new_rows)
    if len(old):
        old = old[~old["game_id"].isin(list(replaced_ids))]
        new = pd.concat([old, new], ignore_index=True) if len(new) else old
    return new.sort_values(sort_cols, kind="stable").reset_index(drop=True)


def update_season(data: Path, season: int, dates, manifest: dict, today: dt.date,
                  deadline: float, log) -> dict:
    """Bring one season up to date. Returns a small summary dict."""
    key = str(season)
    info = manifest.setdefault(key, {})
    if info.get("complete"):
        return {"season": season, "skipped": "complete", "games": info.get("games", 0)}

    start, end = dates[season]
    if start > today.isoformat():
        return {"season": season, "skipped": "not started", "games": 0}

    # the whole season, including games not played yet (needed for projections)
    sched = walk_schedule(start, end, season, log)
    store.write_json(Path(data) / "schedule" / f"{season}.json",
                     sorted(sched, key=lambda g: (g["date"] or "", g["game_id"])), compact=True)
    final = [g for g in sched if is_final(g["state"])]
    pending = [g for g in sched if not is_final(g["state"]) and (g["date"] or "") <= today.isoformat()]

    games = store.read(data, "games", season)
    events = store.read(data, "events", season)
    rosters = store.read(data, "rosters", season)
    have = set(games["game_id"].dropna().astype(int))

    cutoff = (today - dt.timedelta(days=config.REFRESH_DAYS)).isoformat()
    need = sorted(g["game_id"] for g in final
                  if g["game_id"] not in have or (g["date"] or "") >= cutoff)
    log(f"season {season}: {len(sched)} scheduled, {len(final)} final, "
        f"{len(have)} stored, {len(need)} to download")

    failed, done, timed_out = [], 0, False
    for i in range(0, len(need), CHUNK):
        if time.time() > deadline:
            timed_out = True
            log(f"season {season}: out of time, stopping after {done} games")
            break
        chunk = need[i:i + CHUNK]
        g_rows, e_rows, r_rows, got = [], [], [], set()
        for gid, raw, err in nhl_api.get_many({g: nhl_api.pbp_url(g) for g in chunk}):
            if err is not None:
                failed.append(gid)
                log(f"  game {gid}: download failed: {err!r}")
                continue
            try:
                if not is_final(raw.get("gameState")) or not raw.get("plays"):
                    failed.append(gid)
                    continue
                g, e, r = parse_game(raw)
            except Exception as ex:
                failed.append(gid)
                log(f"  game {gid}: could not parse: {ex!r}")
                continue
            g_rows.append(g); e_rows.extend(e); r_rows.extend(r); got.add(gid)
        games = _merge(games, "games", g_rows, got, ["game_id"])
        events = _merge(events, "events", e_rows, got, ["game_id", "idx"])
        rosters = _merge(rosters, "rosters", r_rows, got, ["game_id", "team_id", "player_id"])
        store.write(data, "games", season, games)
        store.write(data, "events", season, events)
        store.write(data, "rosters", season, rosters)
        done += len(got)
        log(f"  season {season}: {done}/{len(need)} downloaded, {len(events):,} events stored")

    info["games"] = int(len(games))
    info["last_game_date"] = None if not len(games) else str(games["date"].max())
    season_over = today > dt.date.fromisoformat(end) + dt.timedelta(days=7)
    stored = set(games["game_id"].dropna().astype(int))
    info["complete"] = bool(
        season_over and not timed_out and not pending
        and all(g["game_id"] in stored for g in final) and len(games) > 0
    )
    return {"season": season, "games": int(len(games)), "downloaded": done,
            "failed": len(failed), "complete": info["complete"]}


MIN_SHIFTS = 200  # a real game has 600 or more


def _shifts_from_reports(data: Path, season: int, games, game_ids: list, log) -> dict:
    """Fallback: read shifts for these games from the printable reports."""
    if not game_ids:
        return {}
    rosters = store.read(data, "rosters", season)
    rosters = rosters[rosters["game_id"].isin(game_ids) & rosters["sweater"].notna()]
    home_of = dict(zip(games["game_id"].astype(int), games["home_id"].astype(int)))
    away_of = dict(zip(games["game_id"].astype(int), games["away_id"].astype(int)))
    urls = {}
    for g in game_ids:
        urls[(g, True)] = nhl_api.shift_report_url(g, season, True)
        urls[(g, False)] = nhl_api.shift_report_url(g, season, False)
    out = {g: [] for g in game_ids}
    for (g, is_home), html, err in nhl_api.get_many(urls, text=True):
        if err is not None:
            log(f"  shift report {g}: {err!r}")
            continue
        team = home_of[g] if is_home else away_of[g]
        r = rosters[(rosters["game_id"] == g) & (rosters["team_id"] == team)]
        by_sweater = dict(zip(r["sweater"].astype(int), r["player_id"].astype(int)))
        out[g].extend(parse_shift_report(html, g, team, by_sweater))
    return out


def update_shifts(data: Path, season: int, manifest: dict, today: dt.date,
                  deadline: float, log) -> dict:
    """Download shift charts for stored games that do not have them yet.

    The league sometimes publishes a game's shift chart late, or not at all.
    Games that come back empty are remembered and retried for two weeks."""
    info = manifest.setdefault(str(season), {})
    if info.get("shifts_done") and info.get("complete") and not info.get("shifts_empty"):
        return {"season": season, "shifts": "complete"}
    games = store.read(data, "games", season)
    if not len(games):
        return {"season": season, "shifts": "no games"}
    shifts = store.read(data, "shifts", season)
    have = set(shifts["game_id"].dropna().astype(int).unique())
    empty = set(info.get("shifts_empty", []))
    date_of = dict(zip(games["game_id"].astype(int), games["date"].astype(str)))
    teams_of = {int(g.game_id): {int(g.home_id), int(g.away_id)} for g in games.itertuples(index=False)}
    recheck = (today - dt.timedelta(days=config.REFRESH_DAYS)).isoformat()
    retry = (today - dt.timedelta(days=14)).isoformat()
    tried = set(info.get("shifts_report_tried", []))
    need = sorted(g for g, d in date_of.items()
                  if (g not in have and (g not in empty or d >= retry or g not in tried))
                  or d >= recheck)
    done, timed_out, from_reports = 0, False, 0
    for i in range(0, len(need), CHUNK):
        if time.time() > deadline:
            timed_out = True
            log(f"season {season}: out of time for shifts after {done} games")
            break
        chunk = need[i:i + CHUNK]
        rows, got, blank = [], set(), []
        for gid, raw, err in nhl_api.get_many({g: nhl_api.shifts_url(g) for g in chunk}):
            if err is not None:
                log(f"  shifts {gid}: download failed: {err!r}")
                continue
            # the feed occasionally mixes in shifts from a different game
            parsed = [r for r in parse_shifts(raw, gid) if r[1] in teams_of[gid]]
            if len(parsed) < MIN_SHIFTS:
                blank.append(gid)
                continue
            rows.extend(parsed); got.add(gid)
        # the feed is empty for some games; the printable reports are not
        for gid, parsed in _shifts_from_reports(data, season, games, blank, log).items():
            if len(parsed) < MIN_SHIFTS:
                empty.add(gid)
                continue
            rows.extend(parsed); got.add(gid); from_reports += 1
        empty -= got
        shifts = _merge(shifts, "shifts", rows, got,
                        ["game_id", "period", "team_id", "player_id", "start"])
        store.write(data, "shifts", season, shifts)
        done += len(got)
        log(f"  season {season}: shifts for {done}/{len(need)} games, {len(shifts):,} shifts stored")
    have = set(shifts["game_id"].dropna().astype(int).unique())
    missing = sorted(g for g in date_of if g not in have)
    info["shifts_empty"] = sorted(g for g in empty if g in date_of and g not in have)
    info["shifts_report_tried"] = info["shifts_empty"]
    info["shift_games"] = len(have)
    info["shifts_done"] = bool(not timed_out and all(g in empty for g in missing))
    return {"season": season, "shift_games": len(have), "downloaded": done,
            "from_reports": from_reports, "missing": len(missing)}


def update_official(data: Path, manifest: dict, log) -> None:
    """League-published season totals (ice time, games played, wins ...)."""
    for season in config.SEASONS:
        info = manifest.get(str(season), {})
        if not info.get("games"):
            continue
        for gt in config.GAME_TYPES:
            for kind in ("goalie", "skater"):
                path = Path(data) / "official" / f"{kind}_{season}_{gt}.json"
                if path.exists() and info.get("complete"):
                    continue
                try:
                    rows = nhl_api.get_json(nhl_api.summary_url(kind, season, gt)).get("data", [])
                    store.write_json(path, rows, compact=True)
                except Exception as e:
                    log(f"official {kind} totals {season}/{gt} unavailable: {e!r}")


def update_standings(data: Path, log) -> None:
    """Which division and conference each team is in, with the official record."""
    try:
        raw = nhl_api.get_json(f"{config.API_WEB}/standings/now")
    except Exception as e:
        log(f"standings unavailable: {e!r}")
        return
    rows = []
    for s in raw.get("standings", []):
        rows.append({
            "team": (s.get("teamAbbrev") or {}).get("default"), "season": s.get("seasonId"),
            "conference": s.get("conferenceName"), "division": s.get("divisionName"),
            "gp": s.get("gamesPlayed"), "w": s.get("wins"), "l": s.get("losses"), "otl": s.get("otLosses"),
            "pts": s.get("points"), "rw": s.get("regulationWins"), "row": s.get("regulationPlusOtWins"),
        })
    if rows:
        store.write_json(Path(data) / "official" / "standings.json", rows, compact=True)


def update_all(data: Path, log, max_minutes: float = 150) -> list[dict]:
    data = Path(data)
    manifest = store.read_json(data / "manifest.json", {}) or {}
    today = dt.datetime.now(dt.timezone.utc).date()
    deadline = time.time() + max_minutes * 60
    dates = season_dates(log)
    results = []
    for season in config.SEASONS:
        try:
            results.append(update_season(data, season, dates, manifest, today, deadline, log))
        except Exception as e:
            log(f"season {season}: update failed: {e!r}")
            results.append({"season": season, "error": repr(e)})
        try:
            results.append(update_shifts(data, season, manifest, today, deadline, log))
        except Exception as e:
            log(f"season {season}: shift update failed: {e!r}")
            results.append({"season": season, "shift_error": repr(e)})
        store.write_json(data / "manifest.json", manifest)
    update_official(data, manifest, log)
    update_standings(data, log)
    return results
