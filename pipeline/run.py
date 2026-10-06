"""The nightly job: download new games, (re)build the stats, build the site.

Usage:  python -m pipeline.run <data_dir> <site_output_dir>

Each stage is isolated so that a failure in one still lets the others run,
and the outcome of every stage is written to <data_dir>/status.json."""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
import traceback
from pathlib import Path

from . import store


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def main(data_dir: str, out_dir: str) -> int:
    data, out = Path(data_dir), Path(out_dir)
    data.mkdir(parents=True, exist_ok=True)
    status = {
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA", "local")[:12],
        "stages": {},
    }
    skip = set(filter(None, os.environ.get("SKIP_STAGES", "").split(",")))

    def stage(name, fn):
        if name in skip:
            status["stages"][name] = {"ok": True, "skipped": True}
            return None
        t0 = time.time()
        try:
            result = fn()
            status["stages"][name] = {"ok": True, "seconds": round(time.time() - t0, 1), "result": result}
            return result
        except Exception as e:
            log(f"STAGE {name} FAILED: {e!r}")
            traceback.print_exc()
            status["stages"][name] = {
                "ok": False, "seconds": round(time.time() - t0, 1),
                "error": repr(e), "trace": traceback.format_exc()[-4000:],
            }
            return None
        finally:
            store.write_json(data / "status.json", status)

    def do_fetch():
        from . import fetch
        return fetch.update_all(data, log, max_minutes=float(os.environ.get("MAX_FETCH_MINUTES", "150")))

    def do_model():
        from . import xg
        return xg.ensure_model(data, log)

    def do_stats():
        from . import aggregate
        return aggregate.build_all(data, log)

    def do_odds():
        from . import predict
        return predict.build(data, data / "site_data", log)

    def do_news():
        from . import newsletter
        return newsletter.build(data / "site_data", log)

    def do_site():
        from . import build_site
        return build_site.build(data, out, log)

    stage("fetch", do_fetch)
    stage("model", do_model)
    stage("stats", do_stats)
    stage("odds", do_odds)
    stage("news", do_news)
    stage("site", do_site)

    status["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    status["ok"] = all(s.get("ok") for s in status["stages"].values())
    store.write_json(data / "status.json", status)
    log("run finished: " + ("OK" if status["ok"] else "WITH ERRORS"))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
