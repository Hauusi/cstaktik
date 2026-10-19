"""Sprache des Spielers: Callouts statt interner Ortsnamen, Spieluhr statt verstrichener Zeit, Meter statt Units.

- Ortsnamen kommen aus der Navmesh der Map (z. B. "TopofMid", "BombsiteA"). Spieler sagen "Top Mid", "A-Site".
  Die Tabelle übersetzt die bekannten Namen; unbekannte werden lesbar getrennt ("SideAlley" -> "Side Alley").
- Die Zeit in der Demo zählt ab Rundenstart (Ende der Freezetime) hoch. Die Uhr im Spiel zählt von 1:55 herunter,
  nach dem Plant 40 s Bombentimer. ``clock`` rechnet um, damit man die Stelle in CS wiederfindet.
- Hammer-Units: 1 Unit = 1 Zoll = 2,54 cm (Spielerhöhe 72 Units = 1,83 m).
"""

from __future__ import annotations

import re

ROUND_S = 115  # Rundenzeit 1:55 (Premier, Competitive, FACEIT)
BOMB_S = 40
UNIT_M = 0.0254

# Navmesh-Name -> Callout. Gilt für alle Maps; Namen, die es nur auf einer Map gibt, stören die anderen nicht.
CALLOUTS = {
    "BombsiteA": "A-Site", "BombsiteB": "B-Site", "TSpawn": "T-Spawn", "CTSpawn": "CT-Spawn",
    "TopofMid": "Top Mid", "Middle": "Mid", "LowerMid": "Lower Mid", "SecondMid": "Second Mid",
    "SnipersNest": "Sniper's Nest", "PalaceInterior": "Palace", "PalaceAlley": "Palace-Eingang",
    "TRamp": "T-Ramp", "SideAlley": "Side Alley", "BackAlley": "Back Alley", "Apartments": "Apartments",
    "Underpass": "Underpass", "Catwalk": "Catwalk", "Connector": "Connector", "Jungle": "Jungle",
    "Stairs": "Stairs", "Ladder": "Ladder", "Truck": "Truck", "House": "House", "Shop": "Shop",
    "Balcony": "Balkon", "Banana": "Banana", "Kitchen": "Kitchen", "Upstairs": "Upstairs", "Deck": "Deck",
    "Bridge": "Bridge", "Quad": "Quad", "Pit": "Pit", "Arch": "Arch", "Ruins": "Ruins",
    "LongDoors": "Long Doors", "LongA": "Long A", "ShortStairs": "Short", "OutsideLong": "Outside Long",
    "OutsideTunnel": "Outside Tunnel", "UpperTunnel": "Upper Tunnel", "LowerTunnel": "Lower Tunnel",
    "TunnelStairs": "Tunnel Stairs", "CTMid": "CT Mid", "BDoors": "B Doors", "ExtendedA": "A Short",
}


def place(name: str | None) -> str:
    """Callout für einen Navmesh-Ort ("" ohne Ort)."""
    if not name:
        return ""
    if name in CALLOUTS:
        return CALLOUTS[name]
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).replace("_", " ")


def clock(sec: float | None, planted_at: float | None = None) -> str:
    """Sekunden seit Rundenstart -> Uhr im Spiel ("1:05"). Nach dem Plant: Bombentimer ("Bombe 0:23")."""
    if sec is None:
        return ""
    if planted_at is not None and sec >= planted_at:
        left = max(0, round(BOMB_S - (sec - planted_at)))
        return f"Bombe 0:{left:02d}"
    left = max(0, round(ROUND_S - sec))
    return f"{left // 60}:{left % 60:02d}"


def meters(units: float | None) -> str:
    """Units -> Meter, gerundet ("17 m")."""
    if units is None:
        return ""
    m = units * UNIT_M
    return f"{m:.1f} m".replace(".", ",") if m < 10 else f"{round(m)} m"


def register(env) -> None:
    """Jinja-Filter: {{ x|callout }}, {{ s|clock }}, {{ u|meters }}."""
    env.filters["callout"] = place
    env.filters["clock"] = clock
    env.filters["meters"] = meters


# Für Seiten mit JavaScript (Report, Replay): dieselbe Tabelle als JS-Funktion
JS = ("const CALLOUTS=" + __import__("json").dumps(CALLOUTS) + ";"
      "function callout(n){if(!n)return'';if(CALLOUTS[n])return CALLOUTS[n];"
      "return n.replace(/([a-z])([A-Z])/g,'$1 $2').replace(/([A-Z])([A-Z][a-z])/g,'$1 $2').replace(/_/g,' ');}"
      f"function gclock(s){{if(s==null)return'';const l=Math.max(0,Math.round({ROUND_S}-s));"
      "return Math.floor(l/60)+':'+String(l%60).padStart(2,'0');}"
      f"function meters(u){{if(u==null)return'';const m=u*{UNIT_M};"
      "return m<10?m.toFixed(1).replace('.',',')+' m':Math.round(m)+' m';}")
