"""Thin, retrying client for the NHL's public data feeds."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config


class FetchError(RuntimeError):
    pass


def get_bytes(url: str, retries: int | None = None, timeout: int = 60) -> bytes:
    """Download one URL, retrying on transient errors."""
    retries = config.FETCH_RETRIES if retries is None else retries
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404):
                raise FetchError(f"{e.code} {url}") from e
            # 429 = slow down; 5xx = server hiccup. Both are worth retrying.
        except Exception as e:  # network errors, timeouts
            last = e
        time.sleep(min(60, 1.5 * 2 ** attempt) + random.random())
    raise FetchError(f"gave up on {url}: {last!r}")


def get_json(url: str, retries: int | None = None, timeout: int = 60):
    """Download one URL and decode it as JSON."""
    retries = config.FETCH_RETRIES if retries is None else retries
    last = None
    for attempt in range(2):  # a truncated body is worth one more try
        try:
            return json.loads(get_bytes(url, retries, timeout))
        except FetchError:
            raise
        except ValueError as e:
            last = e
    raise FetchError(f"bad JSON from {url}: {last!r}")


def get_text(url: str) -> str:
    return get_bytes(url).decode("utf-8", errors="replace")


def get_many(urls: dict, threads: int | None = None, text: bool = False):
    """Download many URLs at once. `urls` maps a key to a URL.

    Yields (key, json_or_None, error_or_None) as each finishes. With
    text=True the body is returned as a string instead of decoded JSON."""
    threads = threads or config.FETCH_THREADS
    getter = get_text if text else get_json

    def one(item):
        key, url = item
        try:
            return key, getter(url), None
        except Exception as e:
            return key, None, e

    with ThreadPoolExecutor(max_workers=threads) as pool:
        yield from pool.map(one, list(urls.items()))


def pbp_url(game_id: int) -> str:
    return f"{config.API_WEB}/gamecenter/{game_id}/play-by-play"


def shifts_url(game_id: int) -> str:
    return f"{config.API_STATS}/shiftcharts?cayenneExp=gameId={game_id}"


def shift_report_url(game_id: int, season: int, home: bool) -> str:
    """The league's printable ice-time report for one team in one game."""
    return (f"https://www.nhl.com/scores/htmlreports/{season}/"
            f"T{'H' if home else 'V'}{game_id % 1000000:06d}.HTM")


def schedule_url(date: str) -> str:
    return f"{config.API_WEB}/schedule/{date}"


def seasons_url() -> str:
    return f"{config.API_STATS}/season"


def summary_url(kind: str, season: int, game_type: int) -> str:
    """Official season totals. kind is 'goalie' or 'skater'."""
    q = f"seasonId={season}%20and%20gameTypeId={game_type}"
    return f"{config.API_STATS}/{kind}/summary?limit=-1&cayenneExp={q}"
