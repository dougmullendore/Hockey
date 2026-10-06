"""Paid versus worth: actual cap hits next to what each player's play is worth.

Cap hits are not in the NHL's data feeds. This module reads them from an
optional file, `contracts/cap_hits.csv`, with one line per contract:

    team,last,first,pos,cap_hit,expiry_status,section

and `contracts/info.json` saying where the numbers came from and when. If
the file is not there, nothing is built and the site simply has no contracts
page. A player whose salary is partly retained by a former team appears
once per team; the pieces are added back together to get his full cap hit."""
from __future__ import annotations

import csv
import datetime as dt
import unicodedata
from pathlib import Path

from . import store

REPO = Path(__file__).resolve().parents[1]
MIN_GAMES_FOR_GOALIE_SEASON = 50.0


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return "".join(c for c in text if c.isalpha())


def _group(pos: str) -> str:
    pos = (pos or "").upper()
    return "G" if pos.startswith("G") else "D" if pos in ("D", "LD", "RD") else "F"


def load(folder: Path | None = None) -> tuple[list[dict], dict]:
    """Contracts with split (retained) pieces merged, plus the source note."""
    folder = Path(folder) if folder else REPO / "contracts"
    path = folder / "cap_hits.csv"
    if not path.exists():
        return [], {}
    merged = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (_norm(r["last"]), _norm(r["first"]), _group(r["pos"]))
            cap = float(r["cap_hit"] or 0)
            m = merged.setdefault(key, {"last": r["last"], "first": r["first"], "group": key[2],
                                        "cap": 0.0, "teams": [], "status": r.get("expiry_status") or "",
                                        "main_cap": -1.0})
            m["cap"] += cap
            if r.get("section") != "X":
                m["teams"].append(r["team"])
            if cap > m["main_cap"]:                      # the team paying most is his current one
                m["main_cap"], m["team"] = cap, r["team"]
    return list(merged.values()), (store.read_json(folder / "info.json", {}) or {})


def _first_names_agree(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a[0] == b[0] and (a.startswith(b[:3]) or b.startswith(a[:3]) or len(a) <= 2 or len(b) <= 2)


def match(contracts: list[dict], people: dict) -> tuple[dict, list]:
    """Tie each contract to an NHL player id.

    people: {player_id: {"first", "last", "group", "team"}}
    Returns ({player_id: contract}, [contracts with no confident match])."""
    by_last = {}
    for pid, p in people.items():
        by_last.setdefault((_norm(p["last"]), p["group"]), []).append(pid)
    found, missed = {}, []
    for c in contracts:
        cands = by_last.get((_norm(c["last"]), c["group"]), [])
        if len(cands) > 1:
            named = [p for p in cands if _first_names_agree(people[p]["first"], c["first"])]
            cands = named or cands
        if len(cands) > 1:
            same_team = [p for p in cands if people[p].get("team") in (c.get("team"), *c["teams"])]
            cands = same_team or cands
        if len(cands) == 1 and cands[0] not in found and (
                _first_names_agree(people[cands[0]]["first"], c["first"])
                or people[cands[0]].get("team") in (c.get("team"), *c["teams"])):
            found[cands[0]] = c
        else:
            missed.append(c)
    return found, missed


def _age(born: str | None, today: dt.date) -> int | None:
    if not born:
        return None
    try:
        b = dt.date.fromisoformat(born)
    except ValueError:
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def build(cards_doc: dict, bio: dict, out: Path, folder: Path | None = None, log=print) -> dict:
    """Write contracts.json and add each matched player's cap hit to his card."""
    contracts, info = load(folder)
    if not contracts:
        return {}
    players = cards_doc["players"]
    seasons = [str(s) for s in cards_doc["seasons"]]
    latest = seasons[-1]
    rate, minimum = cards_doc["money"][latest]

    people = {}
    for pid, card in players.items():
        who = bio.get(pid) or {}
        name = card["n"] or ""
        first = who.get("first") or name.split(" ")[0]
        last = who.get("last") or " ".join(name.split(" ")[1:])
        people[pid] = {"first": first, "last": last, "group": card["p"], "team": card.get("t")}
    found, missed = match(contracts, people)

    today = dt.datetime.now(dt.timezone.utc).date()
    rows = []
    for pid, c in found.items():
        card = players[pid]
        year = max(card["y"])                       # his most recent season with games
        y = card["y"][year]
        goalie = card["p"] == "G"
        war_rate = y["v3"][0]                       # WAR per 82 games (50 for a goalie), 3-year blend
        games = sum(card["y"][s]["gp"] for s in seasons[max(0, seasons.index(year) - 2): seasons.index(year) + 1]
                    if s in card["y"])
        base = minimum * (MIN_GAMES_FOR_GOALIE_SEASON / 82.0 if goalie else 1.0)
        worth = None if war_rate is None else round(max(base, base + war_rate * rate), 2)
        cap = round(c["cap"] / 1e6, 3)
        card["c"] = cap
        rows.append({
            "id": int(pid), "name": card["n"], "team": c.get("team") or card.get("t"), "pos": card["p"],
            "age": _age((bio.get(pid) or {}).get("born"), today),
            "cap": cap, "worth": worth,
            "surplus": None if worth is None else round(worth - cap, 2),
            "war": war_rate, "games": int(games), "through": int(year),
            "status": c.get("status"),
        })
    rows.sort(key=lambda r: -(r["surplus"] if r["surplus"] is not None else -99))
    store.write_json(out / "contracts.json", rows, compact=True)
    store.write_json(out / "cards.json", cards_doc, compact=True)
    log(f"contracts: {len(rows)} matched, {len(missed)} not matched "
        f"({', '.join(m['first'] + ' ' + m['last'] for m in missed[:12])}{'...' if len(missed) > 12 else ''})")
    return {"players": len(rows), "unmatched": len(missed), "season": int(latest),
            "as_of": info.get("as_of"), "source": info.get("source"),
            "dollars_per_war": rate}
