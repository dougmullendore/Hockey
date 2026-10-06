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
from .parse import is_final, parse_game

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
                games[g["id"]] = {
                    "game_id": g["id"], "date": day.get("date"),
                    "game_type": g["gameType"], "state": g.get("gameState"),
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

    sched = walk_schedule(start, min(end, today.isoformat()), season, log)
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
        store.write_json(data / "manifest.json", manifest)
    update_official(data, manifest, log)
    return results
