"""One-off probe: download a handful of raw NHL API responses so the parser
can be developed and tested against real data. Writes into the folder given
as argv[1]."""
import json, sys, time, urllib.request, pathlib, traceback

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (hockey-stats-site data pipeline)"}

TARGETS = {
    "schedule_2025-10-07.json": "https://api-web.nhle.com/v1/schedule/2025-10-07",
    "schedule_now.json": "https://api-web.nhle.com/v1/schedule/now",
    "pbp_2025020001.json": "https://api-web.nhle.com/v1/gamecenter/2025020001/play-by-play",
    "pbp_2025020500.json": "https://api-web.nhle.com/v1/gamecenter/2025020500/play-by-play",
    "pbp_2024030411.json": "https://api-web.nhle.com/v1/gamecenter/2024030411/play-by-play",
    "pbp_2021020100.json": "https://api-web.nhle.com/v1/gamecenter/2021020100/play-by-play",
    "boxscore_2025020001.json": "https://api-web.nhle.com/v1/gamecenter/2025020001/boxscore",
    "landing_2025020001.json": "https://api-web.nhle.com/v1/gamecenter/2025020001/landing",
    "shifts_2025020001.json": "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId=2025020001",
    "season.json": "https://api.nhle.com/stats/rest/en/season",
    "standings_now.json": "https://api-web.nhle.com/v1/standings/now",
    "club_schedule_TOR_20252026.json": "https://api-web.nhle.com/v1/club-schedule-season/TOR/20252026",
    "goalie_summary_20252026.json": "https://api.nhle.com/stats/rest/en/goalie/summary?limit=-1&cayenneExp=seasonId=20252026%20and%20gameTypeId=2",
}

log = []
for name, url in TARGETS.items():
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        json.loads(body)
        (OUT / name).write_bytes(body)
        log.append(f"OK   {len(body):>9} {name}")
    except Exception as e:  # noqa
        log.append(f"FAIL {name}: {e!r}")
        log.append(traceback.format_exc())
    time.sleep(0.5)

(OUT / "PROBE_LOG.txt").write_text("\n".join(log) + "\n")
print("\n".join(log))
