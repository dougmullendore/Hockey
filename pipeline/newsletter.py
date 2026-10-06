"""Latest posts from the site's companion newsletter.

Reads the newsletter's public feed (RSS) and saves the newest post titles for
the home page. Only the title, date, link and a one-line teaser are kept; the
posts themselves stay on the newsletter's own site.

If the feed cannot be read, the last saved list is kept, so one bad night
never empties the home page."""
from __future__ import annotations

import datetime as dt
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import config, nhl_api, store

MAX_POSTS = 6
TEASER_CHARS = 170


def _plain(text: str | None) -> str:
    """Feed text with any HTML tags and entities removed."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _teaser(text: str) -> str:
    if len(text) <= TEASER_CHARS:
        return text
    return text[:TEASER_CHARS].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def parse(xml_text: str, home: str) -> dict:
    """Pick the channel description and newest posts out of an RSS feed."""
    channel = ET.fromstring(xml_text).find("channel")
    if channel is None:
        raise ValueError("not an RSS feed")
    posts = []
    for item in channel.findall("item"):
        title, link = _plain(item.findtext("title")), (item.findtext("link") or "").strip()
        if not title or not link.startswith(("https://", "http://")):
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            day = None
        posts.append({"title": title, "link": link, "date": day,
                      "teaser": _teaser(_plain(item.findtext("description")))})
    posts.sort(key=lambda p: p["date"] or "", reverse=True)
    return {"description": _plain(channel.findtext("description")), "posts": posts[:MAX_POSTS]}


def build(out: Path, log=print) -> dict:
    """Write newsletter.json for the site. Never raises: a newsletter outage
    must not fail the nightly run."""
    name, home = config.NEWSLETTER_NAME, config.NEWSLETTER_URL.rstrip("/")
    path = Path(out) / "newsletter.json"
    if not home:
        if path.exists():
            path.unlink()
        return {"skipped": "no newsletter set"}
    doc = store.read_json(path, {}) or {}
    doc.update({"name": name, "url": home})
    doc.setdefault("posts", [])
    try:
        fresh = parse(nhl_api.get_text(home + "/feed", retries=3), home)
        doc.update(fresh)
        doc["fetched_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
        result = {"posts": len(fresh["posts"]), "newest": fresh["posts"][0]["date"] if fresh["posts"] else None}
    except Exception as e:      # blocked, offline, or a feed we cannot read
        result = {"error": repr(e)[:200], "kept_posts": len(doc["posts"])}
    store.write_json(path, doc, compact=True)
    log(f"newsletter: {result}")
    return result
