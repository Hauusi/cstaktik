"""Accounts: Login und Steam-Zugang je Nutzer, gespeichert in einer SQLite-Datenbank (data/cstaktik.db).

- Passwörter nur als Hash (PBKDF2-SHA256, 600 000 Runden, Salt je Nutzer), nie im Klartext.
- Sitzung: Cookie mit Nutzer und Ablaufzeit, signiert mit einem zufälligen Server-Schlüssel (data/secret.key).
- Steam: SteamID64, Game Authentication Code und zuletzt bekannter Match-Sharecode je Nutzer, dazu die gefundenen
  Sharecodes (steam_sync holt neue über die offizielle Steam-Web-API).
Nutzer anlegen nur auf dem Server: ``cstaktik user add NAME`` (Passwort wird verdeckt abgefragt).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_FILE = DATA_DIR / "cstaktik.db"
SECRET_FILE = DATA_DIR / "secret.key"
COOKIE = "cstaktik_session"
SESSION_DAYS = 30
PBKDF2_ROUNDS = 600_000
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")
SHARECODE_RE = re.compile(r"^CSGO(-[A-Za-z0-9]{5}){5}$")
AUTHCODE_RE = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{5}-[A-Za-z0-9]{4}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steam (
    user TEXT PRIMARY KEY REFERENCES users(name) ON DELETE CASCADE,
    steamid TEXT, auth_code TEXT, last_code TEXT, checked TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS sharecodes (
    code TEXT NOT NULL, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    found TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'neu', PRIMARY KEY (code, user)
);
"""


def db(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    con = sqlite3.connect(p)
    if new:
        p.chmod(0o600)  # enthält Passwort-Hashes und Steam-Codes: nur für den Server-Nutzer lesbar
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    from cstaktik.coaching import now_local

    return now_local()


# ---------------------------------------------------------------- Passwörter

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        algo, rounds, salt, want = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(dk.hex(), want)


def add_user(name: str, pw: str, path: Path | None = None) -> None:
    if not NAME_RE.match(name):
        raise ValueError("Name: 2 bis 32 Zeichen, nur Buchstaben, Ziffern, . _ -")
    if len(pw) < 10:
        raise ValueError("Passwort: mindestens 10 Zeichen.")
    with closing(db(path)) as con, con:
        if con.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"Nutzer {name} gibt es schon.")
        con.execute("INSERT INTO users VALUES (?, ?, ?)", (name, hash_password(pw), _now()))


def set_password(name: str, pw: str, path: Path | None = None) -> None:
    if len(pw) < 10:
        raise ValueError("Passwort: mindestens 10 Zeichen.")
    with closing(db(path)) as con, con:
        if not con.execute("UPDATE users SET pw_hash = ? WHERE name = ?", (hash_password(pw), name)).rowcount:
            raise ValueError(f"Nutzer {name} gibt es nicht.")


def verify(name: str, pw: str, path: Path | None = None) -> bool:
    with closing(db(path)) as con:
        row = con.execute("SELECT pw_hash FROM users WHERE name = ?", (name,)).fetchone()
    if row is None:
        hash_password(pw)  # gleiche Rechenzeit wie bei einem echten Nutzer: Namen nicht über die Antwortzeit erraten
        return False
    return check_password(pw, row["pw_hash"])


def has_users(path: Path | None = None) -> bool:
    p = path or DB_FILE
    if not p.exists():
        return False
    with closing(db(p)) as con:
        return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


# ---------------------------------------------------------------- Sitzung

def _secret(path: Path | None = None) -> bytes:
    p = path or SECRET_FILE
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        p.chmod(0o600)
    return p.read_bytes()


def make_session(name: str, days: int = SESSION_DAYS, secret_path: Path | None = None) -> str:
    exp = int(time.time()) + days * 86400
    body = f"{name}|{exp}"
    sig = hmac.new(_secret(secret_path), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def read_session(value: str | None, secret_path: Path | None = None) -> str | None:
    """Nutzername aus einem gültigen, nicht abgelaufenen Sitzungs-Cookie, sonst None."""
    if not value or value.count("|") != 2:
        return None
    name, exp, sig = value.split("|")
    want = hmac.new(_secret(secret_path), f"{name}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, want) or not exp.isdigit() or int(exp) < time.time():
        return None
    return name


# ---------------------------------------------------------------- Steam-Daten

def get_steam(name: str, path: Path | None = None) -> dict:
    with closing(db(path)) as con:
        row = con.execute("SELECT * FROM steam WHERE user = ?", (name,)).fetchone()
        codes = con.execute("SELECT code, found, status FROM sharecodes WHERE user = ? ORDER BY found DESC",
                            (name,)).fetchall()
    return {**(dict(row) if row else {}), "codes": [dict(c) for c in codes]}


def save_steam(name: str, steamid: str, auth_code: str, last_code: str, path: Path | None = None) -> None:
    steamid, auth_code, last_code = steamid.strip(), auth_code.strip(), last_code.strip()
    if not re.fullmatch(r"7656\d{13}", steamid):
        raise ValueError("SteamID64: 17 Ziffern, beginnt mit 7656.")
    if not AUTHCODE_RE.match(auth_code):
        raise ValueError("Game Authentication Code: Form XXXX-XXXXX-XXXX.")
    if not SHARECODE_RE.match(last_code):
        raise ValueError("Match-Token: Form CSGO-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX.")
    with closing(db(path)) as con, con:
        con.execute("INSERT INTO steam (user, steamid, auth_code, last_code) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user) DO UPDATE SET steamid = excluded.steamid, auth_code = excluded.auth_code, "
                    "last_code = excluded.last_code, error = NULL", (name, steamid, auth_code, last_code))


def steam_users(path: Path | None = None) -> list[dict]:
    with closing(db(path)) as con:
        return [dict(r) for r in con.execute("SELECT * FROM steam WHERE steamid IS NOT NULL AND auth_code IS NOT NULL "
                                             "AND last_code IS NOT NULL")]


def record_codes(name: str, codes: list[str], last: str | None, error: str | None, path: Path | None = None) -> None:
    with closing(db(path)) as con, con:
        for c in codes:
            con.execute("INSERT OR IGNORE INTO sharecodes (code, user, found) VALUES (?, ?, ?)", (c, name, _now()))
        con.execute("UPDATE steam SET checked = ?, error = ?, last_code = COALESCE(?, last_code) WHERE user = ?",
                    (_now(), error, last, name))


# ---------------------------------------------------------------- Server-Einstellungen (in der App gepflegt)

def get_setting(key: str, path: Path | None = None) -> str | None:
    p = path or DB_FILE
    if not p.exists():
        return None
    with closing(db(p)) as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str | None, path: Path | None = None) -> None:
    with closing(db(path)) as con, con:
        if value:
            con.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value))
        else:
            con.execute("DELETE FROM settings WHERE key = ?", (key,))


def steam_key(path: Path | None = None) -> str | None:
    """Steam-Web-API-Schlüssel: aus den Optionen der App, sonst aus der Umgebungsvariable STEAM_WEB_API_KEY."""
    import os

    return get_setting("steam_web_api_key", path) or os.environ.get("STEAM_WEB_API_KEY") or None


# ---------------------------------------------------------------- Steam-Verknüpfung

def link_steamid(name: str, steamid: str, path: Path | None = None) -> None:
    """SteamID aus 'Mit Steam verbinden' am Account speichern. Eine SteamID gehört höchstens zu einem Account."""
    with closing(db(path)) as con, con:
        other = con.execute("SELECT user FROM steam WHERE steamid = ? AND user != ?", (steamid, name)).fetchone()
        if other:
            raise ValueError("Dieser Steam-Account ist schon mit einem anderen Nutzer verbunden.")
        con.execute("INSERT INTO steam (user, steamid) VALUES (?, ?) "
                    "ON CONFLICT(user) DO UPDATE SET steamid = excluded.steamid", (name, steamid))


def user_by_steamid(steamid: str, path: Path | None = None) -> str | None:
    with closing(db(path)) as con:
        row = con.execute("SELECT user FROM steam WHERE steamid = ?", (steamid,)).fetchone()
    return row["user"] if row else None


def save_codes(name: str, auth_code: str, last_code: str, path: Path | None = None) -> None:
    """Game Authentication Code und Match-Token speichern (SteamID kommt aus 'Mit Steam verbinden')."""
    auth_code, last_code = auth_code.strip(), last_code.strip()
    if not AUTHCODE_RE.match(auth_code):
        raise ValueError("Game Authentication Code: Form XXXX-XXXXX-XXXX.")
    if not SHARECODE_RE.match(last_code):
        raise ValueError("Match-Token: Form CSGO-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX.")
    with closing(db(path)) as con, con:
        if not con.execute("SELECT steamid FROM steam WHERE user = ? AND steamid IS NOT NULL", (name,)).fetchone():
            raise ValueError("Erst mit Steam verbinden.")
        con.execute("UPDATE steam SET auth_code = ?, last_code = ?, error = NULL WHERE user = ?",
                    (auth_code, last_code, name))
        # das eingetragene Match selbst gehört auch dazu (die Steam-API liefert nur neuere)
        con.execute("INSERT OR IGNORE INTO sharecodes (code, user, found) VALUES (?, ?, ?)", (last_code, name, _now()))
