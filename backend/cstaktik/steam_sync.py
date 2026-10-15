"""Neue Matches über die offizielle Steam-Web-API finden (Sharecodes).

``ICSGOPlayers_730/GetNextMatchSharingCode/v1`` liefert zu SteamID, Game Authentication Code und einem bekannten
Sharecode den nächsten Sharecode; ist keiner neuer, kommt "n/a". Braucht einen Steam-Web-API-Schlüssel auf dem Server
(in der App unter Optionen eingetragen, sonst Umgebungsvariable STEAM_WEB_API_KEY;
https://steamcommunity.com/dev/apikey).

Die Demo-Datei selbst liefert diese API nicht: Dafür muss ein eingeloggter Steam-Account beim CS2-Game-Coordinator
die Match-Infos anfragen. Das ist hier noch nicht eingebaut; die gefundenen Sharecodes werden gespeichert.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from cstaktik import accounts

API = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1"
MAX_PER_RUN = 50  # Schutz gegen Endlosschleifen
INTERVAL_S = 1800


def _get(params: dict, timeout: float = 15) -> tuple[int, dict]:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - feste https-Quelle
            return r.status, json.loads(r.read(100_000) or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (OSError, ValueError):  # Netz weg, Zeitüberschreitung, kaputte Antwort
        return 0, {}


def next_codes(steamid: str, auth_code: str, known: str, key: str, get=None) -> tuple[list[str], str | None]:
    """Alle Sharecodes nach ``known``. Rückgabe: (neue Codes, Fehlertext oder None)."""
    get = get or _get
    out, cur = [], known
    for _ in range(MAX_PER_RUN):
        status, data = get({"key": key, "steamid": steamid, "steamidkey": auth_code, "knowncode": cur})
        nxt = (data.get("result") or {}).get("nextcode")
        if status in (200, 202) and nxt in (None, "", "n/a"):
            return out, None
        if status == 200 and nxt and accounts.SHARECODE_RE.match(nxt):
            out.append(nxt)
            cur = nxt
            continue
        err = {403: "Steam lehnt ab. Game Authentication Code oder SteamID passen nicht.",
               412: "Steam kennt den Match-Token nicht. Er ist zu alt oder falsch. Trag einen aktuellen ein.",
               429: "Steam begrenzt gerade die Anfragen. Versuch es später erneut.",
               0: "Steam ist gerade nicht erreichbar. Der Coach versucht es in 30 Minuten erneut."}.get(
            status, f"Steam-API antwortet {status}.")
        return out, err
    return out, None


def sync_user(row: dict, key: str | None = None, get=None, path=None) -> dict:
    key = key or accounts.steam_key(path)
    if not key:
        msg = "Es fehlt der Steam-Web-API-Schlüssel. Trag ihn unter Optionen → Server ein."
        accounts.record_codes(row["user"], [], None, msg, path)
        return {"new": 0, "error": msg}
    codes, err = next_codes(row["steamid"], row["auth_code"], row["last_code"], key, get)
    accounts.record_codes(row["user"], codes, codes[-1] if codes else None, err, path)
    return {"new": len(codes), "error": err}


def sync_all(path=None) -> int:
    n = 0
    for row in accounts.steam_users(path):
        n += sync_user(row, path=path)["new"]
    return n
