"""Push-Nachrichten aufs Handy (Web Push), z. B. "Neues Match ausgewertet".

Standard-Web-Push ohne fremden Dienst: Der Browser des Nutzers meldet eine Adresse seines Push-Dienstes (Google, Mozilla,
Apple). Der Server schickt die Nachricht verschlüsselt dorthin (RFC 8291, aes128gcm) und weist sich mit einem eigenen
Schlüsselpaar aus (VAPID, RFC 8292). Der private Schlüssel liegt nur in der Datenbank des Servers.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
from contextlib import closing
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from cstaktik import accounts

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subs (
    endpoint TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    sub TEXT NOT NULL, created TEXT NOT NULL
);
"""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------------------------------------------------------------- Schlüssel und Abos

def _private() -> ec.EllipticCurvePrivateKey:
    """VAPID-Schlüssel des Servers (beim ersten Mal erzeugt)."""
    pem = accounts.get_setting("vapid_private")
    if pem:
        return serialization.load_pem_private_key(pem.encode(), None)
    key = ec.generate_private_key(ec.SECP256R1())
    accounts.set_setting("vapid_private", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    return key


def public_key() -> str:
    """Öffentlicher Schlüssel für den Browser (applicationServerKey)."""
    return b64u(_raw_public(_private().public_key()))


def _db():
    con = accounts.db()
    con.executescript(SCHEMA)
    return con


# Push-Dienste der Browser; andere Adressen nimmt der Server nicht an (er soll keine beliebigen Ziele aufrufen)
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")


def _push_host(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def subscribe(user: str, sub: dict) -> None:
    endpoint = sub.get("endpoint") or ""
    keys = sub.get("keys") or {}
    if not _push_host(endpoint) or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Ungültiges Push-Abo.")
    with closing(_db()) as con, con:
        con.execute("INSERT OR REPLACE INTO push_subs VALUES (?, ?, ?, ?)",
                    (endpoint, user, json.dumps({"endpoint": endpoint, "keys": keys}),
                     time.strftime("%Y-%m-%dT%H:%M:%S")))


def unsubscribe(endpoint: str, user: str | None = None) -> None:
    with closing(_db()) as con, con:
        if user is None:
            con.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
        else:
            con.execute("DELETE FROM push_subs WHERE endpoint = ? AND user = ?", (endpoint, user))


def subs(user: str) -> list[dict]:
    if not accounts.DB_FILE.exists():
        return []
    with closing(_db()) as con:
        return [json.loads(r["sub"]) for r in con.execute("SELECT sub FROM push_subs WHERE user = ?", (user,))]


# ---------------------------------------------------------------- Verschlüsseln und senden

def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Nachricht für genau dieses Gerät verschlüsseln (RFC 8291, ein Datensatz)."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    salt = salt or os.urandom(16)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_public + as_public).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + body


def _vapid_header(endpoint: str) -> str:
    key = _private()
    u = urlparse(endpoint)
    contact = accounts.get_setting("public_url") or "https://localhost"
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                              "sub": contact}).encode())
    r, s = decode_dss_signature(key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={public_key()}"


def _post(url: str, body: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - Adresse kommt vom Push-Dienst des Browsers
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def send(sub: dict, message: dict, post=None) -> int:
    """Eine Nachricht an ein Gerät. Rückgabe: HTTP-Status des Push-Dienstes (201 = angenommen)."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["keys"]["p256dh"], sub["keys"]["auth"])
    headers = {"TTL": "86400", "Urgency": "normal", "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "Authorization": _vapid_header(sub["endpoint"])}
    return (post or _post)(sub["endpoint"], body, headers)


def send_user(user: str, message: dict, post=None) -> int:
    """An alle Geräte des Nutzers. Abgelaufene Abos (404/410) werden gelöscht. Rückgabe: erfolgreich zugestellt."""
    ok = 0
    for sub in subs(user):
        try:
            status = send(sub, message, post)
        except OSError:
            continue
        if status in (404, 410):
            unsubscribe(sub["endpoint"])
        elif 200 <= status < 300:
            ok += 1
    return ok


# ---------------------------------------------------------------- Nachrichten

def match_message(h: dict, sid: str) -> dict:
    """Kurzmeldung zu einem ausgewerteten Match aus dem Verlaufs-Eintrag (nur Daten aus der Auswertung)."""
    from cstaktik.coach_voice import LESSONS
    from cstaktik.impact import de

    won, lost = h.get("won", 0), h.get("lost", 0)
    res = "gewonnen" if won > lost else "verloren" if lost > won else "unentschieden"
    label = (h.get("map") or "").removeprefix("de_").capitalize() or "Match"
    parts = []
    imp = (h.get("impact") or {}).get(sid)
    if imp and imp.get("total") is not None:
        parts.append(f"Dein Impact: {de(imp['total'] / 100)}")
    lid = h.get("main_lesson")
    if lid in LESSONS and lid != "duel":
        parts.append(f"Thema: {LESSONS[lid][0]}")
    return {"title": f"{label} {won}:{lost} {res}", "body": ". ".join(parts) or "Der Report ist fertig.",
            "url": f"/reports/{h['report_file']}" if h.get("report_file") else "/matches"}


def notify_match(h: dict, post=None) -> int:
    """Alle Nutzer, deren verbundener Steam-Account mitgespielt hat, bekommen eine Nachricht."""
    if not h or not accounts.DB_FILE.exists():
        return 0
    n = 0
    players = h.get("players") or {}
    with closing(accounts.db()) as con:
        linked = [(r["user"], r["steamid"]) for r in con.execute("SELECT user, steamid FROM steam WHERE steamid IS NOT NULL")]
    for user, sid in linked:
        if sid in players:
            n += send_user(user, match_message(h, sid), post)
    return n
