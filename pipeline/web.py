"""Downloading, with retries."""
from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config


class FetchError(RuntimeError):
    pass


def get_bytes(url: str, timeout: int = 45, tries: int | None = None) -> bytes:
    last = None
    for attempt in range(tries or config.FETCH_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":            # sent compressed though not asked to
                raw = gzip.decompress(raw)
            return raw
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 403, 404):
                break
        except Exception as e:  # network errors, timeouts
            last = e
        time.sleep(min(30, 1.5 * 2 ** attempt) + random.random())
    raise FetchError(f"could not download {url[:100]}: {last!r}")


def get_json(path: str, tries: int | None = None):
    """One document from the NHL feed. `path` is what follows .../v1/."""
    return json.loads(get_bytes(config.API + path, tries=tries))


def get_many(paths: list[str], tries: int | None = None):
    """Download many documents at once. Yields (path, document_or_None, error_or_None), in order."""
    def one(path):
        try:
            return path, get_json(path, tries), None
        except Exception as e:
            return path, None, e

    with ThreadPoolExecutor(max_workers=config.FETCH_THREADS) as pool:
        yield from pool.map(one, paths)
