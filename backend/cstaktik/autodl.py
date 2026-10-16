"""Automatischer Demo-Download für Valve-Matches (Premier, Competitive, Wingman).

Den Download selbst übernimmt das Open-Source-Werkzeug cs-demo-downloader (github.com/claabs/cs-demo-downloader,
MIT). Es läuft als eigener Docker-Container auf dem Server: Ein Bot-Account startet kurz CS2, fragt beim Game
Coordinator von Valve die Download-Adresse der Demo zu jedem neuen Match-Code ab und lädt die Demo herunter.

Dieses Modul
- schreibt dessen config.json aus den Optionen der App (Bot-Account, Steam-Web-API-Schlüssel, je verbundenem Nutzer
  Auth-Code, SteamID und ältester bekannter Match-Code). Das Werkzeug liest die Datei bei jedem Lauf neu.
- holt fertige Demos aus dessen Ausgabe-Ordner und gibt sie in die normale Auswertung (pipeline.run).
"""

from __future__ import annotations

import json
import os
import time
from contextlib import closing
from pathlib import Path

from cstaktik import accounts, pipeline
from cstaktik.fsutil import write_atomic

BASE = pipeline.DATA_DIR / "autodl"
CONFIG_DIR = BASE / "config"  # -> /config im Container
DEMOS_DIR = BASE / "demos"  # -> /demos im Container
SCHEDULE = "*/20 * * * *"  # alle 20 Minuten
SCAN_S = 60
IMAGE = "ghcr.io/claabs/cs-demo-downloader:latest"


def _ids() -> str:
    """Der Container läuft als derselbe Nutzer wie der Coach: beide dürfen die Dateien lesen und verschieben."""
    return f"{os.getuid()}:{os.getgid()}"


def docker_command() -> str:
    """Einmal auf dem Server ausführen: startet den Download-Container (läuft danach von selbst weiter)."""
    return (f"mkdir -p {CONFIG_DIR} {DEMOS_DIR} && chown -R {_ids()} {BASE} && "
            f"docker run -d --name cs-demo-downloader --restart unless-stopped --user {_ids()} "
            f"-v {CONFIG_DIR}:/config -v {DEMOS_DIR}:/demos {IMAGE}")


def bot() -> dict | None:
    user, pw = accounts.get_setting("autodl_bot_user"), accounts.get_setting("autodl_bot_pass")
    if not user or not pw:
        return None
    return {"username": user, "password": pw, "secret": accounts.get_setting("autodl_bot_secret") or ""}


def _oldest_code(user: str, fallback: str) -> str:
    """Ältester bekannter Match-Code des Nutzers: ab dort lädt das Werkzeug (Valve hält Demos nur einige Wochen)."""
    with closing(accounts.db()) as con:
        row = con.execute("SELECT code FROM sharecodes WHERE user = ? ORDER BY found ASC LIMIT 1", (user,)).fetchone()
    return row["code"] if row else fallback


def build_config() -> dict | None:
    """config.json für das Werkzeug, oder None, wenn etwas fehlt (Bot, Schlüssel oder kein Nutzer mit Codes)."""
    b, key = bot(), accounts.steam_key()
    users = [u for u in accounts.steam_users() if u.get("steamid") and u.get("auth_code") and u.get("last_code")]
    if not b or not key or not users:
        return None
    return {
        "authCodeLogin": b,
        "steamApiKey": key,
        "authCodes": [{"authCode": u["auth_code"], "steamId64": u["steamid"],
                       "oldestShareCode": _oldest_code(u["user"], u["last_code"])} for u in users],
        "logLevel": "info",
        "runOnStartup": True,
        "cronSchedule": SCHEDULE,
    }


def write_config() -> bool:
    """Konfiguration schreiben (nur lesbar für den Coach und den Container, enthält das Bot-Passwort)."""
    cfg = build_config()
    if cfg is None:
        return False
    path = CONFIG_DIR / "config.json"
    write_atomic(path, json.dumps(cfg, indent=2))
    os.chmod(path, 0o600)
    return True


def status() -> dict:
    """Für die Optionen: ist alles eingetragen, läuft der Container, was wurde zuletzt übernommen."""
    state = _load_state()
    return {"bot": bool(bot()), "key": bool(accounts.steam_key()), "config": (CONFIG_DIR / "config.json").exists(),
            "store": (CONFIG_DIR / "store.json").exists(),  # legt das Werkzeug nach seinem ersten Lauf an
            "imported": state.get("imported", []), "last": state.get("last"), "error": state.get("error")}


def _state_file() -> Path:
    return BASE / "imported.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    write_atomic(_state_file(), json.dumps(state, ensure_ascii=False))


def ready_demos() -> list[Path]:
    """Fertig heruntergeladene Demos. Das Werkzeug schreibt erst nach demos/temp und benennt dann um: alles direkt
    im Ordner ist vollständig."""
    return sorted(DEMOS_DIR.glob("*.dem")) if DEMOS_DIR.exists() else []


def take(p: Path) -> Path:
    """Demo in den normalen Demo-Ordner verschieben (keine doppelte Kopie auf der Platte)."""
    from cstaktik.archive import _unique

    pipeline.DEMOS_DIR.mkdir(parents=True, exist_ok=True)
    target = _unique(pipeline.DEMOS_DIR, p.name)
    p.replace(target)
    return target


def record(name: str, error: str | None = None) -> None:
    state = _load_state()
    imported = state.get("imported", [])
    imported.insert(0, {"name": name, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": error})
    state["imported"] = imported[:10]
    state["last"] = state["imported"][0]["at"]
    state["error"] = error
    _save_state(state)
