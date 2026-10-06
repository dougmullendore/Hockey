"""Temporary probe: look at games whose shift chart came back empty."""
import json, sys, urllib.request, pathlib
OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; hockey-stats-site/1.0)"}
T = {
 "shifts_2024021235.json": "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId=2024021235",
 "shifts_2024021260.json": "https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId=2024021260",
 "TH021235.HTM": "https://www.nhl.com/scores/htmlreports/20242025/TH021235.HTM",
 "TV021235.HTM": "https://www.nhl.com/scores/htmlreports/20242025/TV021235.HTM",
 "TH020001_2025.HTM": "https://www.nhl.com/scores/htmlreports/20252026/TH020001.HTM",
 "TV020001_2025.HTM": "https://www.nhl.com/scores/htmlreports/20252026/TV020001.HTM",
}
log = []
for name, url in T.items():
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read()
        (OUT / name).write_bytes(body); log.append(f"OK {len(body)} {name}")
    except Exception as e:
        log.append(f"FAIL {name} {e!r}")
(OUT / "PROBE_LOG.txt").write_text("\n".join(log)); print("\n".join(log))
