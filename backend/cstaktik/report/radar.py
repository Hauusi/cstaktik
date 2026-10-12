"""Welt -> Radar-Pixel.

Gesucht wird in ``backend/data/maps/`` und ``~/.awpy/maps/`` (Ergebnis von ``awpy get maps``):

- Kalibrierung: ``map-data.json`` (awpy-Format) oder ``<map>.txt`` (Valve-Overview mit
  ``pos_x``, ``pos_y``, ``scale``)
- Bild: ``<map>.png`` / ``<map>_radar.png`` / ``.jpg`` / ``.webp``

Formel wie awpy.plot.utils.game_to_pixel: px = (x - pos_x) / scale, py = (pos_y - y) / scale.
Ohne Kalibrierung: Bounding-Box der Positionen, kein Kartenbild.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

from cstaktik.model import MatchData

AWPY_MAPS_DIR = Path.home() / ".awpy" / "maps"
LOCAL_MAPS_DIR = Path(__file__).resolve().parents[2] / "data" / "maps"
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


@dataclass
class Radar:
    size: float  # Kantenlänge der Zeichenfläche in Radar-Pixeln (ohne Bild)
    image_data_uri: str | None
    note: str | None
    pos_x: float
    pos_y: float
    scale: float

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return round((x - self.pos_x) / self.scale, 1), round((self.pos_y - y) / self.scale, 1)


def _calibration(name: str, d: Path) -> dict | None:
    meta = d / "map-data.json"
    if meta.exists():
        entry = json.loads(meta.read_text(encoding="utf-8")).get(name)
        if entry and {"pos_x", "pos_y", "scale"} <= entry.keys():
            return entry
    txt = d / f"{name}.txt"
    if txt.exists():
        vals = dict(re.findall(r'"(pos_x|pos_y|scale)"\s+"([-\d.]+)"', txt.read_text(encoding="utf-8", errors="ignore")))
        if len(vals) == 3:
            return {k: float(v) for k, v in vals.items()}
    return None


def _image(name: str, d: Path) -> str | None:
    for stem in (name, f"{name}_radar"):
        for ext, mime in _MIME.items():
            f = d / f"{stem}{ext}"
            if f.exists():
                return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()
    return None


def build_radar(match: MatchData, maps_dirs: list[Path] | None = None) -> Radar:
    name = match.map_name or ""
    dirs = maps_dirs if maps_dirs is not None else [LOCAL_MAPS_DIR, AWPY_MAPS_DIR]
    for d in dirs:
        cal = _calibration(name, d) if name else None
        img = _image(name, d) if cal else None
        if cal and img:
            return Radar(1024, img, None, cal["pos_x"], cal["pos_y"], cal["scale"])

    xs = [p.pos.x for p in match.positions] + [k.victim_pos.x for k in match.kills if k.victim_pos]
    ys = [p.pos.y for p in match.positions] + [k.victim_pos.y for k in match.kills if k.victim_pos]
    if not xs:
        xs, ys = [0.0, 1.0], [0.0, 1.0]
    pad = 150.0
    min_x, max_x, min_y, max_y = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    span = max(max_x - min_x, max_y - min_y)
    scale = span / 1024.0
    # zentrieren
    pos_x = min_x - (span - (max_x - min_x)) / 2
    pos_y = max_y + (span - (max_y - min_y)) / 2
    return Radar(
        1024,
        None,
        "Kartenbild fehlt: Radar-Dateien nach backend/data/maps legen (siehe README). Laufwege ohne Karte.",
        pos_x,
        pos_y,
        scale,
    )
