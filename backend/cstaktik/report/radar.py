"""Welt -> Bild-Koordinaten für das 2D-Radar.

Mit awpy-Kartendaten (``awpy get maps`` -> ~/.awpy/maps/map-data.json + <map>.png) wird
die offizielle Radar-Transformation genutzt (gleiche Formel wie awpy.plot.utils.game_to_pixel).
Ohne diese Dateien: Bounding-Box der Positionen, ohne Kartenbild.
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from cstaktik.model import MatchData

AWPY_MAPS_DIR = Path.home() / ".awpy" / "maps"


@dataclass
class Radar:
    width: float
    height: float
    image_data_uri: str | None
    note: str | None
    _pos_x: float
    _pos_y: float
    _scale: float
    _flip_y: bool

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        px = (x - self._pos_x) / self._scale
        py = (self._pos_y - y) / self._scale if self._flip_y else (y - self._pos_y) / self._scale
        return round(px, 1), round(py, 1)


def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def build_radar(match: MatchData, maps_dir: Path = AWPY_MAPS_DIR) -> Radar:
    name = match.map_name or ""
    meta_file, img_file = maps_dir / "map-data.json", maps_dir / f"{name}.png"
    if name and meta_file.exists() and img_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8")).get(name)
        data = img_file.read_bytes()
        size = _png_size(data)
        if meta and size:
            return Radar(
                width=size[0],
                height=size[1],
                image_data_uri="data:image/png;base64," + base64.b64encode(data).decode(),
                note=None,
                _pos_x=meta["pos_x"],
                _pos_y=meta["pos_y"],
                _scale=meta["scale"],
                _flip_y=True,
            )

    # Fallback: Bounding-Box aller Positionen
    xs = [p.pos.x for p in match.positions] + [k.victim_pos.x for k in match.kills if k.victim_pos]
    ys = [p.pos.y for p in match.positions] + [k.victim_pos.y for k in match.kills if k.victim_pos]
    if not xs:
        xs, ys = [0.0, 1.0], [0.0, 1.0]
    pad = 100.0
    min_x, max_x, min_y, max_y = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    span = max(max_x - min_x, max_y - min_y)
    scale = span / 1000.0
    return Radar(
        width=round((max_x - min_x) / scale),
        height=round((max_y - min_y) / scale),
        image_data_uri=None,
        note="Radarbild fehlt (am PC einmal 'awpy get maps' ausführen). Laufwege ohne Karte.",
        _pos_x=min_x,
        _pos_y=max_y,
        _scale=scale,
        _flip_y=True,
    )
