"""Automatischer Demo-Download über den eigenen Steam-Account (ohne Zweitaccount, ohne Docker).

Ablauf (wie der Steam-Login im Browser und wie cs-demo-downloader im "GCPD"-Modus, github.com/claabs/cs-demo-downloader):
1. Einmal anmelden: Passwort (RSA-verschlüsselt an Steam) und Steam-Guard-Code bzw. Bestätigung in der Steam-App.
   Steam liefert einen Anmelde-Schlüssel (refresh token). Nur der wird gespeichert, das Passwort nie.
2. Regelmäßig: Mit dem Schlüssel ein Browser-Cookie holen und die Seite "Persönliche Spieldaten" von CS2 lesen
   (steamcommunity.com/my/gcpd/730). Dort steht zu jedem der letzten Matches der Download-Link der Demo
   (replayNNN.valve.net/730/<matchid>_<n>.dem.bz2).
3. Neue Demos herunterladen, entpacken und wie einen Upload auswerten.

Netzwerkzugriffe laufen über ``_http`` (in Tests ersetzbar).
"""

from __future__ import annotations

import base64
import bz2
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

API = "https://api.steampowered.com/IAuthenticationService"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TABS = ("matchhistorypremier", "matchhistorycompetitivepermap", "matchhistorycompetitive", "matchhistorywingman",
        "matchhistoryscrimmage")
REPLAY = re.compile(r"https?://replay\d+\.valve\.net/730/(\d+)_\d+\.dem\.bz2")
INTERVAL_S = 20 * 60
MAX_BYTES = 2 * 1024**3


class SteamLoginError(Exception):
    """Verständliche Meldung für die Optionen."""


# ---------------------------------------------------------------- HTTP

def _http(url: str, data: dict | None = None, cookies: CookieJar | None = None, timeout: float = 20) -> bytes:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies)) if cookies is not None \
        else urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as r:  # noqa: S310 - feste Steam-Adressen
        return r.read()


def _api(method: str, data: dict, http=None) -> dict:
    http = http or _http
    try:
        raw = http(f"{API}/{method}/v1", data)
    except urllib.error.HTTPError as exc:
        raise SteamLoginError(f"Steam lehnt die Anfrage ab (HTTP {exc.code}).") from exc
    except OSError as exc:
        raise SteamLoginError(f"Steam ist gerade nicht erreichbar: {exc}") from exc
    try:
        return json.loads(raw).get("response") or {}
    except ValueError as exc:
        raise SteamLoginError("Unerwartete Antwort von Steam.") from exc


# ---------------------------------------------------------------- Login

def _rsa_encrypt(password: str, mod_hex: str, exp_hex: str) -> str:
    """RSA PKCS#1 v1.5 mit dem öffentlichen Schlüssel von Steam (nur Standardbibliothek)."""
    n, e = int(mod_hex, 16), int(exp_hex, 16)
    k = (n.bit_length() + 7) // 8
    msg = password.encode("utf-8")
    if len(msg) > k - 11:
        raise SteamLoginError("Passwort zu lang.")
    pad = b""
    while len(pad) < k - 3 - len(msg):
        b = secrets.token_bytes(1)
        if b != b"\x00":
            pad += b
    em = b"\x00\x02" + pad + b"\x00" + msg
    c = pow(int.from_bytes(em, "big"), e, n)
    return base64.b64encode(c.to_bytes(k, "big")).decode()


def begin_login(account: str, password: str, http=None) -> dict:
    """Login starten. Rückgabe: Sitzung (client_id, request_id, steamid) und welche Bestätigung Steam will."""
    http = http or _http
    try:
        raw = http(f"{API}/GetPasswordRSAPublicKey/v1?" + urllib.parse.urlencode({"account_name": account}))
        key = json.loads(raw).get("response") or {}
    except (OSError, ValueError) as exc:
        raise SteamLoginError(f"Steam ist gerade nicht erreichbar: {exc}") from exc
    if not key.get("publickey_mod"):
        raise SteamLoginError("Steam kennt diesen Login-Namen nicht.")
    enc = _rsa_encrypt(password, key["publickey_mod"], key["publickey_exp"])
    r = _api("BeginAuthSessionViaCredentials", {
        "account_name": account, "encrypted_password": enc, "encryption_timestamp": key["timestamp"],
        "remember_login": "true", "persistence": "1", "website_id": "Community",
        "device_friendly_name": "cstaktik Coach"}, http)
    if not r.get("client_id"):
        raise SteamLoginError("Login abgelehnt. Login-Name oder Passwort stimmen nicht.")
    kinds = {c.get("confirmation_type") for c in r.get("allowed_confirmations") or []}
    return {"client_id": str(r["client_id"]), "request_id": r["request_id"], "steamid": str(r["steamid"]),
            "account": account,
            # 3 = Code aus der Steam-App, 2 = Code per E-Mail, 4 = in der Steam-App bestätigen, 1 = nichts nötig
            "needs": "app" if 3 in kinds else "mail" if 2 in kinds else "confirm" if 4 in kinds else "none"}


def finish_login(sess: dict, code: str = "", http=None, wait_s: float = 25) -> str:
    """Steam-Guard-Code senden (falls nötig) und auf den Anmelde-Schlüssel warten. Rückgabe: refresh token."""
    code = code.strip().upper()
    if code:
        _api("UpdateAuthSessionWithSteamGuardCode", {
            "client_id": sess["client_id"], "steamid": sess["steamid"], "code": code,
            "code_type": "2" if sess.get("needs") == "mail" else "3"}, http)
    end = time.monotonic() + wait_s
    while True:
        r = _api("PollAuthSessionStatus", {"client_id": sess["client_id"], "request_id": sess["request_id"]}, http)
        if r.get("refresh_token"):
            return r["refresh_token"]
        if time.monotonic() > end:
            raise SteamLoginError("Steam hat die Anmeldung nicht bestätigt. Code prüfen oder in der Steam-App "
                                  "bestätigen und erneut versuchen.")
        time.sleep(2)


def token_expiry(token: str) -> int | None:
    """Ablauf des Anmelde-Schlüssels (Unix-Zeit) aus dem JWT, ohne Prüfung der Signatur."""
    try:
        part = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return int(data.get("exp"))
    except (IndexError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- Matchliste

def web_cookies(token: str, steamid: str, http=None) -> CookieJar:
    """Browser-Sitzung für steamcommunity.com aus dem Anmelde-Schlüssel (wie beim Login im Browser)."""
    http = http or _http
    jar = CookieJar()
    sid = secrets.token_hex(12)
    try:
        raw = http("https://login.steampowered.com/jwt/finalizelogin",
                   {"nonce": token, "sessionid": sid, "redir": "https://steamcommunity.com/login/home/?goto="}, jar)
        info = json.loads(raw)
        for t in info.get("transfer_info") or []:
            if "steamcommunity.com" in t.get("url", ""):
                http(t["url"], {**(t.get("params") or {}), "steamID": info.get("steamID") or steamid}, jar)
    except (OSError, ValueError) as exc:
        raise SteamLoginError(f"Anmeldung bei Steam abgelaufen oder abgelehnt ({exc}). Bitte neu anmelden.") from exc
    if not any(c.name == "steamLoginSecure" for c in jar):
        raise SteamLoginError("Anmeldung bei Steam abgelaufen. Bitte in den Optionen neu anmelden.")
    return jar


def demo_links(jar: CookieJar, http=None) -> dict[str, str]:
    """Match-ID -> Demo-Link aus allen Matchlisten (erste Seite je Liste: die neuesten Matches)."""
    http = http or _http
    out: dict[str, str] = {}
    for tab in TABS:
        try:
            html = http("https://steamcommunity.com/my/gcpd/730?" + urllib.parse.urlencode({"tab": tab}),
                        None, jar).decode("utf-8", "ignore")
        except OSError:
            continue
        if "g_steamID = false" in html or "login/home" in html and "g_sGcContinueToken" not in html:
            raise SteamLoginError("Anmeldung bei Steam abgelaufen. Bitte in den Optionen neu anmelden.")
        for m in REPLAY.finditer(html):
            out.setdefault(m.group(1), m.group(0))
    return out


def download(url: str, dest: Path, http_open=None) -> Path:
    """Demo laden und entpacken (.dem.bz2 -> .dem), mit Größengrenze; halbe Dateien werden gelöscht."""
    tmp = dest.with_suffix(".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = http_open or (lambda u: urllib.request.urlopen(  # noqa: S310 - nur valve.net (REPLAY)
        urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60))
    if not REPLAY.fullmatch(url):
        raise ValueError("Kein Valve-Demo-Link.")
    try:
        with opener(url) as resp, open(tmp, "wb") as out:
            dec, total = bz2.BZ2Decompressor(), 0
            while chunk := resp.read(1 << 20):
                data = dec.decompress(chunk)
                total += len(data)
                if total > MAX_BYTES:
                    raise ValueError("Demo größer als 2 GB.")
                out.write(data)
        tmp.replace(dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- Ablauf je Nutzer

def _done_file() -> Path:
    from cstaktik import autodl

    return autodl.BASE / "gcpd_done.json"


def done_ids() -> dict:
    try:
        return json.loads(_done_file().read_text())
    except (OSError, ValueError):
        return {}


def mark_done(match_id: str, note: str) -> None:
    from cstaktik.fsutil import write_atomic

    d = done_ids()
    d[match_id] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note}
    write_atomic(_done_file(), json.dumps(d))


def fetch_new(user: str, http=None, http_open=None) -> list[Path]:
    """Neue Demos des Nutzers herunterladen. Rückgabe: fertige .dem-Dateien (noch nicht ausgewertet).
    Fehler beim Login werden am Nutzer vermerkt (für die Optionen) und als SteamLoginError weitergegeben."""
    from cstaktik import accounts, autodl

    token = accounts.get_setting(f"gcpd_token:{user}")
    steamid = accounts.get_steam(user).get("steamid")
    if not token or not steamid:
        return []
    try:
        jar = web_cookies(token, steamid, http)
        links = demo_links(jar, http)
    except SteamLoginError as exc:
        accounts.set_setting(f"gcpd_error:{user}", str(exc))
        raise
    accounts.set_setting(f"gcpd_error:{user}", None)
    accounts.set_setting(f"gcpd_checked:{user}", time.strftime("%Y-%m-%dT%H:%M:%S"))
    done = done_ids()
    out = []
    for mid, url in sorted(links.items()):
        if mid in done:
            continue
        dest = autodl.DEMOS_DIR / f"match730_{mid}.dem"
        try:
            download(url, dest, http_open)
            mark_done(mid, "geladen")
            out.append(dest)
        except urllib.error.HTTPError as exc:  # abgelaufen/gelöscht (Valve hält Demos nur einige Wochen)
            mark_done(mid, f"nicht mehr bei Valve (HTTP {exc.code})")
        except (ValueError, EOFError) as exc:  # kaputt oder zu groß: nicht immer wieder laden
            mark_done(mid, f"nicht ladbar: {exc}")
        except OSError:
            continue  # Netzfehler: beim nächsten Lauf erneut
    return out
