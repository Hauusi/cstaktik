"""Radarbilder und Kalibrierung (pos_x, pos_y, scale) für die 2D-Karte herunterladen.

Quelle: github.com/MurkyYT/cs2-map-icons. Die Dateien werden dort automatisch aus dem
offiziellen CS2-Depot gezogen (Rechte: Valve). Sie landen nur lokal in data/maps, nicht im Repo.
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/main"
DEFAULT_MAPS = ["de_mirage", "de_dust2", "de_inferno", "de_nuke", "de_ancient", "de_anubis", "de_train",
                "de_overpass", "de_vertigo"]
_CAL = re.compile(r'"(pos_x|pos_y|scale)"\s+"([-\d.]+)"')


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cstaktik"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste https-Quelle
        return resp.read()


def has_map(name: str, maps_dir: Path) -> bool:
    return (maps_dir / f"{name}.txt").exists() and (maps_dir / f"{name}_radar_psd.png").exists()


def fetch_map(name: str, maps_dir: Path, timeout: float = 20.0) -> None:
    """Lädt Kalibrierung + Radarbild. Prüft beides, bevor es gespeichert wird."""
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError(f"Ungültiger Mapname: {name}")
    txt = _get(f"{BASE}/data/radar_info/{name}.txt", timeout)
    if len(dict(_CAL.findall(txt.decode("utf-8", "ignore")))) != 3:
        raise ValueError(f"Kalibrierung für {name} unvollständig (pos_x/pos_y/scale fehlt)")
    png = _get(f"{BASE}/images/radars/{name}_radar_psd.png", timeout)
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Radarbild für {name} ist kein PNG")
    maps_dir.mkdir(parents=True, exist_ok=True)
    for fname, data in ((f"{name}.txt", txt), (f"{name}_radar_psd.png", png)):
        tmp = maps_dir / (fname + ".part")
        tmp.write_bytes(data)
        tmp.replace(maps_dir / fname)


def ensure_map(name: str | None, maps_dir: Path, timeout: float = 20.0) -> str | None:
    """Sorgt dafür, dass die Karte lokal liegt. Gibt bei Problemen einen Hinweistext zurück."""
    if not name:
        return "Mapname fehlt in der Demo: kein Radarbild."
    if has_map(name, maps_dir):
        return None
    try:
        fetch_map(name, maps_dir, timeout)
        return None
    except Exception as exc:  # noqa: BLE001 - Report soll trotzdem entstehen
        return f"Radarbild für {name} nicht geladen ({type(exc).__name__}: {exc})"
