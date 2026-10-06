"""Assemble the finished website: the pages in site/ plus the data tables."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import store

SITE_SRC = Path(__file__).resolve().parents[1] / "site"


def build(data: Path, out: Path, log) -> dict:
    data, out = Path(data), Path(out)
    src = data / "site_data"
    if not (src / "meta.json").exists():
        raise RuntimeError("no stats tables have been built yet")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out)
    shutil.copytree(src, out / "data")
    files = [p for p in out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    log(f"site: {len(files)} files, {size / 1e6:.1f} MB")
    meta = store.read_json(src / "meta.json", {})
    return {"files": len(files), "mb": round(size / 1e6, 2), "updated": meta.get("updated_utc")}
