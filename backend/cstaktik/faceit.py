"""Pro-Demos automatisch über die offizielle FACEIT-API holen (Data API + Downloads API).

Ablauf (laut FACEIT-Doku):
1. Data API ``GET /data/v4/hubs/{hub_id}/matches?type=past`` liefert Matches mit ``demo_url``.
2. ``demo_url`` ist privat; Downloads API ``POST /download/v2/demos/download`` mit
   ``{"resource_url": demo_url}`` liefert ``payload.download_url`` (signierter Link).
3. Datei laden, entpacken, als Pro-Referenz speichern (pipeline.run_pro), Rohdatei löschen.

Schlüssel: Umgebungsvariable FACEIT_API_KEY (Server-Side-Key aus dem FACEIT Developer Portal).
Für Schritt 2 braucht der Schlüssel ggf. eine freigeschaltete Downloads-API-Berechtigung;
``cstaktik faceit-test`` prüft das und meldet es klar.
"""

from __future__ import annotations

from cstaktik.fsutil import write_atomic

import bz2
import gzip
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA_API = "https://open.faceit.com/data/v4"
DOWNLOAD_API = "https://open.faceit.com/download/v2/demos/download"
MAX_DEMO_BYTES = 2 * 1024**3


class FaceitError(Exception):
    pass


def _key() -> str:
    key = os.environ.get("FACEIT_API_KEY", "").strip()
    if not key:
        raise FaceitError("FACEIT_API_KEY ist nicht gesetzt (Server-Side-Key aus dem FACEIT Developer Portal).")
    return key


def _request(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_key()}", "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "cstaktik",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste https-API
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise FaceitError("FACEIT lehnt den Schlüssel ab (401). Server-Side-Key prüfen.") from exc
        if exc.code == 403 and url.startswith(DOWNLOAD_API):
            raise FaceitError("Downloads API verweigert (403): Der Schlüssel hat keine Freigabe für Demo-Downloads. "
                              "Im FACEIT Developer Portal den Zugang zur Downloads API beantragen.") from exc
        raise FaceitError(f"FACEIT-API Fehler {exc.code} bei {url.split('?')[0]}") from exc


def hub_matches(hub_id: str, offset: int = 0, limit: int = 50) -> list[dict]:
    res = _request("GET", f"{DATA_API}/hubs/{hub_id}/matches?type=past&offset={offset}&limit={limit}")
    return res.get("items", [])


def match_map(m: dict) -> str | None:
    """Mapname aus der Match-Antwort (voting.map.pick), falls vorhanden."""
    pick = ((m.get("voting") or {}).get("map") or {}).get("pick")
    if isinstance(pick, list) and pick:
        return str(pick[0])
    return None


def signed_url(resource_url: str) -> str:
    res = _request("POST", DOWNLOAD_API, {"resource_url": resource_url})
    url = (res.get("payload") or {}).get("download_url")
    if not url:
        raise FaceitError("Downloads API lieferte keinen download_url.")
    return url


def download(url: str, dest_dir: Path, name: str, timeout: float = 120.0) -> Path:
    """Lädt die Demo und entpackt .gz/.bz2 zu .dem. Andere Formate werden klar abgelehnt."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw = dest_dir / f"{name}.part"
    req = urllib.request.Request(url, headers={"User-Agent": "cstaktik"})
    out = dest_dir / f"{name}.dem"
    try:  # auch bei Abbruch im Download (Netz, zu groß) keine halbe Datei liegen lassen
        with urllib.request.urlopen(req, timeout=timeout) as resp, raw.open("wb") as fh:  # noqa: S310
            size = 0
            while chunk := resp.read(1 << 20):
                size += len(chunk)
                if size > MAX_DEMO_BYTES:
                    raise FaceitError("Demo größer als 2 GB, abgebrochen.")
                fh.write(chunk)
        with raw.open("rb") as fh:
            head = fh.read(8)
        if head[:2] == b"\x1f\x8b":
            opener = gzip.open
        elif head[:3] == b"BZh":
            opener = bz2.open
        elif head[:7] == b"PBDEMS2":
            raw.replace(out)
            return out
        elif head[:4] == b"\x28\xb5\x2f\xfd":
            raise FaceitError("Demo ist zstd-komprimiert; dieses Format wird noch nicht unterstützt.")
        else:
            raise FaceitError("Unbekanntes Demo-Format (kein .dem, .gz oder .bz2).")
        written = 0
        with opener(raw, "rb") as fin, out.open("wb") as fout:
            while chunk := fin.read(1 << 20):
                written += len(chunk)
                if written > MAX_DEMO_BYTES:  # entpackt begrenzen: eine kleine Datei kann sich riesig aufblähen
                    raise FaceitError("Entpackte Demo größer als 2 GB, abgebrochen.")
                fout.write(chunk)
        return out
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        raw.unlink(missing_ok=True)

def _load_index(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    return {"done": {}, "failed": {}}


def sync(cfg: dict, pro_dir: Path, work_dir: Path, run_pro, log=print, sleep_s: float = 1.0) -> dict:
    """Holt pro Map bis ``per_map`` neue Demos aus den konfigurierten Hubs.

    ``run_pro(path) -> {"map": ..}`` speichert die Referenz. Bereits verarbeitete Matches werden übersprungen.
    """
    index_file = pro_dir / "faceit_index.json"
    index = _load_index(index_file)
    wanted = list(cfg["maps"])
    have: dict[str, int] = {}
    for info in index["done"].values():
        have[info.get("map")] = have.get(info.get("map"), 0) + 1
    target = {m: have.get(m, 0) + cfg["per_map"] for m in wanted}
    added = {m: 0 for m in wanted}

    def full() -> bool:
        return all(have.get(m, 0) >= target[m] for m in wanted)

    for hub in cfg["hubs"]:
        offset = 0
        while not full() and offset < cfg["max_scan"]:
            matches = hub_matches(hub, offset=offset, limit=50)
            if not matches:
                break
            offset += len(matches)
            for m in matches:
                if full():
                    break
                mid = m.get("match_id")
                if not mid or mid in index["done"] or mid in index["failed"]:
                    continue
                mp = match_map(m)
                if mp and (mp not in target or have.get(mp, 0) >= target[mp]):
                    continue
                demos = m.get("demo_url") or []
                if not demos:
                    continue
                try:
                    url = signed_url(demos[0])
                    demo = download(url, work_dir, f"faceit_{mid}")
                    try:
                        info = run_pro(demo)
                    finally:
                        demo.unlink(missing_ok=True)
                    got = info.get("map")
                    index["done"][mid] = {"map": got, "hub": hub}
                    have[got] = have.get(got, 0) + 1
                    if got in added:
                        added[got] += 1
                    log(f"ok      {mid} {got}")
                except FaceitError as exc:
                    if "Downloads API verweigert" in str(exc) or "Schlüssel" in str(exc):
                        raise  # betrifft alle Matches: sofort melden
                    index["failed"][mid] = str(exc)
                    log(f"FEHLER  {mid}: {exc}")
                except OSError as exc:
                    import urllib.error

                    # nur echte Netzprobleme erneut versuchen; HTTP-Fehler (Demo weg/abgelaufen) und kaputte .gz nicht
                    transient = (isinstance(exc, (TimeoutError, ConnectionError))
                                 or (isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)))
                    if transient:
                        log(f"FEHLER  {mid}: {type(exc).__name__}: {exc} (wird beim nächsten Sync erneut versucht)")
                    else:
                        index["failed"][mid] = f"{type(exc).__name__}: {exc}"
                        log(f"FEHLER  {mid}: {type(exc).__name__}: {exc}")
                except Exception as exc:  # noqa: BLE001 - einzelnes Match überspringen
                    index["failed"][mid] = f"{type(exc).__name__}: {exc}"
                    log(f"FEHLER  {mid}: {type(exc).__name__}: {exc}")
                finally:
                    pro_dir.mkdir(parents=True, exist_ok=True)
                    write_atomic(index_file, json.dumps(index, indent=1))
                time.sleep(sleep_s)
    return {"added": added, "total": {m: have.get(m, 0) for m in wanted}}


def selftest(cfg: dict) -> list[str]:
    """Prüft Schlüssel, Hub-Zugriff und Downloads-API-Freigabe. Gibt lesbare Zeilen zurück."""
    lines = []
    _key()
    lines.append("Schlüssel gesetzt.")
    for hub in cfg["hubs"]:
        ms = hub_matches(hub, limit=20)
        with_demo = [m for m in ms if m.get("demo_url")]
        maps = sorted({match_map(m) or "?" for m in ms})
        lines.append(f"Hub {hub}: {len(ms)} Matches gelesen, {len(with_demo)} mit Demo, Maps: {', '.join(maps)}")
        if with_demo:
            signed_url(with_demo[0]["demo_url"][0])
            lines.append("Downloads API: Freigabe vorhanden, signierter Link erhalten.")
            return lines
    lines.append("Kein Match mit Demo gefunden: Hub-ID in rules.yaml (faceit.hubs) prüfen.")
    return lines
