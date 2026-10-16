#!/usr/bin/env python3
"""Bangun pembaca HTML statis (docs/index.html) dari data/articles.json."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / "template.html"


def build_site(articles: list[dict], cfg: dict, out: Path) -> Path:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "topics": [t["name"] for t in cfg.get("topics", [])],
        "articles": articles,
    }
    # </script> di dalam data harus dinetralkan
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    arts_path = BASE / "data" / "articles.json"
    arts = json.loads(arts_path.read_text(encoding="utf-8")) if arts_path.exists() else []
    p = build_site(arts, cfg, BASE / "docs" / "index.html")
    print(f"Ditulis: {p} ({len(arts)} artikel)")
