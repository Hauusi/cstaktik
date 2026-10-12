"""Pro-Demos als Referenz: Positionen aller Spieler je 5 s Rundenzeit, gespeichert in data/pro.

Pro-Demos z. B. von HLTV am PC herunterladen, die .dem aus dem Archiv entpacken und mit
"Pro-Demo" hochladen (oder ``cstaktik pro <demo>``). Es wird kein Report erzeugt.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cstaktik.model import MatchData
from cstaktik.reference import timeline


def summarize(match: MatchData) -> dict:
    return {
        "id": match.source_sha256 or match.source_file,
        "source_file": match.source_file,
        "map": match.map_name,
        "rounds": len(match.rounds),
        "analyzed_at": datetime.now().isoformat(timespec="minutes"),
        "timeline": timeline(match, all_players=True),
    }


def save(summary: dict, pro_dir: Path) -> Path:
    pro_dir.mkdir(parents=True, exist_ok=True)
    key = "".join(ch for ch in str(summary["id"]) if ch.isalnum())[:40] or "pro"
    out = pro_dir / f"{key}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False))
    return out


def load_all(pro_dir: Path) -> list[dict]:
    out = []
    for f in sorted(pro_dir.glob("*.json")) if pro_dir.exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def overview(pro_dir: Path) -> dict[str, int]:
    """Map -> Anzahl Pro-Demos."""
    counts: dict[str, int] = {}
    for d in load_all(pro_dir):
        counts[d.get("map") or "?"] = counts.get(d.get("map") or "?", 0) + 1
    return counts
