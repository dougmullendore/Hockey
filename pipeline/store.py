"""Reading and writing the data folder (the repository's `data` branch).

Layout:
  games/<season>.csv.gz     one row per finished game
  events/<season>.csv.gz    every play-by-play event
  rosters/<season>.csv.gz   who dressed for each game
  shifts/<season>.csv.gz    every shift: who was on the ice, and when
  official/<kind>_<season>_<type>.json   league season totals (TOI, GP ...)
  model/                    the trained expected-goals model and its report
  manifest.json             bookkeeping
  status.json               result of the most recent run
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .parse import EVENT_COLS, GAME_COLS, ROSTER_COLS, SHIFT_COLS

INT_COLS = {
    "games": ["game_id", "season", "game_type", "home_id", "away_id",
              "home_score", "away_score", "periods"],
    "events": ["game_id", "idx", "event_id", "period", "period_seconds",
               "game_seconds", "team_id", "is_home", "x", "y", "x_adj", "y_adj",
               "player1_id", "player2_id", "player3_id", "goalie_id",
               "home_skaters", "away_skaters", "home_goalie_in",
               "away_goalie_in", "home_score", "away_score", "penalty_minutes"],
    "rosters": ["game_id", "team_id", "player_id", "sweater"],
    "shifts": ["game_id", "team_id", "player_id", "period", "start", "end"],
}
STR_COLS = {
    "games": ["date", "start_utc", "state", "home_abbrev", "away_abbrev", "last_period_type"],
    "events": ["period_type", "type", "zone", "shot_type", "reason", "situation",
               "penalty_type", "desc_key"],
    "rosters": ["first_name", "last_name", "position"],
    "shifts": [],
}
COLS = {"games": GAME_COLS, "events": EVENT_COLS, "rosters": ROSTER_COLS,
        "shifts": SHIFT_COLS}


def _path(data: Path, table: str, season: int) -> Path:
    return Path(data) / table / f"{season}.csv.gz"


def frame(table: str, rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLS[table])
    return _types(table, df)


def _types(table: str, df: pd.DataFrame) -> pd.DataFrame:
    for c in INT_COLS[table]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in STR_COLS[table]:
        df[c] = df[c].astype("string")
    return df


def read(data: Path, table: str, season: int) -> pd.DataFrame:
    p = _path(data, table, season)
    if not p.exists():
        return frame(table, [])
    dtypes = {c: "string" for c in STR_COLS[table]}
    df = pd.read_csv(p, dtype=dtypes, keep_default_na=True)
    for c in COLS[table]:
        if c not in df.columns:
            df[c] = pd.NA
    return _types(table, df[COLS[table]])


def write(data: Path, table: str, season: int, df: pd.DataFrame) -> None:
    p = _path(data, table, season)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.gz")
    # mtime=0 keeps the file byte-identical when the contents are unchanged,
    # so git does not store a new copy every night.
    df.to_csv(tmp, index=False, compression={"method": "gzip", "mtime": 0, "compresslevel": 6})
    tmp.replace(p)


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, obj, compact: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(obj, indent=1, allow_nan=False)
    path.write_text(text)
