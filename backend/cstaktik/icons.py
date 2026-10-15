"""Offizielle CS2-Waffen-Icons (Killfeed-Silhouetten) für das Replay.

Quelle: github.com/Juknum/counter-strike-icons (aus den CS2-Spieldateien, SVG; Rechte: Valve).
Werden nur lokal in data/icons gespeichert, nicht im Repo.
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/Juknum/counter-strike-icons/main/cs2/panorama/images/icons/equipment"
ICONS_DIR = Path(__file__).resolve().parent.parent / "data" / "icons"
ALL_ICONS = [
    "ak47", "m4a1_silencer", "m4a1", "awp", "glock", "usp_silencer", "hkp2000", "p250", "deagle", "fiveseven",
    "tec9", "cz75a", "elite", "revolver", "mp9", "mac10", "mp7", "mp5sd", "ump45", "p90", "bizon", "nova", "xm1014",
    "mag7", "sawedoff", "negev", "m249", "famas", "galilar", "aug", "sg556", "ssg08", "scar20", "g3sg1", "knife",
    "flashbang", "smokegrenade", "hegrenade", "molotov", "incgrenade", "decoy", "c4", "taser",
]
# normalisierter Name (klein, nur a-z0-9) -> Icon. Deckt Anzeigenamen ("AK-47") und Klassennamen ("weapon_ak47") ab.
_ALIASES = {
    "ak47": "ak47", "m4a1s": "m4a1_silencer", "m4a1silencer": "m4a1_silencer",
    "m4a4": "m4a1", "m4a1": "m4a1", "awp": "awp", "glock": "glock", "glock18": "glock", "usps": "usp_silencer",
    "uspsilencer": "usp_silencer", "p2000": "hkp2000", "hkp2000": "hkp2000", "p250": "p250", "deagle": "deagle",
    "deserteagle": "deagle", "fiveseven": "fiveseven", "tec9": "tec9", "cz75": "cz75a", "cz75a": "cz75a",
    "cz75auto": "cz75a", "elite": "elite", "dualberettas": "elite", "revolver": "revolver", "r8revolver": "revolver",
    "mp9": "mp9", "mac10": "mac10", "mp7": "mp7", "mp5sd": "mp5sd", "ump45": "ump45", "p90": "p90", "bizon": "bizon",
    "ppbizon": "bizon", "nova": "nova", "xm1014": "xm1014", "mag7": "mag7", "sawedoff": "sawedoff", "negev": "negev",
    "m249": "m249", "famas": "famas", "galil": "galilar", "galilar": "galilar", "aug": "aug", "sg553": "sg556",
    "sg556": "sg556", "ssg08": "ssg08", "scar20": "scar20", "g3sg1": "g3sg1", "flashbang": "flashbang",
    "smokegrenade": "smokegrenade", "hegrenade": "hegrenade", "highexplosivegrenade": "hegrenade",
    "molotov": "molotov", "incgrenade": "incgrenade", "incendiarygrenade": "incgrenade", "decoy": "decoy",
    "decoygrenade": "decoy", "c4": "c4", "c4explosive": "c4", "taser": "taser", "zeusx27": "taser", "zeus": "taser",
}
_KNIVES = ("knife", "bayonet", "karambit", "dagger", "bowie", "falchion", "stiletto", "talon", "ursus", "navaja",
           "kukri", "huntsman", "butterfly", "gut", "flip", "cleaver", "nomad", "skeleton", "survival", "paracord")


def icon_for(weapon: str | None) -> str | None:
    """Icon-Name für einen Waffennamen aus der Demo, None wenn unbekannt (dann zeigt das Replay eine Klassen-Form)."""
    if not weapon:
        return None
    w = re.sub(r"[^a-z0-9]", "", weapon.lower().removeprefix("weapon_"))
    if w in _ALIASES:
        return _ALIASES[w]
    if any(k in w for k in _KNIVES):
        return "knife"
    for key in sorted(_ALIASES, key=len, reverse=True):  # z. B. "ak47 | Redline" -> ak47
        if len(key) >= 3 and key in w:
            return _ALIASES[key]
    return None


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cstaktik"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste https-Quelle
        return resp.read(200_000)


def fetch_icon(name: str, icons_dir: Path = ICONS_DIR, timeout: float = 15.0) -> Path:
    if name not in ALL_ICONS:
        raise ValueError(f"Unbekanntes Icon: {name}")
    data = _get(f"{BASE}/{name}.svg", timeout)
    head = data[:300].lstrip()
    if not (head.startswith(b"<?xml") or head.startswith(b"<svg")) or b"<svg" not in data:
        raise ValueError(f"{name}: kein SVG")
    icons_dir.mkdir(parents=True, exist_ok=True)
    out = icons_dir / f"{name}.svg"
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


_FAILED: dict[str, float] = {}  # Name -> Zeitpunkt des letzten Fehlschlags (nicht bei jeder Auswertung neu warten)
RETRY_S = 3600


def ensure_icons(names: set[str], icons_dir: Path = ICONS_DIR) -> list[str]:
    """Lädt fehlende Icons. Gibt Namen zurück, die nicht geladen werden konnten."""
    import time

    failed = []
    for n in sorted(names):
        if (icons_dir / f"{n}.svg").exists():
            continue
        if time.time() - _FAILED.get(n, 0) < RETRY_S:  # kürzlich gescheitert: erst in einer Stunde wieder
            failed.append(n)
            continue
        try:
            fetch_icon(n, icons_dir)
        except Exception:  # noqa: BLE001 - Replay fällt auf Klassen-Form zurück
            _FAILED[n] = time.time()
            failed.append(n)
    return failed
