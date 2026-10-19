"""FastAPI: Demo-Upload, Auswertung im Hintergrund mit Fortschritt, Report-Abruf."""

from __future__ import annotations

import json
import base64
import os
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cstaktik import pipeline
from cstaktik.config import load_rules_config

app = FastAPI(title="cstaktik")


import contextvars

# SteamID des eingeloggten Nutzers (mit Steam verbunden): Seiten zeigen dann nur sein Profil
_ME: contextvars.ContextVar[str | None] = contextvars.ContextVar("cstaktik_me", default=None)


# Name des eingeloggten Nutzers (auch ohne Steam-Verbindung), None ohne Accounts
_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar("cstaktik_user", default=None)


def _me() -> str | None:
    return _ME.get()


def _visible(h: dict) -> bool:
    """Darf der eingeloggte Nutzer dieses Match sehen? Nur Matches, in denen er (mit Steam verbunden) mitgespielt
    hat. Eingeloggt ohne Steam-Verbindung: keine. Ohne Accounts (kein Login): alle."""
    if _USER.get() is None:
        return True
    me = _me()
    return bool(me) and me in (h.get("players") or {})


def _own_only(sid: str) -> None:
    """Mit Steam verbunden: nur den eigenen Plan ändern."""
    me = _me()
    if me and sid != me:
        raise HTTPException(403, "Nur dein eigener Plan.")


def _mine(sids):
    """Nur der eigene Spieler, wenn der Nutzer mit Steam verbunden ist; sonst alle (z. B. ohne Login)."""
    me = _me()
    if _USER.get() is not None and not me:  # eingeloggt, aber (noch) nicht mit Steam verbunden: niemand
        return []
    return [s for s in sids if s == me] if me else list(sids)


_SEEN_LOCK = threading.RLock()


def _seen(user: str | None) -> tuple[str, list[str]] | None:
    """Gesehene Reports des Nutzers: (seit wann gezählt wird, Dateinamen). Ältere Matches gelten als gesehen,
    sonst wäre beim ersten Mal alles "neu"."""
    if not user:
        return None
    from cstaktik import accounts

    raw = accounts.get_setting(f"seen:{user}")
    try:
        d = json.loads(raw) if raw else None
    except ValueError:
        d = None
    if not d:
        with _SEEN_LOCK:
            raw = accounts.get_setting(f"seen:{user}")  # gleichzeitiger erster Aufruf: nicht überschreiben
            d = json.loads(raw) if raw else {"since": pipeline.coaching_now(), "files": []}
            if not raw:
                accounts.set_setting(f"seen:{user}", json.dumps(d))
    return d["since"], list(d.get("files") or [])


def _mark_seen(user: str, file: str) -> None:
    from cstaktik import accounts

    with _SEEN_LOCK:
        since, files = _seen(user)
        if file not in files:
            keep = files[-499:] + [file]  # begrenzt, älteste zuerst raus; ältere fallen ohnehin unter "since"
            accounts.set_setting(f"seen:{user}", json.dumps({"since": since, "files": keep}))


def _is_new(h: dict, seen: tuple[str, list[str]] | None) -> bool:
    return bool(seen and h.get("report_file") and (h.get("analyzed_at") or "") > seen[0]
                and h["report_file"] not in seen[1])


async def _personal_report(resp: Response, me: str) -> Response:
    """Report (fertige HTML-Datei) für den eingeloggten Spieler: SteamID einsetzen, die Seite blendet die Teile
    anderer Spieler aus. Die Datei selbst bleibt unverändert."""
    body = b"".join([chunk async for chunk in resp.body_iterator])
    tag = f'<script>window.__ME="{me}";</script></head>'.encode()
    body = body.replace(b"</head>", tag, 1)
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "etag", "last-modified")}
    return Response(body, status_code=resp.status_code, headers=headers)


_PUBLIC = {"/login", "/fonts.css", "/setup", "/auth/steam", "/auth/steam/callback", "/manifest.webmanifest", "/sw.js",
           "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"}
_FAILS: dict[tuple, list[float]] = {}  # Login-Fehlversuche je IP und Name (Schutz gegen Durchprobieren)


@app.middleware("http")
async def _password(request: Request, call_next):
    """Optionaler Passwortschutz (HTTP Basic) für alle Seiten inkl. Reports.

    Aktiv, wenn die Umgebungsvariable CSTAKTIK_PASSWORD gesetzt ist (Benutzer: CSTAKTIK_USER, Standard "coach").
    """
    redirect = _https_only(request)
    if redirect is not None:
        return redirect
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        # eigene Adresse: Host, hinter einem Proxy auch X-Forwarded-Host, zusätzlich CSTAKTIK_ALLOWED_HOSTS
        hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", "")}
        hosts |= {h.strip() for h in os.environ.get("CSTAKTIK_ALLOWED_HOSTS", "").split(",") if h.strip()}
        if origin and urlparse(origin).netloc not in hosts - {""}:  # "null" (Sandbox) gilt als fremd
            return Response("Fremde Herkunft", status_code=403)
    from cstaktik import accounts

    if accounts.has_users():  # Accounts angelegt: Login über die Seite /login, Sitzung im Cookie
        user = accounts.read_session(request.cookies.get(accounts.COOKIE))
        if user or request.url.path in _PUBLIC:
            request.state.user = user
            me = (accounts.get_steam(user).get("steamid") or None) if user else None
            _ME.set(me)
            _USER.set(user)
            m = re.fullmatch(r"/reports/([^/]+\.html)", request.url.path)
            if user and m and not _report_visible(m.group(1)):  # fremdes Match: gibt es für diesen Nutzer nicht
                return Response("Report nicht gefunden.", status_code=404)
            if me and request.url.path.startswith("/reports/"):  # keine 304 aus dem Cache: die Seite wird angepasst
                request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                            if k not in (b"if-none-match", b"if-modified-since")]
            resp = await call_next(request)
            if user and m and resp.status_code == 200:
                _mark_seen(user, m.group(1))
            if me and request.url.path.startswith("/reports/") and resp.headers.get("content-type", "").startswith("text/html"):
                return await _personal_report(resp, me)
            return resp
        if request.method == "GET" and not request.url.path.startswith("/api/"):
            from urllib.parse import quote

            return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
        return Response("Login erforderlich", status_code=401)
    request.state.user = None
    password = os.environ.get("CSTAKTIK_PASSWORD")  # alter Schutz per Browser-Dialog, solange es keine Accounts gibt
    if not password:
        return await call_next(request)
    user = os.environ.get("CSTAKTIK_USER", "coach")
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            got_user, _, got_pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            got_user, got_pw = "", ""
        if secrets.compare_digest(got_user.encode(), user.encode()) and secrets.compare_digest(
            got_pw.encode(), password.encode()
        ):
            return await call_next(request)
    return Response("Login erforderlich", status_code=401, headers={"WWW-Authenticate": 'Basic realm="cstaktik"'})

pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=pipeline.REPORTS_DIR, html=True), name="reports")
_env = Environment(loader=FileSystemLoader([Path(__file__).parent / "web", Path(__file__).parent / "report" / "templates"]),
                   autoescape=select_autoescape(["html"]))
_env.globals["font_css"] = lambda: __import__("cstaktik.fonts", fromlist=["font_css"]).font_css()
__import__("cstaktik.callouts", fromlist=["register"]).register(_env)
_env.globals["callouts_js"] = __import__("cstaktik.callouts", fromlist=["JS"]).JS


class _GoalCfg:
    """Auftrags-Schwellen aus rules.yaml für die Texte (immer aktuell, keine festen Zahlen im Template)."""

    def __getattr__(self, name: str):
        return load_rules_config()["goals"].get(name, {"min_count": 3, "min_master_rounds": 40}.get(name))


_env.globals["goal_cfg"] = _GoalCfg()

# Auswertung läuft im Hintergrund: Der Browser muss nach dem Upload nicht offen bleiben.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_SCORE = re.compile(r"^(.*?)\s+(\d+):(\d+)\s+–")


def _same_unpacked(packed: Path, dem: Path, suffix: str) -> bool:
    """Ist die gepackte Datei entpackt identisch mit ``dem``? Blockweise, ohne Zwischendatei."""
    try:
        with pipeline.open_packed(packed, suffix) as a, dem.open("rb") as b:
            while True:
                x, y = a.read(1 << 20), b.read(1 << 20)
                if x != y:
                    return False
                if not x:
                    return True
    except Exception:  # noqa: BLE001 - kaputt oder anderes Format: nicht dieselbe Demo
        return False


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pipeline.demo_stem(Path(name).name)).strip("._") or "demo"
    return stem[:80]


def _report_entries() -> list[dict]:
    """Reports für die Startseite; Map und Ergebnis kommen aus dem <title> des Reports."""
    out = []
    for p in sorted(pipeline.REPORTS_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.name == "fortschritt.html":  # CLI-Export der Fortschritts-Seite, kein Match
            continue
        with p.open(encoding="utf-8", errors="ignore") as fh:
            head = fh.read(4096)
        m = _TITLE.search(head)
        s = _SCORE.match(m.group(1).strip()) if m else None
        out.append(
            {
                "file": p.name,
                "name": p.stem,
                "map": s.group(1) if s else None,
                "won": int(s.group(2)) if s else None,
                "lost": int(s.group(3)) if s else None,
                "date": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            }
        )
    return out


def _job_view(job_id: str, job: dict) -> dict:
    return {
        "id": job_id,
        "name": job["name"],
        "status": job["status"],
        "stage": job["stage"],
        "frac": round(job["frac"], 3),
        "elapsed": round(time.monotonic() - job["started"], 1) if job["started"] else 0.0,
        "estimate": job["estimate"],
        "samples": job["samples"],
        "cached": job["cached"],
        "report": job["report"],
        "message": job.get("message"),
        "links": job.get("links") or [],
        "error": job["error"],
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/", error: str = "") -> str:
    from cstaktik import accounts

    return _env.get_template("login.html").render(next=next if next.startswith("/") else "/", error=error,
                                                  setup=not accounts.has_users())


@app.post("/setup")
async def setup_post(request: Request) -> Response:
    """Ersten Account anlegen, nur solange es noch keinen gibt (danach legen eingeloggte Nutzer weitere an)."""
    from urllib.parse import quote

    from cstaktik import accounts

    if accounts.has_users():
        raise HTTPException(403, "Es gibt schon Accounts.")
    form = await request.form()
    name, pw, pw2 = str(form.get("name", "")).strip(), str(form.get("password", "")), str(form.get("password2", ""))
    if pw != pw2:
        return RedirectResponse("/login?error=" + quote("Passwörter stimmen nicht überein."), status_code=303)
    try:  # Passwort-Hash rechnet ~0,5 s: nicht im Event-Loop, sonst steht die ganze App
        await run_in_threadpool(accounts.add_user, name, pw)
    except ValueError as exc:
        return RedirectResponse("/login?error=" + quote(str(exc)), status_code=303)
    return _session_redirect(request, name, "/konto?saved=" + quote("Account angelegt. Jetzt mit Steam verbinden."))


def _session_redirect(request: Request, name: str, to: str) -> Response:
    from cstaktik import accounts

    r = RedirectResponse(to, status_code=303)
    r.set_cookie(accounts.COOKIE, accounts.make_session(name), max_age=accounts.SESSION_DAYS * 86400, httponly=True,
                 samesite="lax", secure=_base(request).startswith("https"))
    return r


def _https_only(request: Request) -> Response | None:
    """Läuft die App hinter einem HTTPS-Proxy (Caddy auf demselben Server), gilt nur noch der verschlüsselte Weg.

    Kommt eine Anfrage verschlüsselt über den Proxy, merkt sich die App ihre HTTPS-Adresse. Danach
    werden direkte Zugriffe von außen (z. B. http://IP:8000) dorthin umgeleitet, damit Passwörter nie unverschlüsselt
    übertragen werden. Zurücksetzen auf dem Server: ``cstaktik https-adresse --aus``."""
    from cstaktik import accounts

    # Hinter Caddy setzt uvicorn das Schema aus X-Forwarded-Proto, aber nur für Anfragen vom Proxy auf demselben
    # Server (forwarded_allow_ips=127.0.0.1). Ein direkter Aufruf von außen bleibt "http", egal welche Header er schickt.
    if request.url.scheme == "https":
        host = request.headers.get("host", "")
        url = f"https://{host}"
        # nur mit gültigem Login merken: sonst könnte jeder per Host-Header eine fremde Adresse eintragen
        if (host and re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", host) and accounts.get_setting("public_url") != url
                and accounts.read_session(request.cookies.get(accounts.COOKIE))):
            accounts.set_setting("public_url", url)
        return None
    url = accounts.get_setting("public_url")
    if not url:
        return None
    if request.method in ("GET", "HEAD"):
        target = url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(target, status_code=307)
    return Response(f"Bitte über {url} aufrufen (verschlüsselt).", status_code=403)


def _base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{host}"


@app.get("/auth/steam")
def steam_start(request: Request) -> Response:
    """Zu Steam weiterleiten. Eingeloggt: Steam mit dem Account verbinden; sonst: mit Steam einloggen."""
    from cstaktik import steam_openid

    state = secrets.token_urlsafe(16)
    base = _base(request)
    r = RedirectResponse(steam_openid.login_url(f"{base}/auth/steam/callback?state={state}", base), status_code=303)
    r.set_cookie("cstaktik_steam_state", state, max_age=600, httponly=True, samesite="lax",
                 secure=base.startswith("https"))
    return r


@app.get("/auth/steam/callback")
def steam_callback(request: Request) -> Response:
    from urllib.parse import quote

    from cstaktik import accounts, steam_openid

    state = request.query_params.get("state", "")
    want = request.cookies.get("cstaktik_steam_state", "")
    params = dict(request.query_params)
    sid = None
    if state and want and secrets.compare_digest(state.encode(), want.encode()):
        sid = steam_openid.verify(params, f"{_base(request)}/auth/steam/callback?state={state}")
    user = accounts.read_session(request.cookies.get(accounts.COOKIE))
    if not sid:
        to = "/konto" if user else "/login"
        return RedirectResponse(f"{to}?error=" + quote("Steam-Anmeldung nicht bestätigt. Bitte erneut versuchen."),
                                status_code=303)
    if user:  # verbinden
        before = accounts.linked_steamids()
        try:
            accounts.link_steamid(user, sid)
        except ValueError as exc:
            return RedirectResponse("/konto?error=" + quote(str(exc)), status_code=303)
        msg = "Mit Steam verbunden."
        if accounts.linked_steamids() != before and _load_hist():
            # ausgewertet werden nur verbundene Spieler: bisherige Matches für die neue Auswahl neu berechnen
            _start_rerender()
            msg += " Deine Matches werden jetzt neu ausgewertet. Das dauert ein paar Minuten."
        r = RedirectResponse("/konto?saved=" + quote(msg), status_code=303)
    else:  # einloggen: nur, wenn dieser Steam-Account mit einem Nutzer verbunden ist
        name = accounts.user_by_steamid(sid)
        if not name:
            return RedirectResponse("/login?error=" + quote("Dieser Steam-Account gehört zu keinem Nutzer. "
                                                            "Erst mit Name und Passwort einloggen. Dann in den "
                                                            "Optionen mit Steam verbinden."), status_code=303)
        r = _session_redirect(request, name, "/")
    r.delete_cookie("cstaktik_steam_state")
    return r


@app.post("/login")
async def login_post(request: Request) -> Response:
    from urllib.parse import quote

    from cstaktik import accounts

    form = await request.form()
    name, pw = str(form.get("name", "")).strip(), str(form.get("password", ""))
    nxt = str(form.get("next", "/"))
    nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
    ip = request.client.host if request.client else "?"
    now = time.time()
    for k in [k for k, v in _FAILS.items() if not v or now - v[-1] >= 900]:  # alte Einträge aufräumen
        _FAILS.pop(k, None)
    key = (ip, name.lower())  # je Name: hinter einem Proxy sperrt ein Fremder sonst alle aus
    fails = [t for t in _FAILS.get(key, []) if now - t < 900]
    if len(fails) >= 10:
        return RedirectResponse(f"/login?next={quote(nxt)}&error=" + quote("Zu viele Versuche. Bitte in 15 Minuten erneut versuchen."),
                                status_code=303)
    if not await run_in_threadpool(accounts.verify, name, pw):
        _FAILS[key] = fails + [now]
        return RedirectResponse(f"/login?next={quote(nxt)}&error=" + quote("Name oder Passwort falsch."), status_code=303)
    _FAILS.pop(key, None)
    return _session_redirect(request, name, nxt)


@app.post("/logout")
def logout() -> Response:
    from cstaktik import accounts

    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(accounts.COOKIE)
    return r


@app.get("/konto", response_class=HTMLResponse)
def konto_page(request: Request, saved: str = "", error: str = "") -> str:
    from cstaktik import accounts

    user = getattr(request.state, "user", None)
    key = accounts.steam_key()
    from cstaktik import autodl

    return _env.get_template("konto.html").render(
        nav_active="settings", user=user, steam=accounts.get_steam(user) if user else None, saved=saved, error=error,
        has_key=bool(key), key_hint=f"…{key[-4:]}" if key else None, autodl=autodl.status(),
        bot_user=accounts.get_setting("autodl_bot_user"), docker_cmd=autodl.docker_command())


def _need_user(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Erst einloggen.")
    return user


@app.post("/konto")
async def konto_save(request: Request) -> Response:
    from urllib.parse import quote

    from cstaktik import accounts, steam_sync

    user = _need_user(request)
    form = await request.form()
    try:
        accounts.save_codes(user, str(form.get("auth_code", "")), str(form.get("last_code", "")))
    except ValueError as exc:
        return RedirectResponse("/konto?error=" + quote(str(exc)), status_code=303)
    row = next((r for r in accounts.steam_users() if r["user"] == user), None)
    res = await run_in_threadpool(steam_sync.sync_user, row) if row else {"new": 0, "error": None}
    from cstaktik import autodl

    autodl.write_config()
    msg = _sync_msg(res)
    return RedirectResponse("/konto?saved=" + quote(msg), status_code=303)


def _sync_msg(res: dict) -> str:
    if res["error"]:
        return f"{res['new']} neue Matches gefunden. {res['error']}"
    if not res["new"]:
        return ("Die Verbindung zu Steam klappt. Nach deinem Match-Token gibt es noch kein neues Match. "
                "Steam meldet nur neuere Matches. Dein nächstes erscheint hier. Der Coach prüft alle 30 Minuten.")
    return (f"{res['new']} neue{'s' if res['new'] == 1 else ''} Match{'es' if res['new'] != 1 else ''} gefunden. "
            "Die Demo lädt der Coach noch nicht selbst herunter. Lade sie in CS2 unter „Sehen“ → „Deine Matches“ "
            "herunter und lade die Datei auf der Startseite hoch.")


@app.post("/konto/key")
async def konto_key(request: Request) -> Response:
    """Steam-Web-API-Schlüssel des Servers in der App setzen (leer = entfernen)."""
    from urllib.parse import quote

    from cstaktik import accounts

    _need_user(request)
    key = str((await request.form()).get("key", "")).strip()
    if key and not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
        return RedirectResponse("/konto?error=" + quote("Der Schlüssel hat 32 Zeichen: 0–9 und A–F."), status_code=303)
    accounts.set_setting("steam_web_api_key", key.upper() or None)
    from cstaktik import autodl

    autodl.write_config()
    return RedirectResponse("/konto?saved=" + quote("Schlüssel gespeichert." if key else "Schlüssel entfernt."),
                            status_code=303)


@app.post("/konto/user")
async def konto_add_user(request: Request) -> Response:
    """Weiteren Nutzer anlegen (z. B. für den Duo-Partner)."""
    from urllib.parse import quote

    from cstaktik import accounts

    _need_user(request)
    form = await request.form()
    try:
        await run_in_threadpool(accounts.add_user, str(form.get("name", "")).strip(), str(form.get("password", "")))
    except ValueError as exc:
        return RedirectResponse("/konto?error=" + quote(str(exc)), status_code=303)
    return RedirectResponse("/konto?saved=" + quote(f"Nutzer {form.get('name')} angelegt."), status_code=303)


@app.post("/konto/passwort")
async def konto_password(request: Request) -> Response:
    from urllib.parse import quote

    from cstaktik import accounts

    user = _need_user(request)
    form = await request.form()
    if not await run_in_threadpool(accounts.verify, user, str(form.get("old", ""))):
        return RedirectResponse("/konto?error=" + quote("Altes Passwort stimmt nicht."), status_code=303)
    try:
        await run_in_threadpool(accounts.set_password, user, str(form.get("new", "")))
    except ValueError as exc:
        return RedirectResponse("/konto?error=" + quote(str(exc)), status_code=303)
    # alte Sitzungen sind damit ungültig (Passwort steckt in der Signatur): diese hier neu ausstellen
    return _session_redirect(request, user, "/konto?saved=" + quote("Passwort geändert. Andere Geräte sind abgemeldet."))


@app.post("/konto/sync")
def konto_sync(request: Request) -> Response:
    from urllib.parse import quote

    from cstaktik import accounts, steam_sync

    user = getattr(request.state, "user", None)
    row = next((r for r in accounts.steam_users() if r["user"] == user), None)
    if not row:
        return RedirectResponse("/konto?error=" + quote("Erst Steam-Daten eintragen."), status_code=303)
    res = steam_sync.sync_user(row)
    msg = _sync_msg(res)
    return RedirectResponse("/konto?saved=" + quote(msg), status_code=303)


@app.post("/konto/bot")
async def konto_bot(request: Request) -> Response:
    """Bot-Account für den automatischen Demo-Download speichern (leerer Name = entfernen)."""
    from urllib.parse import quote

    from cstaktik import accounts, autodl

    _need_user(request)
    form = await request.form()
    name, pw = str(form.get("bot_user", "")).strip(), str(form.get("bot_pass", ""))
    secret = str(form.get("bot_secret", "")).strip()
    if not name:
        for k in ("autodl_bot_user", "autodl_bot_pass", "autodl_bot_secret"):
            accounts.set_setting(k, None)
        autodl.write_config()  # löscht die Konfiguration: der Container lädt nichts mehr
        return RedirectResponse("/konto?saved=" + quote("Bot-Account entfernt."), status_code=303)
    accounts.set_setting("autodl_bot_user", name)
    if pw:  # leer lassen = altes Passwort behalten
        accounts.set_setting("autodl_bot_pass", pw)
    if secret or form.get("bot_secret_clear"):
        accounts.set_setting("autodl_bot_secret", secret or None)
    ok = autodl.write_config()
    msg = ("Bot-Account gespeichert. Der Download startet beim nächsten Lauf." if ok else
           "Bot-Account gespeichert. Es fehlt noch etwas: Passwort, Steam-Web-API-Schlüssel oder deine Match-Daten.")
    return RedirectResponse("/konto?saved=" + quote(msg), status_code=303)


def _autodl_import() -> int:
    """Fertig heruntergeladene Demos übernehmen und auswerten (wie ein Upload, ohne Besitzer: sichtbar für alle,
    die im Match mitgespielt haben)."""
    from cstaktik import autodl

    n = 0
    for p in autodl.ready_demos():
        try:
            target = autodl.take(p)
        except OSError as exc:
            autodl.record(p.name, f"Konnte nicht übernommen werden: {exc}")
            continue
        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {"owner": None, "status": "wartet", "name": f"Automatisch geladen: {target.stem}",
                             "stage": "Wartet", "frac": 0.0, "started": None, "estimate": None, "samples": 0,
                             "cached": False, "report": None, "error": None}

        def run(job_id=job_id, target=target):
            _run_job(job_id, target, None)
            with _jobs_lock:
                err, report = _jobs[job_id].get("error"), _jobs[job_id].get("report")
            autodl.record(target.name, err)
            if report and not err:
                _notify_report(report)

        _executor.submit(run)
        n += 1
    return n


def _notify_report(report: str) -> None:
    """Push-Nachricht an alle, die im gerade ausgewerteten Match mitgespielt haben (Fehler stoppen nichts)."""
    from cstaktik import history, notify

    try:
        hist = history.load_all(pipeline.HISTORY_DIR)
        h = next((x for x in hist if x.get("report_file") == report), None)
        notify.notify_match(h, hist=hist)
    except Exception:  # noqa: BLE001 - eine fehlgeschlagene Nachricht darf die Auswertung nicht stören
        pass


@app.on_event("startup")
def _start_autodl() -> None:
    """Jede Minute nach automatisch geladenen Demos schauen; alle 10 Minuten die Konfiguration auffrischen."""
    from cstaktik import autodl

    def loop():
        i = 0
        while True:
            try:
                if i % 10 == 0:
                    autodl.write_config()
                _autodl_import()
            except Exception:  # noqa: BLE001 - darf den Server nie stoppen
                pass
            i += 1
            time.sleep(autodl.SCAN_S)

    threading.Thread(target=loop, daemon=True, name="autodl").start()


@app.on_event("startup")
def _start_steam_sync() -> None:
    """Alle 30 Minuten neue Sharecodes für alle Nutzer mit Steam-Daten holen (sobald ein Schlüssel eingetragen ist)."""
    from cstaktik import accounts, steam_sync

    def loop():
        while True:
            try:
                if accounts.steam_key():
                    steam_sync.sync_all()
            except Exception:  # noqa: BLE001 - der Abruf darf den Server nie stoppen
                pass
            time.sleep(steam_sync.INTERVAL_S)

    threading.Thread(target=loop, daemon=True, name="steam-sync").start()


@app.get("/fonts.css")
def fonts_css() -> Response:
    """Schriften einmal laden und im Browser cachen, statt sie in jede Seite einzubetten (spart ~180 KB je Seite).
    Die Reports betten sie weiter selbst ein, damit sie als einzelne Datei funktionieren."""
    from cstaktik.fonts import font_css

    import hashlib

    css = font_css()
    # ohne geladene Schriften nicht cachen, sonst bleibt die Systemschrift eine Woche, auch wenn sie später da sind
    cache = "public, max-age=604800" if css else "no-cache"
    etag = '"' + hashlib.sha1(css.encode()).hexdigest()[:16] + '"'
    return Response(css, media_type="text/css", headers={"Cache-Control": cache, "ETag": etag})


_STATIC = Path(__file__).parent / "static"


@app.get("/manifest.webmanifest")
def manifest() -> Response:
    """Damit sich der Coach wie eine App auf den Startbildschirm legen lässt."""
    data = {"name": "cstaktik CS2-Coach", "short_name": "Coach", "lang": "de", "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": "#0b0d12", "theme_color": "#0b0d12",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}
    return Response(json.dumps(data), media_type="application/manifest+json")


@app.get("/{name}.png", include_in_schema=False)
def app_icon(name: str) -> Response:
    if name not in ("icon-192", "icon-512", "apple-touch-icon"):
        raise HTTPException(404)
    return Response((_STATIC / f"{name}.png").read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


_SW = """self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {body: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.title || 'cstaktik', {
    body: d.body || '', icon: '/icon-192.png', badge: '/icon-192.png', data: {url: d.url || '/'}, tag: d.url || 'cstaktik'}));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    const same = list.find(c => new URL(c.url).pathname === url);
    if (same) return same.focus();
    const c = list.find(c => 'navigate' in c);
    if (!c) return clients.openWindow(url);
    return c.navigate(url).then(w => (w || c).focus()).catch(() => clients.openWindow(url));
  }));
});
"""


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    return Response(_SW, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/push/key")
def push_key(request: Request) -> JSONResponse:
    from cstaktik import notify

    _need_user(request)
    return JSONResponse({"key": notify.public_key()})


@app.post("/push/subscribe")
async def push_subscribe(request: Request) -> JSONResponse:
    from cstaktik import notify

    user = _need_user(request)
    try:
        body = await request.json()
        owner = notify.owner(str(body.get("endpoint") or ""))
        if owner and owner != user and not body.get("take"):  # Gerät gehört einem anderen Nutzer: nicht still umhängen
            return JSONResponse({"ok": False, "owner": owner}, status_code=409)
        notify.subscribe(user, body)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, "Ungültiges Push-Abo.") from exc
    return JSONResponse({"ok": True})


@app.post("/push/unsubscribe")
async def push_unsubscribe(request: Request) -> JSONResponse:
    from cstaktik import notify

    user = _need_user(request)
    try:
        endpoint = str((await request.json()).get("endpoint") or "")
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "Ungültige Anfrage.") from exc
    notify.unsubscribe(endpoint, user)
    return JSONResponse({"ok": True})


@app.post("/push/test")
def push_test(request: Request) -> JSONResponse:
    from cstaktik import notify

    user = _need_user(request)
    n = notify.send_user(user, {"title": "Benachrichtigungen aktiv",
                                "body": "Ab jetzt meldet sich der Coach, sobald ein neues Match ausgewertet ist.",
                                "url": "/"})
    return JSONResponse({"sent": n})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Startseite: nur zwei Dinge. Oben das neue Match (oder eine Zeile zum letzten), darunter der Fokus fürs
    nächste Match mit den Übungen dieser Woche. Alles andere liegt unter Training, Matches und Fortschritt."""
    from cstaktik import weekplan
    from cstaktik.config import load_focus_steamids

    jobs = _running_jobs()
    hist = _load_hist()
    # eingestellter Spieler, der im letzten Match nicht vorkommt: der Coach sieht ihn nicht -> Hinweis
    missing = len(set(_mine(load_focus_steamids())) - set((hist[-1].get("players") or {}) if hist else ()))
    names = _names(hist)
    auftrag = _auftrag(hist)
    _ensure_weekplans(hist, [a["sid"] for a in auftrag])
    key = weekplan.week_key(weekplan.local_today())
    players = _players_state()
    for a in auftrag:  # Übungen dieser Woche als kurze Checkliste (Haken über /training/plan)
        plan = ((players.get(a["sid"]) or {}).get("weeks") or {}).get(key)
        if plan and plan.get("lesson") == a["lesson"] and plan.get("tasks"):
            done = plan.get("done") or {}
            a["week"] = {"key": key, "tasks": [{**t, "done": t["id"] in done} for t in plan["tasks"]],
                         "done": sum(1 for t in plan["tasks"] if t["id"] in done), "total": len(plan["tasks"])}
    seen = _seen(_USER.get())
    from cstaktik import autodl

    try:
        auto = bool(autodl.status()["config"])
    except Exception:  # noqa: BLE001 - ohne Download-Konfiguration bleibt es beim Hochladen
        auto = False
    news = [_last_view(h) for h in reversed(hist) if _is_new(h, seen)]  # noch nicht geöffnet, neueste zuerst
    deal = _deal_view(hist)
    push_hint = False
    if _USER.get() and _me():  # erst nach der Steam-Verbindung: vorher kommt ohnehin keine Nachricht
        from cstaktik import notify

        push_hint = not notify.subs(_USER.get())
    return _env.get_template("index.html").render(
        nav_active="coach", jobs=jobs, n_history=len(hist), last=_last_view(hist[-1]) if hist else None,
        news=news[:6], n_new=len(news), auftrag=auftrag, missing_players=missing if hist else 0,
        me_name=names.get(_me()) if _me() else None,
        need_link=_USER.get() is not None and not _me(),
        auto=auto and bool(hist), push_hint=push_hint, deal=deal,
    )


def _ensure_weekplans(hist: list[dict], sids: list[str]) -> None:
    """Wochenplan der aktuellen Woche anlegen, falls er fehlt oder der Auftrag gewechselt hat (sonst nichts tun:
    der Plan wird nur gebaut, wenn es nötig ist). So zeigt die Startseite den Fortschritt auch ohne Besuch auf
    /training, z. B. nach einer automatischen Auswertung."""
    from cstaktik import coaching, weekplan

    key = weekplan.week_key(weekplan.local_today())
    players = _players_state()
    todo = [sid for sid in sids if (players.get(sid) or {}).get("focus")
            and ((players[sid].get("weeks") or {}).get(key) or {}).get("lesson") != players[sid]["focus"]["lesson"]]
    if not todo:
        return
    pro_all = _load_pro()
    for sid in todo:
        try:
            ctx = _plan_ctx(hist, pro_all, sid, players[sid]["focus"])  # außerhalb der Sperre (liest nur)
            with coaching.LOCK:  # frisch laden: Haken, die inzwischen gesetzt wurden, bleiben erhalten
                state = coaching.load(pipeline.COACHING_FILE)
                slot = state.get("players", {}).get(sid)
                if not slot or (slot.get("focus") or {}).get("lesson") != ctx["lesson"]:
                    continue
                if weekplan.ensure(slot, ctx)[2]:
                    coaching.save(state, pipeline.COACHING_FILE)
        except Exception:  # noqa: BLE001 - ein fehlender Plan darf die Startseite nicht verhindern
            continue


def _last_view(h: dict) -> dict:
    """Ein Match für die Startseite: Ergebnis, Datum, Thema. Mit Steam verbunden: aus Sicht des eigenen Spielers
    (seine Seite, sein Thema), sonst fürs Team."""
    from cstaktik import history
    from cstaktik.coach_voice import LESSONS

    me = _me() if _me() in (h.get("players") or {}) else None
    sc = history.score(h, me)  # None: kein Ergebnis aus seiner Sicht bekannt, dann keins zeigen
    won, lost = sc if sc else (None, None)
    lid = history.lead(h, me)
    try:
        when = datetime.fromisoformat(h["analyzed_at"]).strftime("%d.%m. %H:%M")
    except (KeyError, ValueError, TypeError):
        when = None
    return {**h, "won": won, "lost": lost,
            "result": None if sc is None else "Sieg" if won > lost else "Niederlage" if lost > won else "Unentschieden",
            "res": None if sc is None else "w" if won > lost else "l" if lost > won else "d", "when": when,
            "map_label": (h.get("map") or "?").removeprefix("de_").capitalize(),
            "topic": LESSONS[lid][0] if lid in LESSONS and lid != "duel" else None}


def _running_jobs() -> list[dict]:
    with _jobs_lock:
        return [_job_view(i, j) for i, j in _jobs.items() if j["status"] in ("wartet", "läuft") and _own_job(j)]


def _own_job(job: dict) -> bool:
    """Uploads sieht nur, wer sie hochgeladen hat; Hintergrund-Aufträge (Neuberechnen, FACEIT) alle."""
    return job.get("owner") is None or _USER.get() is None or job["owner"] == _USER.get()


@app.get("/matches", response_class=HTMLResponse)
def matches_page() -> str:

    from cstaktik.coach_voice import LESSONS

    hist = _load_hist()
    by_file = {h.get("report_file"): h for h in hist if h.get("report_file")}
    reports = _report_entries()
    if _USER.get() is not None:  # eingeloggt: nur Reports der eigenen Matches
        reports = [r for r in reports if r["file"] in by_file]
    for r in reports:  # Datum und Hauptthema aus dem Verlauf: die Dateizeit ändert sich bei jedem Neubau der Reports
        h = by_file.get(r["file"])
        if h and h.get("analyzed_at"):
            r["date"] = datetime.fromisoformat(h["analyzed_at"]).strftime("%d.%m.%Y %H:%M")
            r["sort"] = h["analyzed_at"]
            from cstaktik import history

            me = _me() if _me() in (h.get("players") or {}) else None
            lid = history.lead(h, me)
            r["topic"] = LESSONS[lid][0] if lid in LESSONS and lid != "duel" else None
            if me:  # Ergebnis aus Sicht des eigenen Spielers (falls ihr gegeneinander gespielt habt)
                r["won"], r["lost"] = history.score(h, me) or (None, None)
            from cstaktik.impact import de

            r["imp"] = [{"name": (h.get("players", {}).get(sid) or {}).get("name", sid), "v": de(x["total"] / 100),
                         "pos": x["total"] > 0, "rank": x.get("rank"), "of": x.get("of")}
                        for sid, x in sorted((h.get("impact") or {}).items()) if _mine([sid])]
        if r.get("won") is not None:
            r["res"] = "w" if r["won"] > r["lost"] else "l" if r["lost"] > r["won"] else "d"
    seen = _seen(_USER.get())
    for r in reports:
        r["new"] = _is_new(by_file.get(r["file"]) or {}, seen)
    reports.sort(key=lambda r: r.get("sort") or "", reverse=True)
    return _env.get_template("matches.html").render(nav_active="matches", jobs=_running_jobs(),
                                                    reports=reports, n_history=len(hist))


def _focus_entry(fc: dict | None, sid: str) -> dict | None:
    """Auftrags-Ergebnis dieses Spielers aus ``focus_check``; altes Format (ein gemeinsamer Auftrag) gilt für alle."""
    if not fc:
        return None
    if "check" in fc or "focus" in fc and not any(isinstance(v, dict) and "check" in v for v in fc.values()):
        return fc
    v = fc.get(sid)
    return v if isinstance(v, dict) else None


REGULATION_ROUNDS = 24  # MR12: danach Overtime


def _minute_sides(h: dict, sid: str) -> list[dict] | None:
    """T/CT-Aufteilung aus Sicht des Spielers (Runden, Kills, Tode) plus Overtime. Nur wenn die Summen zu seinen
    Kills und Toden im Verlauf passen (sonst lieber nichts zeigen)."""
    rows = (h.get("by_round") or {}).get(sid)
    p = (h.get("players") or {}).get(sid) or {}
    if not rows or sum(r[3] for r in rows) != p.get("kills") or sum(r[4] for r in rows) != p.get("deaths"):
        return None
    out = []
    for label, pick in (("T-Seite", lambda r: r[0] <= REGULATION_ROUNDS and r[1] == "t"),
                        ("CT-Seite", lambda r: r[0] <= REGULATION_ROUNDS and r[1] == "ct"),
                        ("Overtime", lambda r: r[0] > REGULATION_ROUNDS)):
        rs = [r for r in rows if pick(r)]
        if rs:
            out.append({"label": label, "won": sum(1 for r in rs if r[2]), "lost": sum(1 for r in rs if r[2] is False),
                        "k": sum(r[3] for r in rs), "d": sum(r[4] for r in rs)})
    return out


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _minute_player(h: dict, sid: str) -> dict:
    """Ein Spieler in der Match-Story: nur Werte, die im Verlaufs-Eintrag stehen. Fehlt etwas, bleibt das Feld leer
    und die Seite lässt den Block weg. Zahlen in Worten des Spielers (Tode, Runden), nicht als Raten."""
    from cstaktik import history
    from cstaktik.coach_voice import DEATH_PHRASE, LESSONS
    from cstaktik.curriculum import TEACH
    from cstaktik.impact import de

    sc = history.score(h, sid)
    p = (h.get("players") or {}).get(sid) or {}
    out = {"sid": sid, "name": p.get("name", sid)}
    if sc:  # ohne Ergebnis aus seiner Sicht keins zeigen
        won, lost = sc
        out.update(won=won, lost=lost, res="w" if won > lost else "l" if lost > won else "d",
                   result="Sieg" if won > lost else "Niederlage" if lost > won else "Unentschieden")
    if p.get("kills") is not None and p.get("deaths") is not None:
        hs = ((h.get("mech") or {}).get(sid) or {}).get("hs_pct")
        out["stats"] = {"k": p["kills"], "d": p["deaths"], "adr": None if p.get("adr") is None else round(p["adr"]),
                        "hs": None if hs is None else round(hs)}
    out["sides"] = _minute_sides(h, sid)
    imp = (h.get("impact") or {}).get(sid)
    if imp and imp.get("total") is not None:
        v = imp["total"] / 100
        meaning = ("Deine Kills und Tode haben eurem Team zusammen etwa {} Runden gebracht." if v > 0.05 else
                   "Deine Kills und Tode haben eurem Team zusammen etwa {} Runden gekostet." if v < -0.05 else
                   "Deine Kills und Tode haben sich etwa ausgeglichen.").format(_de(abs(v)))
        out["imp"] = {"total": de(v), "pos": v > 0, "rank": imp.get("rank"), "of": imp.get("of"), "meaning": meaning}
    rounds = h.get("rounds") or p.get("rounds")
    deaths = p.get("deaths")

    def plain(lid: str, count: int | None, target) -> dict:
        """"11 von 19 Toden mit Flash oder Molotov in der Tasche." und das Ziel als Anzahl Tode in so vielen Runden."""
        o = {}
        if count is not None and deaths and lid in DEATH_PHRASE:
            o["today"] = f"{count} von {deaths} Toden {DEATH_PHRASE[lid]}."
        if target is not None and rounds:
            o["max"] = int(float(target) * rounds / 10)
            o["max_rounds"] = rounds
        return o

    lessons_today = (h.get("lessons") or {}).get(sid) or {}
    fc = _focus_entry(h.get("focus_check"), sid) or {}
    c = fc.get("check")
    fo = fc.get("focus") or {}
    if c and c.get("rate") is not None and c.get("target") is not None:
        cl = fo.get("lesson")
        out["check"] = {"title": c.get("title"), "met": c.get("met"), "streak": c.get("streak"), "need": c.get("need"),
                        "mastered": bool(fc.get("mastered")), "count": c.get("count"), "rounds": c.get("rounds")}
        if cl in DEATH_PHRASE and c.get("count") is not None and deaths:
            out["check"]["today"] = f"{c['count']} von {deaths} Toden {DEATH_PHRASE[cl]}."
        if c.get("rounds"):
            out["check"]["max"] = int(float(c["target"]) * c["rounds"] / 10)
    lid = history.lead(h, sid)
    won_round = {r[0]: r[2] for r in (h.get("by_round") or {}).get(sid) or []}
    won_round.update({x[0]: x[2] for x in (history._seq_by(h).get(sid) or [])})
    if lid in LESSONS and lid != "duel":
        out["topic"] = {"id": lid, "title": LESSONS[lid][0], "mantra": (TEACH.get(lid) or {}).get("mantra")}
        own = [x for x in h.get("scenes") or [] if x.get("sid") == sid
               and x.get("round") is not None and x.get("tick") is not None]
        main = [x for x in own if x.get("lesson") == lid]  # Hauptfehler dieses Todes
        side = [x for x in own if x.get("lesson") != lid and lid in (x.get("lessons") or [])]
        if not main and not side and not any("lessons" in x for x in own):
            side = own  # ältere Einträge kennen nur die Haupt-Lektion je Szene: dann seine teuersten Szenen

        def low_cost(x) -> bool:  # Tod in Überzahl, Runde trotzdem gewonnen: kostet wenig, kein Aufmacher
            return bool(won_round.get(x["round"])) and (x.get("own") or 0) > (x.get("enemy") or 0)

        scs = sorted(main, key=lambda x: (low_cost(x), -(x.get("cost") or 0))) + \
            sorted(side, key=lambda x: (low_cost(x), -(x.get("cost") or 0)))
        out["scenes"] = [{"round": x["round"], "text": x.get("happened"), "cost": x.get("cost"),
                          "nades": x.get("nades") if lid == "utility" else None,
                          "href": f"/reports/{h['report_file']}#s{x['round']}-{x.get('from') or x['tick']}"}
                         for x in scs[:2]]
        if lid == "utility":
            out["util_late"] = _util_late(h, sid)
    elif sid in (h.get("lead_by") or {}) or (h.get("lessons") or {}).get(sid) is not None:
        # seine Lektionen sind ausgewertet, aber kein Fehler kam mehrmals vor: das ist die Aussage
        out["quiet"] = "Kein Fehler kam mehrmals vor. Heute gibt es kein Thema."
    out["spot"] = _minute_spot(h, sid)  # konkretes Muster (Todesort) zur Szene
    # Nächstes Match: der laufende Fokus (gilt über mehrere Matches), sonst das heutige Thema
    if fo.get("lesson") in LESSONS and fo.get("lesson") in TEACH:
        nid = fo["lesson"]
    else:
        nid = lid if lid in LESSONS and lid != "duel" and lid in TEACH else None
    if nid:
        t = TEACH[nid]
        target = fo.get("target") if fo.get("lesson") == nid else None
        out["next"] = {"lesson": nid, "title": LESSONS[nid][0], "in_game": t.get("in_game"), "mantra": t.get("mantra"),
                       **plain(nid, lessons_today.get(nid, 0) if sid in (h.get("lessons") or {}) else None, target)}
    return out


SPOT_MIN = 3  # so oft am selben Ort (gleiche Seite) gestorben: ein Muster, das man ansprechen kann


def _minute_spot(h: dict, sid: str) -> str | None:
    """Häufigster Todesort aus den Tod-Zeilen des Verlaufs: "4x als T in Apartments gestorben (Runde 5, 7, 9, 11)."."""
    from collections import defaultdict

    from cstaktik.callouts import place

    by = defaultdict(list)
    for d in h.get("deaths") or []:
        if d.get("sid") == sid and d.get("place") and d.get("side"):
            by[(d["side"], d["place"])].append(d["round"])
    if not by:
        return None
    (side, pl), rs = max(by.items(), key=lambda kv: (len(kv[1]), -min(kv[1])))
    if len(rs) < SPOT_MIN:
        return None
    return f"{len(rs)}x als {side.upper()} in {place(pl)} gestorben (Runde {', '.join(map(str, sorted(rs)))})."


UTIL_LOTS_PER_ROUND = 1.5  # ab so vielen Granaten je Runde wirft er "viel"
UTIL_LATE_SHARE = 0.5  # vor dem ersten Duell höchstens dieser Anteil davon: "zu spät"


def _util_late(h: dict, sid: str) -> str | None:
    """"Du wirfst viel, aber zu spät": viele Granaten im Match, aber wenige vor dem ersten Duell der Runde
    (``util_stats.pre`` je Runde). Nur wenn beide Werte da sind und klar auseinanderliegen."""
    p = (h.get("players") or {}).get(sid) or {}
    thrown = sum((p.get("utility") or {}).get(k, 0) for k in ("smoke", "flash", "he", "molotov"))
    rounds = p.get("rounds") or h.get("rounds")
    pre = ((h.get("util_stats") or {}).get(sid) or {}).get("pre")
    if not rounds or pre is None or not thrown:
        return None
    per = thrown / rounds
    if per < UTIL_LOTS_PER_ROUND or pre > per * UTIL_LATE_SHARE:
        return None
    return (f"Du wirfst viel, aber zu spät: {thrown} Granaten in {rounds} Runden. Vor dem ersten Duell der Runde "
            f"waren es nur {_de(pre)} pro Runde.")


@app.get("/m/{report_file}", response_class=HTMLResponse)
def match_minute(report_file: str, p: str = "") -> str:
    """Match-Story nach dem Spiel: ein Gedanke pro Bildschirm (Ergebnis, Fokus, die eine Szene, nächstes Match).
    Mehrere Fokus-Spieler ohne Login: erst wählen (``p``); eingeloggt nur der eigene Spieler."""
    if not re.fullmatch(r"[^/\\]+\.html", report_file) or not _report_visible(report_file):
        raise HTTPException(404, "Match nicht gefunden.")
    h = next((x for x in _load_hist() if x.get("report_file") == report_file), None)
    if h is None:
        raise HTTPException(404, "Match nicht gefunden.")
    if _USER.get():
        _mark_seen(_USER.get(), report_file)
    players = h.get("players") or {}
    from cstaktik import history

    focus = sorted(set(history._seq_by(h)) | set(h.get("issues") or {}) | set(h.get("impact") or {}))
    me = _me()
    sids = [me] if me and me in players else [s for s in _mine(focus) if s in players]
    names = {s: (players.get(s) or {}).get("name", s) for s in sids}
    sids.sort(key=lambda s: names[s].lower())
    try:
        at = datetime.fromisoformat(h["analyzed_at"])
        when = at.strftime("%d.%m. %H:%M")
    except (KeyError, ValueError, TypeError):
        at = when = None
    view = {"nav_active": "matches", "jobs": _running_jobs(), "file": report_file, "when": when,
            "map_label": (h.get("map") or "?").removeprefix("de_").capitalize(), "many": len(sids) > 1}
    if len(sids) > 1 and p not in sids:  # mehrere Spieler: erst wählen, wessen Story
        return _env.get_template("minute.html").render(**view, r=None, mine=False,
                                                       pick=[{"sid": s, "name": names[s]} for s in sids])
    r = _minute_player(h, p if p in sids else sids[0]) if sids else None
    if r:
        from cstaktik import session, weekplan

        # Spielabend nur für heute (bis zu diesem Match), Übungs-Vergleich zum Fokus
        if at is not None and at.date() == weekplan.local_today():
            r["today"] = session.session(_load_hist(), r["sid"], at.date(), until=h["analyzed_at"])
        if r.get("check"):
            r["practice"] = session.practice(_players_state().get(r["sid"]))
    return _env.get_template("minute.html").render(**view, r=r, pick=None, mine=bool(me and r and r["sid"] == me))


@app.get("/pro", response_class=HTMLResponse)
def pro_page() -> str:
    from cstaktik import pro

    return _env.get_template("pro.html").render(nav_active="settings", jobs=_running_jobs(),
                                                pro_overview=pro.stats(pipeline.PRO_DIR),
                                                faceit_ready=bool(os.environ.get("FACEIT_API_KEY")))


def _all_scenes(hist: list[dict]) -> list[dict]:
    """Trainings-Szenen aller Matches, neueste zuerst, jede Szene nur einmal."""
    seen: set = set()
    out = []
    for h in reversed(hist):
        for sc in h.get("scenes", []):
            key = (sc.get("report"), sc["round"], sc["tick"])
            if key not in seen:
                seen.add(key)
                out.append(sc)
    return out


def _default_sid(players: dict, names: dict, want: str = "") -> str | None:
    """Gewählter Spieler, sonst der erste mit Auftrag (nach Name sortiert), überall gleich.
    Eingeloggt und mit Steam verbunden: immer der eigene Spieler."""
    if _me():
        return _me()
    if want in players:
        return want
    return next((s for s in sorted(players, key=lambda s: names.get(s, s)) if players[s].get("focus")), None)


def _players_state() -> dict:
    from cstaktik import coaching

    return coaching.load(pipeline.COACHING_FILE).get("players", {})


def _auftrag(hist: list[dict]) -> list[dict]:
    """Laufende Aufträge je Spieler für die Startseite: Lektion, Merksatz, Übung, Checks, erledigte Übungen."""
    from cstaktik import coaching, session
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    names = {sid: p["name"] for h in hist for sid, p in h.get("players", {}).items()}
    scenes = _all_scenes(hist)
    out = []
    for sid, slot in sorted(((k, v) for k, v in _players_state().items() if k in _mine([k])),
                            key=lambda kv: names.get(kv[0], kv[0])):
        f = slot.get("focus")
        if not f or f["lesson"] not in LESSONS or f["lesson"] not in TEACH:
            continue  # Lektion gibt es nicht mehr (alte coaching.json)
        t = TEACH[f["lesson"]]
        streak = 0  # Matches in Folge unter dem Ziel (wie coaching.check: zu kurze Matches zählen nicht)
        for m in reversed(f.get("matches", [])):
            if m.get("met") is None:
                continue
            if not m["met"]:
                break
            streak += 1
        out.append({"streak": streak,
                    "mastered_titles": [LESSONS[d["lesson"]][0] for d in reversed(slot.get("done", []))
                                        if d.get("lesson") in LESSONS][:3],"sid": sid, "name": names.get(sid, sid), "lesson": f["lesson"], "title": LESSONS[f["lesson"]][0],
                    "target": f["target"], "baseline": f["baseline"], "matches": f.get("matches", []),
                    "baseline_n": f.get("baseline_n"), "baseline_rounds": f.get("baseline_rounds"),
                    "rueckfall": f.get("rueckfall"),
                    "mantra": t["mantra"], "routine": t["routine"], "in_game": t["in_game"],
                    "drills": coaching.drills_since(slot, f.get("created_at")),
                    "scenes": min(12, sum(1 for sc in scenes if sc["lesson"] == f["lesson"] and sc.get("sid") == sid)),
                    "mastered": len(slot.get("done", [])), "practice": session.practice(slot)})
    return out


def _deal_key(user: str) -> str:
    return f"deal:{user}"


def _deal_view(hist: list[dict]) -> dict | None:
    """Abmachung aus dem Report ("Abgemacht"), bis das nächste Match des Spielers ausgewertet ist."""
    user, me = _USER.get(), _me()
    if not user or not me:
        return None
    from cstaktik import accounts

    try:
        d = json.loads(accounts.get_setting(_deal_key(user)) or "null")
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("sid") != me:
        return None
    if any(me in (h.get("players") or {}) and (h.get("analyzed_at") or "") > (d.get("match_at") or "")
           for h in hist):
        return None  # nächstes Match ist da: die Abmachung ist erledigt
    return d


@app.post("/training/deal")
async def training_deal(request: Request) -> JSONResponse:
    """"Abgemacht" im Report: Abmachung bis zum nächsten Match speichern (nur für den eigenen Spieler)."""
    user = _USER.get()
    me = _me()
    if not user or not me:  # ohne Accounts oder ohne Steam-Verbindung bleibt es beim Browser-Speicher
        raise HTTPException(400, "Nur eingeloggt und mit Steam verbunden.")
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Ungültige Anfrage.") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Ungültige Anfrage.")
    sid, lesson, report = str(data.get("sid") or ""), str(data.get("lesson") or ""), str(data.get("report") or "")
    if sid != me:
        raise HTTPException(403, "Nur deine eigene Abmachung.")
    from cstaktik import accounts, history
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    h = next((x for x in _load_hist() if report and x.get("report_file") == report), None)
    if h is None or me not in (h.get("players") or {}) or lesson not in LESSONS:
        raise HTTPException(404, "Match oder Auftrag nicht gefunden.")
    fo = (_focus_entry(h.get("focus_check"), me) or {}).get("focus") or {}
    text = LESSONS[lesson][0]
    if fo.get("lesson") == lesson and fo.get("target") is not None:
        text += f": höchstens {str(fo['target']).replace('.', ',')}x pro 10 Runden"
    mantra = (TEACH.get(lesson) or {}).get("mantra")
    sc = history.score(h, me)
    deal = {"sid": me, "lesson": lesson, "text": text + ".", "mantra": mantra, "report": report,
            "map_label": (h.get("map") or "?").removeprefix("de_").capitalize(),
            "score": f"{sc[0]}:{sc[1]}" if sc else None,
            "match_at": h.get("analyzed_at"), "at": pipeline.coaching_now()}
    accounts.set_setting(_deal_key(user), json.dumps(deal, ensure_ascii=False))
    return JSONResponse({"ok": True})


@app.post("/training/done")
def training_done(p: str = "") -> RedirectResponse:
    from cstaktik import coaching, weekplan

    _own_only(p)

    with coaching.LOCK:
        state = coaching.load(pipeline.COACHING_FILE)
        slot = state.get("players", {}).get(p)
        if slot and slot.get("focus"):
            coaching.drill_done(slot, slot["focus"]["lesson"])
            # dieselbe Übung im Wochenplan abhaken, damit sie nicht doppelt gezählt wird
            key = weekplan.week_key(weekplan.local_today())
            plan = slot.get("weeks", {}).get(key)
            if plan:
                open_ = next((t["id"] for t in plan["tasks"] if t["id"].startswith("routine") and t["id"] not in plan["done"]),
                             None)
                if open_:
                    weekplan.toggle(slot, key, open_)
            coaching.save(state, pipeline.COACHING_FILE)
    from urllib.parse import quote

    return RedirectResponse(f"/training?p={quote(p)}#vorbereitung", status_code=303)


def _scene_maps(scenes: list[dict]) -> dict[str, str]:
    """Lagebilder der Szenen auf das Radarbild der Map umrechnen (Pixel, Ausschnitt). Rückgabe: Map -> Bild."""
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    radars, imgs = {}, {}
    for sc in scenes:
        fr, m = sc.get("frame"), sc.get("map")
        if not fr or not m:
            continue
        if m not in radars:
            radars[m] = build_radar(MatchData(map_name=m, tickrate=64, tickrate_source="-", players=[], rounds=[]))
            if radars[m].image_data_uri:
                imgs[m] = radars[m].image_data_uri
        r = radars[m]
        if m not in imgs:
            continue
        px = lambda p: [round(v, 1) for v in r.to_px(p[0], p[1])]  # noqa: E731
        view = {"me": px(fr["me"]), "mates": [px(q) + [q[2]] for q in fr.get("mates", [])],
                "foes": [px(q) for q in fr.get("foes", [])], "spotted": fr.get("spotted")}
        if fr.get("killer"):
            view["killer"], view["dead"], view["kplace"] = px(fr["killer"]), px(fr["dead"]), fr.get("kplace")
        # Ausschnitt: du, sichtbare Gegner und der nächste Mitspieler (weit entfernte sind am Rand/außerhalb).
        # Der Killer bestimmt den Ausschnitt erst nach der Antwort (``vb_rev``), sonst verrät der Rahmen die Richtung.
        near = sorted(view["mates"], key=lambda q: (q[0] - view["me"][0]) ** 2 + (q[1] - view["me"][1]) ** 2)[:1]
        pts = [view["me"]] + [q[:2] for q in near] + view["foes"]

        def box(pts):
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            size = min(1024, max(max(max(xs) - min(xs), max(ys) - min(ys)) + 240, 420))
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            return [round(min(max(cx - size / 2, 0), 1024 - size)), round(min(max(cy - size / 2, 0), 1024 - size)),
                    round(size)]

        view["vb"] = box(pts)
        view["vb_rev"] = box(pts + [view["killer"], view["dead"]]) if "killer" in view else view["vb"]
        sc["view"] = view
    return imgs


_INFO_RE = re.compile(r"^Info: (?P<now>.*?(?:sichtbar|Radar)\.)(?: (?P<after>.*))?$")


def _quiz_scene(sc: dict) -> dict:
    """Eine Szene fürs Situations-Training, ohne Spoiler vor der Antwort:
    - ``lage_info``: nur, was man im Moment wissen konnte (Gegner auf dem Radar); wer später tötete und ab wann er
      sichtbar war, steht in ``reveal_info`` und erscheint erst nach der Antwort.
    - ``uhr``: Spieluhr wie in CS (Rundenzeit herunter, nach dem Plant Bombentimer).
    - ``did``: was der Spieler getan hat, in denselben Worten wie die Optionen, mit Hinweis, wenn Laufen und
      Wertung auseinanderliegen (losgegangen, aber nicht näher an den Gegner = "Position gehalten")."""
    from cstaktik.callouts import clock

    snap = sc.get("snap") or {}
    m = _INFO_RE.match(sc.get("info") or "")
    sc["lage_info"] = m.group("now") if m else None
    sc["reveal_info"] = (m.group("after") if m else None) or None
    if snap.get("planted"):
        left = snap.get("time_left")
        sc["uhr"] = f"Bombe liegt, noch 0:{int(left):02d}" if left is not None else "Bombe liegt"
    elif snap.get("secs") is not None:
        sc["uhr"] = f"Uhr {clock(snap['secs'])}, Bombe nicht gelegt"
    act, kind = sc.get("aktion"), snap.get("kind")
    label = {"gehalten": "Position halten", "zurückgezogen": "Zurückziehen", "Richtung Gegner": "Richtung Gegner gehen"}
    sc["did"] = label.get(act)
    if act == "gehalten" and kind == "bewegt":
        sc["did_note"] = ("Du bist losgegangen, aber in den 5 Sekunden danach weder näher an den Gegner noch weiter "
                          "weg. Das zählt hier als Position halten.")
    elif act == "Richtung Gegner" and kind == "gehalten":
        sc["did_note"] = "Du standest, bist dann aber auf den Gegner zugegangen."
    return sc


@app.get("/training/situationen", response_class=HTMLResponse)
def quiz_page(p: str = "") -> str:
    """Entscheidungs-Training mit eigenen Situationen aus allen Matches, zuerst zum laufenden Auftrag."""
    import json as _json

    from cstaktik.coach_voice import LESSONS

    hist = _load_hist()
    players = _players_state()
    names = _names(hist)
    sid = _default_sid(players, names, p)
    f = (players.get(sid) or {}).get("focus")
    scenes = [sc for sc in _all_scenes(hist) if sid is None or sc.get("sid") == sid]
    lesson = f["lesson"] if f else None
    pick = [sc for sc in scenes if sc["lesson"] == lesson] if lesson else []
    if len(pick) < 6:  # auffüllen mit den teuersten anderen Szenen
        rest = sorted((sc for sc in scenes if sc not in pick), key=lambda sc: -(sc.get("cost") or 0))
        pick += rest[: 12 - len(pick)]
    # Szenen mit Pro-Vergleich zuerst (Reihenfolge sonst wie gewählt); ohne Vergleich gibt es die Regel des Coaches
    pick = sorted(pick[:40], key=lambda sc: not sc.get("pro_rates"))
    pick = [_quiz_scene(dict(sc)) for sc in pick]  # Kopien: der Verlauf ist gecacht und wird nicht verändert
    radars = _scene_maps(pick)  # die Seite wählt daraus 12 (falsch beantwortete und neue zuerst)
    data = _json.dumps([{**sc, "lesson_title": LESSONS.get(sc["lesson"], ("?",))[0]} for sc in pick],
                       ensure_ascii=False).replace("</", "<\\/")
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s, v in players.items() if v.get("focus") and s in _mine([s])]
    from cstaktik import coaching, weekplan

    week = weekplan.week_key(weekplan.local_today())
    plan = ((coaching.load(pipeline.COACHING_FILE).get("players", {}).get(sid) or {}).get("weeks") or {}).get(week)
    quiz_open = bool(plan) and any(t["id"] == "quiz" for t in plan["tasks"]) and "quiz" not in plan["done"]
    return _env.get_template("quiz.html").render(nav_active="coach", title=LESSONS.get(lesson, ("?",))[0] if lesson else None,
                                                 n=min(12, len(pick)), data_json=data, tabs=tabs, who=names.get(sid),
                                                 own=bool(_me()) and sid == _me(),
                                                 sid=sid, week=week, quiz_open=quiz_open, radars=radars)


_CACHE: dict[str, tuple] = {}


def _dir_cached(name: str, folder: Path, loader) -> list[dict]:
    """Ordner-Inhalt nur neu laden, wenn sich Dateien geändert haben (Name, Größe, Änderungszeit).
    Die Seiten lesen die Daten nur; wer sie ändert, speichert sie und macht den Cache so ungültig."""
    if not folder.exists():
        return []
    key = (str(folder), tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in folder.glob("*.json"))))
    hit = _CACHE.get(name)
    if hit is None or hit[0] != key:
        hit = (key, loader(folder))
        _CACHE[name] = hit
    return hit[1]


def _load_hist() -> list[dict]:
    from cstaktik import history

    return [h for h in _dir_cached("hist", pipeline.HISTORY_DIR, history.load_all) if _visible(h)]


def _report_visible(file: str) -> bool:
    """Report gehört zu einem Match, das der Nutzer sehen darf (Report ohne Verlaufs-Eintrag: nicht)."""
    from cstaktik import history

    hist = _dir_cached("hist", pipeline.HISTORY_DIR, history.load_all)
    return any(h.get("report_file") == file and _visible(h) for h in hist)


def _load_pro() -> list[dict]:
    from cstaktik import pro

    return _dir_cached("pro", pipeline.PRO_DIR, pro.load_all)


def _names(hist: list[dict]) -> dict[str, str]:
    return {s: pp["name"] for h in hist for s, pp in h.get("players", {}).items()}


def _player_maps(hist: list[dict], sid: str | None) -> list[str]:
    """Maps des Spielers, zuletzt gespielte zuerst."""
    played = [h.get("map") for h in reversed(hist) if h.get("map") and (sid is None or sid in h.get("players", {}))]
    return list(dict.fromkeys(played))


def _plan_ctx(hist: list[dict], pro_all: list[dict], sid: str, focus: dict) -> dict:
    from cstaktik import lineups, mapbook
    from cstaktik.curriculum import TEACH

    cfg = load_rules_config()["mapbook"]
    maps = _player_maps(hist, sid)
    m = maps[0] if maps else None
    spot = lineup = None
    positions, pos_lineups = [], []
    want = {"utility": "flash", "no_shot_far": "smoke", "no_shot_close": "flash"}.get(focus["lesson"])
    if m:
        book = mapbook.build(hist, pro_all, m, sid, cfg)
        spot = mapbook.worst_spot(book)
        # eigene Standard-Spots: je Seite die 2 häufigsten mit genug Runden; Pro-Lineups von genau dort
        for side, sd in book["sides"].items():
            for row in sorted(sd["spots"], key=lambda r: -r["n"])[:2]:
                positions.append({"side": side, "place": row["place"], "n": row["n"]})
                pos_lineups += row.get("lineups") or []
        pos_lineups.sort(key=lambda l: (l["kind"] != want if want else False, -l["n"]))
        cands = (spot or {}).get("lineups") or []
        if not cands:
            side = (spot or {}).get("side")
            allx = lineups.build(pro_all, m)
            cands = [l for l in allx if side is None or l["side"] == side] or allx
        # passend zum Auftrag: Utility-Auftrag -> Flash, lange Linien -> Smoke
        cands = sorted(cands, key=lambda l: l["kind"] != want) if want else cands
        lineup = cands[0] if cands else None
    scenes = sum(1 for sc in _all_scenes(hist) if sc.get("sid") == sid)
    tactic = None
    if m:  # Taktik-Hausaufgabe: nur eine echte Pro-Empfehlung (ab 50 % Siegquote, mindestens 3 Runden)
        from cstaktik import playbook

        own = [{"map": h.get("map"), "plays": h.get("plays"), "ct_plays": h.get("ct_plays")} for h in hist]
        plan = playbook.gameplan(pro_all, own, m, load_rules_config().get("playbook"))
        tp = (plan or {}).get("t_pro")
        tactic = tp if tp and tp.get("why") == "best" else None
    t = TEACH[focus["lesson"]]
    return {"sid": sid, "lesson": focus["lesson"], "routine": t["routine"], "map": m,
            "map_label": m.removeprefix("de_").capitalize() if m else None, "spot": spot, "lineup": lineup,
            "scenes": scenes, "tactic": tactic, "positions": positions, "pos_lineups": pos_lineups,
            "fault": t.get("fault"), "in_game": t.get("in_game")}


@app.get("/training", response_class=HTMLResponse)
def training_page(p: str = "") -> str:
    """Trainings-Zentrale: Wochenplan je Spieler, Map-Buch, Lineups, Situationen."""
    from cstaktik import coaching, weekplan
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    hist = _load_hist()
    names = _names(hist)
    state = coaching.load(pipeline.COACHING_FILE)
    players = state.get("players", {})
    sid = _default_sid(players, names, p)
    slot = players.get(sid) or {}
    focus = slot.get("focus")
    plan = chk = key = None
    past = []
    if sid and focus:
        key, plan, changed = weekplan.ensure(slot, _plan_ctx(hist, _load_pro(), sid, focus))
        changed |= weekplan.tactic_progress(key, plan, hist, load_rules_config().get("playbook"), sid)
        if changed:  # nur den Wochenplan dieses Spielers in den aktuellen Stand schreiben
            with coaching.LOCK:
                cur = coaching.load(pipeline.COACHING_FILE)
                cur.setdefault("players", {}).setdefault(sid, slot)["weeks"] = slot.get("weeks", {})
                coaching.save(cur, pipeline.COACHING_FILE)
        chk = weekplan.check(key, plan, hist, sid, focus,
                             min_rounds=load_rules_config()["goals"].get("min_master_rounds", 40))
        for k in sorted(slot.get("weeks", {}), reverse=True):
            if k != key:
                past.append(weekplan.check(k, slot["weeks"][k], hist, sid, None)
                            | {"title": LESSONS.get(slot["weeks"][k]["lesson"], ("?",))[0]})
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s, v in players.items() if v.get("focus") and s in _mine([s])]
    # Vor dem Match (10 Minuten): Aufwärm-Übung zum Fokus und die Kabine je Map
    prep = next((a for a in _auftrag(hist) if a["sid"] == sid), None)
    played = [h.get("map") for h in reversed(hist) if h.get("map")]
    briefing_maps = list(dict.fromkeys(played + ["de_mirage", "de_dust2", "de_inferno"]))
    return _env.get_template("training.html").render(
        prep=prep, briefing_maps=briefing_maps, n_history=len(hist),
        nav_active="coach", tabs=tabs, sid=sid, who=names.get(sid), plan=plan, week=key, chk=chk, past=past[:4],
        title=LESSONS.get(focus["lesson"], ("?",))[0] if focus else None, maps=_player_maps(hist, sid) or ["de_mirage"],
        fault=(TEACH.get(focus["lesson"]) or {}).get("fault") if focus else None,
        pro_maps=sorted({d.get("map") for d in _load_pro() if d.get("map")}), hub=_map_hub(hist, sid))


def _map_hub(hist: list[dict], sid: str | None) -> list[dict]:
    """Je Map alle Werkzeuge an einem Ort: eigene Matches, Pro-Demos, Links zu Kabine, Map-Buch, Playbook, Lineups.
    Reihenfolge: eure meistgespielten Maps zuerst, dann Maps nur mit Pro-Demos."""
    from collections import Counter

    own = Counter(h.get("map") for h in hist if h.get("map") and (not sid or sid in h.get("players", {})))
    pro = Counter(d.get("map") for d in _load_pro() if d.get("map"))
    maps = sorted(set(own) | set(pro), key=lambda m: (-own[m], -pro[m], m))
    return [{"map": m, "label": m.removeprefix("de_").capitalize(), "own": own[m], "pro": pro[m],
             "won": sum(1 for h in hist if h.get("map") == m and (h.get("won") or 0) > (h.get("lost") or 0)
                        and (not sid or sid in h.get("players", {})))} for m in maps]


@app.post("/training/plan")
def plan_toggle(p: str = "", task: str = "", week: str = "", done: int = 0, back: str = "") -> RedirectResponse:
    """Aufgabe abhaken/Haken entfernen. ``done=1``: nur abhaken (automatisch, z. B. Quiz), nie den Haken entfernen.
    ``back=home``: danach zurück zur Startseite (Checkliste im Fokus)."""
    from cstaktik import coaching, weekplan

    _own_only(p)

    with coaching.LOCK:
        state = coaching.load(pipeline.COACHING_FILE)
        slot = state.get("players", {}).get(p)
        if slot and done and task in ((slot.get("weeks", {}).get(week) or {}).get("done") or {}):
            slot = None  # schon erledigt (z. B. in einem anderen Tab): nichts umschalten
        if slot:
            now = weekplan.toggle(slot, week, task)
            if task.startswith("routine") and slot.get("focus") and now is not None:
                if now:
                    coaching.drill_done(slot, slot["focus"]["lesson"])
                else:
                    coaching.drill_undo(slot, slot["focus"]["lesson"])
            if now is not None:
                coaching.save(state, pipeline.COACHING_FILE)
    if back == "home":
        return RedirectResponse("/#fokus", status_code=303)
    return RedirectResponse(f"/training?p={p}#plan", status_code=303)


@app.get("/mapbook/{map_name}", response_class=HTMLResponse)
def mapbook_page(map_name: str, p: str = "") -> str:
    from cstaktik import mapbook

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    hist = _load_hist()
    names = _names(hist)
    focus_ids = sorted({s for h in hist if h.get("map") == map_name for t in h.get("timeline", []) for s in [t["sid"]]},
                       key=lambda s: names.get(s, s))
    pref = _default_sid(_players_state(), names, p)
    sid = _me() or (p if p in focus_ids else pref if pref in focus_ids else (focus_ids[0] if focus_ids else None))
    book = mapbook.build(hist, _load_pro(), map_name, sid, load_rules_config()["mapbook"]) \
        if sid else None
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in _mine(focus_ids)]
    img = None
    if book:  # Schusslinien aufs Radarbild umrechnen
        radar = _page_radar(map_name, [q for sd in book["sides"].values() for l in sd["lines"]
                                       for q in ((l[0], l[1]), (l[2], l[3]))])
        img = radar.image_data_uri
        if img or radar.note:
            for sd in book["sides"].values():
                sd["px"] = [[*radar.to_px(l[0], l[1]), *radar.to_px(l[2], l[3]), l[4] if len(l) > 4 else None]
                            for l in sd["lines"]]
                if sd["px"]:  # auf den Bereich der Linien zoomen (am Handy sonst zu klein)
                    xs = [v for l in sd["px"] for v in (l[0], l[2])]
                    ys = [v for l in sd["px"] for v in (l[1], l[3])]
                    size = max(max(xs) - min(xs), max(ys) - min(ys)) + 220
                    size = min(1024, max(size, 380))
                    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
                    x0 = min(max(cx - size / 2, 0), 1024 - size)
                    y0 = min(max(cy - size / 2, 0), 1024 - size)
                    sd["vb"] = f"{x0:.0f} {y0:.0f} {size:.0f} {size:.0f}"
                    sd["sw"] = round(size / 340, 2)
    return _env.get_template("mapbook.html").render(img=img,nav_active="coach", book=book, cfg=load_rules_config()["mapbook"], tabs=tabs, sid=sid,
                                                    who=names.get(sid), map_name=map_name,
                                                    label=map_name.removeprefix("de_").capitalize())


_MAP_TRIED: set[str] = set()


def _page_radar(map_name: str, points: list | None = None):
    """Radar für Playbook, Lineups und Map-Buch. Fehlt das Radarbild (Pro-Demo ohne eigenes Match dieser Map), wird
    es einmal je Map nachgeladen. Klappt das nicht: Kalibrierung aus den Punkten der Seite (Welt x/y), kein Bild.
    Dann zeigt die Seite die Wege auf neutralem Grund mit dem Hinweis "Keine Karte für diese Map"."""
    from cstaktik import maps
    from cstaktik.model import MatchData
    from cstaktik.report import radar as rmod

    mk = lambda: rmod.build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))  # noqa: E731
    r = mk()
    if r.image_data_uri is None and map_name not in _MAP_TRIED:
        _MAP_TRIED.add(map_name)
        if maps.ensure_map(map_name, rmod.LOCAL_MAPS_DIR, timeout=8) is None:
            r = mk()
    if r.image_data_uri is None and points:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        pad = 200.0
        span = max(max(xs) - min(xs), max(ys) - min(ys)) + 2 * pad
        r = rmod.Radar(1024, None, "Keine Karte für diese Map", min(xs) - pad - (span - 2 * pad - (max(xs) - min(xs))) / 2,
                       max(ys) + pad + (span - 2 * pad - (max(ys) - min(ys))) / 2, span / 1024)
    return r


@app.get("/playbook", response_class=HTMLResponse)
def playbook_index() -> RedirectResponse:
    maps = sorted({d.get("map") for d in _load_pro() if d.get("map")})
    return RedirectResponse(f"/playbook/{maps[0] if maps else 'de_mirage'}", status_code=303)


@app.get("/playbook/{map_name}", response_class=HTMLResponse)
def playbook_page(map_name: str, who: str = "", side: str = "") -> str:
    """T-Taktiken aus den Pro-Demos dieser Map: Laufwege, Granaten, Plant, abspielbar auf dem Radar."""
    import json as _json

    from cstaktik import playbook

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    pro, cfg = _load_pro(), load_rules_config().get("playbook")
    own = [{"map": h.get("map"), "plays": h.get("plays"), "ct_plays": h.get("ct_plays"),
            "source_file": f"{(h.get('analyzed_at') or '')[8:10]}.{(h.get('analyzed_at') or '')[5:7]}."}
           for h in _load_hist() if h.get("plays") or h.get("ct_plays")]
    if who not in ("ihr", "pro"):  # ohne Wahl: Pros, außer es gibt für diese Map keine Pro-Demo, aber eigene Runden
        has_pro = any(d.get("map") == map_name for d in pro)
        has_own = any(d.get("map") == map_name for d in own)
        who = "ihr" if has_own and not has_pro else "pro"
    book = playbook.build(own if who == "ihr" else pro, map_name, cfg)
    mix = {"pro": playbook.style_mix(pro, map_name, cfg), "ihr": playbook.style_mix(own, map_name, cfg)}
    mix["text"] = playbook.compare(mix["ihr"], mix["pro"])
    from cstaktik import callouts
    from cstaktik import lineups as lu

    # Granaten-Set und Rollen mit Lineups verknüpfen: gleiche Art, Seite und Landeort, häufigster Wurf zuerst
    lines = lu.build(pro, map_name)
    src_pts = [q for d in (own if who == "ihr" else pro) if d.get("map") == map_name
               for key in ("plays", "ct_plays") for p in d.get(key) or []
               for q in ([v for pts in (p.get("paths") or {}).values() for v in pts] + [v[:2] for v in (p.get("pos") or {}).values()])]
    radar = _page_radar(map_name, src_pts)
    img = radar.image_data_uri

    def draw(ex: dict) -> dict | None:
        """Eine Runde fürs Radar: Laufwege, Granaten, Plant, Schlüsselmomente, Rollen, Ausschnitt."""
        px = lambda x, y: [round(v, 1) for v in radar.to_px(x, y)]  # noqa: E731
        paths = [[px(*q) for q in pts] for pts in (ex.get("paths") or {}).values()]
        nades = [{"kind": n["kind"], "t": n["t"], "to": n.get("to"),
                  "a": px(*(n["p"][:2] if n.get("p") else (n["fx"], n["fy"]))), "b": px(n["tx"], n["ty"])}
                 for n in playbook.drawn_nades(ex)]
        plant = px(*ex["plant"]) if ex.get("plant") else None
        pts = [q for p in paths for q in p] + [q for n in nades for q in (n["a"], n["b"])] + ([plant] if plant else [])
        if not pts:
            return None
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        size = min(1024, max(max(xs) - min(xs), max(ys) - min(ys)) + 120)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        x0, y0 = min(max(cx - size / 2, 0), 1024 - size), min(max(cy - size / 2, 0), 1024 - size)
        sids = list(ex.get("paths") or {})
        evs = playbook.events(ex)
        for ev in evs:  # T-Tod: Punkt am Ende seines Laufwegs (Laufwege enden mit dem Tod)
            for it in ev["items"]:
                if it["kind"] == "death" and it.get("sid") in sids:
                    it["p"] = paths[sids.index(it["sid"])][-1]
        return {"paths": paths, "nades": nades, "plant": plant, "step": playbook.PATH_STEP_S, "events": evs,
                "plant_t": ex.get("plant_t"), "vb": [round(x0), round(y0), round(size)], "sw": round(size / 400, 2),
                "r": ex["r"], "demo": ex.get("demo"), "won": ex["won"],
                "via": [callouts.place(v) for v in ex.get("via_all") or []], "roles": playbook.roles(ex, lines)}

    for tac in book["tactics"]:  # bis zu 8 Runden je Taktik zum Durchblättern, die Beispielrunde zuerst
        tac["draws"] = [d for d in (draw(r) for r in tac["rounds"][:8]) if d]
    if side not in ("t", "ct"):  # ohne Wahl: T, außer es gibt nur CT-Runden (z. B. ihr habt nur CT gespielt)
        src = own if who == "ihr" else pro
        has_t = any(d.get("map") == map_name and d.get("plays") for d in src)
        has_ct = any(d.get("map") == map_name and d.get("ct_plays") for d in src)
        side = "ct" if has_ct and not has_t else "t"
    def link(items: list[dict], sd: str) -> None:
        for c in items:
            hit = next((x for x in lines if x["side"] == sd and x["kind"] == c["kind"] and x.get("to") == c.get("to")), None)
            c["lineup"] = hit["id"] if hit else None

    for tac in book["tactics"]:
        link(tac["common"], "t")
    ct = None
    if side == "ct":  # Aufstellungen: Bombsite-Mitten aus allen Plants dieser Map (Pros und eure)
        ct = playbook.ct_build(own if who == "ihr" else pro, map_name, playbook.site_centers(pro + own, map_name), cfg)
        units = (cfg or {}).get("zone_units", playbook.CT_DEFAULTS["zone_units"])
        for st in ct["setups"]:
            st["draws"] = []
            for r in st["rounds"][:8]:
                pts = [radar.to_px(v[0], v[1]) + (r["zones"][sid], v[2]) for sid, v in r["pos"].items()]
                nades = [{"kind": n["kind"], "to": n.get("to"), "t": n["t"],
                          "a": radar.to_px(*(n["p"][:2] if n.get("p") else (n["fx"], n["fy"]))),
                          "b": radar.to_px(n["tx"], n["ty"])} for n in r["nades"] if n["kind"] != "he"]
                st["draws"].append({"pts": pts, "nades": nades, "r": r["r"], "won": r["won"], "demo": r.get("demo"),
                                    "plant": radar.to_px(*r["plant"]) if r.get("plant") else None,
                                    "plant_site": r.get("plant_site")})
        for st in ct["setups"]:
            link(st["util"], "ct")
        ct["zones_px"] = {k: [*radar.to_px(*v), units / radar.scale] for k, v in ct["centers"].items()}
    maps = sorted({d.get("map") for d in pro + own if d.get("map")} | {map_name})
    data = _json.dumps({t["id"]: t.get("draws") for t in book["tactics"]} if side == "t" else
                       {"zones": ct["zones_px"], **{st["id"]: st["draws"] for st in ct["setups"]}},
                       ensure_ascii=False).replace("</", "<\\/")
    return _env.get_template("playbook.html").render(nav_active="coach", book=book, img=img, maps=maps, no_map=not img,
                                                     map_name=map_name, data=data, who=who, mix=mix, side=side, ct=ct,
                                                     label=map_name.removeprefix("de_").capitalize())


@app.get("/lineups/{map_name}", response_class=HTMLResponse)
def lineups_page(map_name: str, side: str = "", kind: str = "", l: str = "", p: str = "") -> str:
    """Lineups einer Map: je Seite die meistgeworfenen zuerst, der Rest nach Landeort eingeklappt."""
    from cstaktik import lineups

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    allx = lineups.build(_load_pro(), map_name)
    sel = [x for x in allx if (not side or x["side"] == side) and (not kind or x["kind"] == kind)]
    sides = lineups.organize(sel)
    flat = [x for sd in sides for x in sd["core"] + [y for g in sd["groups"] for y in g["rows"]]]
    # Link auf einen zusammengelegten Wurf (anderer Seite oder älterer Link): auf den gezeigten umlenken
    l = next((x["id"] for x in flat if l and (x["id"] == l or l in x["alt_ids"])), "")
    radar = _page_radar(map_name, [q for x in flat for q in ((x["x"], x["y"]), (x["tx"], x["ty"]))])
    for x in flat:
        x["px"], x["py"] = radar.to_px(x["x"], x["y"])
        x["tpx"], x["tpy"] = radar.to_px(x["tx"], x["ty"])
        lo_x, hi_x = min(x["px"], x["tpx"]), max(x["px"], x["tpx"])
        lo_y, hi_y = min(x["py"], x["tpy"]), max(x["py"], x["tpy"])
        size = max(max(hi_x - lo_x, hi_y - lo_y) + 200, 320)
        cx, cy = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
        h = max(size * .7, hi_y - lo_y + 200)  # flacher als quadratisch: am Handy weniger Scrollen
        x["vb"] = f"{cx - size / 2:.0f} {cy - h / 2:.0f} {size:.0f} {h:.0f}"
        x["sw"] = round(size / 300, 2)  # Strichstärke und Schrift passend zum Ausschnitt
        # Beschriftung innen halten: Text links vom Punkt, wenn er rechts im Ausschnitt liegt
        x["fanchor"] = "end" if x["px"] > cx else "start"
        x["tanchor"] = "end" if x["tpx"] > cx else "start"
    for sd in sides:
        for g in sd["groups"]:
            g["open"] = any(x["id"] == l for x in g["rows"])
    return _env.get_template("lineups.html").render(
        nav_active="coach", sides=sides, img=radar.image_data_uri, map_name=map_name,
        label=map_name.removeprefix("de_").capitalize(), side=side, kind=kind, sel=l, total=len(lineups.dedupe(allx)),
        n_shown=len(flat), kinds=lineups.KIND_DE, sid=re.sub(r"[^0-9]", "", p),
        n_demos=sum(1 for d in _load_pro() if d.get("map") == map_name))


def _baustellen(hist: list[dict]) -> list[dict]:
    """Je Fokus-Spieler die größte Coach-Lektion im Verlauf, mit Trend und schlechtester Map."""
    from cstaktik.report.progress import _lessons

    out = []
    names = {}
    for h in hist:
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]
    for sid, name in names.items():
        ls = _lessons(hist, sid)
        if not ls:
            continue
        top = ls[0]
        have = [r for r in top["rates"] if r is not None]
        worst = max(top["by_map"].items(), key=lambda kv: kv[1]["rate"], default=(None, None))[0]
        out.append({"name": name, "title": top["title"], "state": top["trend"]["state"],
                    "now": str(round(have[-1], 1)).replace(".", ",") if have else "0",
                    "worst_map": worst.removeprefix("de_").capitalize() if worst and len(top["by_map"]) > 1 else None})
    return out


@app.get("/briefing/{map_name}", response_class=HTMLResponse)
def briefing_page(map_name: str) -> str:
    from cstaktik import briefing, goals

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    hist = _load_hist()

    from cstaktik import playbook

    pro = _load_pro()
    b = briefing.build(map_name, hist, goals.load(pipeline.GOALS_FILE), pro=pro)
    own = [{"map": h.get("map"), "plays": h.get("plays"), "ct_plays": h.get("ct_plays")} for h in hist]
    cfg = load_rules_config().get("playbook")
    # Empfehlung und "Stärke" erst ab KABINE_MIN Runden: 2 von 4 ist keine Stärke
    plan = playbook.gameplan(pro, own, map_name, cfg, min_n=KABINE_MIN)
    if plan:
        if plan.get("t_own") and plan["t_own"]["won_pct"] <= 50:
            plan["t_own"] = None
        plan["pro_demos"] = sum(1 for d in pro if d.get("map") == map_name)
        if not any(v for k, v in plan.items() if k != "pro_demos"):
            plan = None
    has_own = bool(b["matches"])
    # Gewohnheiten über alle Maps (Kauf, nach dem Plant): nur wenn klar schlechter als Pros. Dieselbe Pro-Basis wie
    # unter Fortschritt > Details (alle Pro-Demos, alle Maps). Ohne eigenes Match auf dieser Map: keine Tipps von
    # anderen Maps, stattdessen ehrlich "noch keine Daten".
    habits = []
    if has_own:
        for side in ("t", "ct"):
            key = playbook.SIDE_KEYS[side][0]
            demos = sum(1 for d in pro if d.get(key))
            pb, pp, pf = playbook.buy_mix(pro, cfg, side), playbook.postplant_mix(pro, side), playbook.firstblood_mix(pro, side)
            for text, n_pro in ((playbook.buy_reading(playbook.buy_mix(own, cfg, side), pb, side=side), pb["total"]),
                                (playbook.postplant_reading(playbook.postplant_mix(own, side), pp, side=side), pp["total"]),
                                (playbook.firstblood_reading(playbook.firstblood_mix(own, side), pf, side), pf["total"])):
                if text:
                    habits.append({"text": text, "basis": f"Eure {side.upper()}-Runden auf allen Maps. Pros: {n_pro} "
                                                          f"{side.upper()}-Runden aus {demos} Demo{'s' if demos != 1 else ''}."})
    if habits:
        plan = {**(plan or {}), "habits": habits}
    kab = _kabine(hist, map_name)
    if kab and not has_own:
        for pl in kab["players"]:
            pl["mind"] = []  # Hinweise aus anderen Maps gehören nicht in die Kabine dieser Map
    return _env.get_template("briefing.html").render(nav_active="coach", b=b, map_lessons=_map_lessons(hist, map_name),
                                                     kabine=kab, plan=plan, map_name=map_name, has_own=has_own,
                                                     kabine_min=KABINE_MIN)


KABINE_MIN = 5  # so viele Runden braucht eine Taktik in der Kabine für "Empfehlung" oder "Stärke"


def _kabine(hist: list[dict], map_name: str) -> dict | None:
    """Kabine vor dem Match: Auftrag je Spieler und wo auf dieser Map der Auftrags-Fehler passiert ist."""
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    auftr = _auftrag(hist)
    if not auftr:
        return None
    colors = ["#ff9f1c", "#6f9be8"]
    scenes = [sc for sc in _all_scenes(hist) if sc.get("map") == map_name and sc.get("pos")]
    radar = build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))
    img = radar.image_data_uri
    players = []
    pts_all = []
    for i, a in enumerate(auftr):
        mine = [sc for sc in scenes if sc["lesson"] == a["lesson"] and sc.get("sid") == a["sid"]]
        pts = []
        for sc in mine:
            x, y = sc["pos"]
            pts.append({"x": x, "y": y, "round": sc["round"], "report": sc.get("report"), "tick": sc.get("from") or sc["tick"],
                        "place": (sc.get("snap") or {}).get("place")})
        pts_all += pts
        from collections import Counter

        top = Counter(q["place"] for q in pts if q["place"]).most_common(1)
        from cstaktik import mapbook

        ang = {side: mapbook.angles(hist, map_name, a["sid"], side) for side in ("ct", "t")}
        angles = {side: g["killer_top"][:1] for side, g in ang.items()}
        seen_at = {s.upper(): g["seen"]["places"][0] for s, g in ang.items() if g["seen"] and g["seen"]["places"]}
        players.append({**a, "color": colors[i % len(colors)], "points": pts, "mind": _mind(hist, a["sid"]),
                        "top_place": top[0] if top and top[0][1] >= 2 else None,
                        "angles": {s.upper(): v[0] for s, v in angles.items() if v}, "seen_at": seen_at})
    if img:
        for pl in players:
            for q in pl["points"]:
                q["px"], q["py"] = radar.to_px(q["x"], q["y"])
    elif pts_all:  # ohne Radarbild: Punkte in ihrem eigenen Rahmen
        xs, ys = [q["x"] for q in pts_all], [q["y"] for q in pts_all]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 500) * 1.3
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        for pl in players:
            for q in pl["points"]:
                q["px"], q["py"] = 512 + (q["x"] - cx) / span * 1024, 512 - (q["y"] - cy) / span * 1024
    return {"img": img, "players": players, "has_points": bool(pts_all)}


def _mind(hist: list[dict], sid: str) -> list[str]:
    """Für die Kabine: was die Impact-, Tilt- und Clutch-Auswertung über alle Maps für dieses Match mitgibt."""
    from cstaktik import clutch, impact, tilt

    out = []
    im = impact.profile(hist, sid)
    if im and im.get("ctx"):
        sure = [c for c in im["ctx"] if c["enough"] and c["ctx"] != "bomb"]
        if sure and sure[0]["per_match"] <= -0.15:
            w = sure[0]
            out.append(f"{w['label']}: Hier liegst du {w['per_match_s'].lstrip('-')} Runden pro Match unter dem "
                       f"Schnitt. {impact.CTX_TIP[w['ctx']]}")
    t = tilt.summary(hist, sid)
    if t and t["reading"] and "messbar schlechter" in t["reading"]:
        out.append("Nach zwei verlorenen Runden in Folge spielst du messbar schlechter. Dann bewusst eine ruhige "
                   "Standard-Runde zu zweit.")
    c = clutch.summary(hist, sid, _load_pro())
    if c and c["reading"] and "liegen" in c["reading"]:
        out.append("Im Clutch: Zeit nutzen, Gegner einzeln nehmen.")
    return out


def _map_lessons(hist: list[dict], map_name: str) -> list[dict]:
    """Je Spieler die zwei häufigsten Coach-Lektionen auf dieser Map (aus dem Verlauf)."""
    from cstaktik.report.progress import _lessons

    names = {sid: p["name"] for h in hist for sid, p in h.get("players", {}).items()}
    out = []
    focus_titles = {a["title"] for a in _auftrag(hist)}
    for sid, name in names.items():
        if not _mine([sid]):
            continue
        # erst ab 3 Vorkommen und 30 Runden auf der Map: ein einzelner Tod ist keine Baustelle
        ls = [l for l in _lessons(hist, sid) if (l["by_map"].get(map_name) or {}).get("count", 0) >= 3
              and l["by_map"][map_name]["rounds"] >= 30]
        ls = [l for l in ls if l["title"] not in focus_titles]  # Auftrag steht schon oben in der Kabine
        ls.sort(key=lambda l: -l["by_map"][map_name]["rate"])
        out += [{"name": name, "title": l["title"], "drill": l["drill"],
                 "rate": str(l["by_map"][map_name]["rate"]).replace(".", ","),
                 "count": l["by_map"][map_name]["count"], "rounds": l["by_map"][map_name]["rounds"]} for l in ls[:2]]
    return out


def _run_job(job_id: str, target: Path, focus: set[str] | None, is_pro: bool = False) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft", stage="Demo vorbereiten", started=time.monotonic())
    try:
        demo = pipeline.prepare_demo(target, remove_source=True)
        cached = pipeline.is_cached(demo)
        estimate = None if cached else pipeline.estimate_seconds(demo.stat().st_size)
        update(cached=cached, estimate=round(estimate, 1) if estimate else None, samples=pipeline.timing_samples())
        if is_pro:
            info = pipeline.run_pro(demo, progress=lambda stage, frac: update(stage=stage, frac=frac))
            label = (info["map"] or "?").removeprefix("de_").capitalize()
            update(status="fertig", stage="Fertig", frac=1.0,
                   message=f"Pro-Demo gespeichert: {label}, {info['rounds']} Runden, {info['nades']} Granaten. "
                           f"{info['reports']} eigene {label}-Reports mit den neuen Pro-Daten aktualisiert.")
        else:
            out = pipeline.run(demo, focus, progress=lambda stage, frac: update(stage=stage, frac=frac))
            update(status="fertig", stage="Fertig", frac=1.0, report=out.name)
    except ValueError as exc:
        update(status="fehler", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - Parser-Fehler verständlich melden
        update(status="fehler", error=f"Demo konnte nicht ausgewertet werden: {type(exc).__name__}: {exc}")


def _run_archive_job(job_id: str, archive: Path, focus: set[str] | None, is_pro: bool = False) -> None:
    """Archiv entpacken, dann jede Demo darin nacheinander auswerten (wie _run_job)."""
    from cstaktik.archive import extract_demos

    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft", stage="Archiv entpacken", started=time.monotonic())
    try:
        demos = extract_demos(archive, archive.parent, pipeline.MAX_DEMO_BYTES)
    except ValueError as exc:
        update(status="fehler", error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        update(status="fehler", error=f"Archiv konnte nicht entpackt werden: {type(exc).__name__}: {exc}")
        return
    done, failed, links = [], [], []
    for i, demo in enumerate(demos):
        pre = f"Demo {i + 1} von {len(demos)}: " if len(demos) > 1 else ""

        def step(stage, frac, pre=pre, i=i):
            update(stage=pre + stage, frac=(i + frac) / len(demos))

        try:
            demo = pipeline.prepare_demo(demo, remove_source=True)
            if is_pro:
                info = pipeline.run_pro(demo, progress=step)
                done.append(f"{(info['map'] or '?').removeprefix('de_').capitalize()} ({info['rounds']} Runden)")
            else:
                out = pipeline.run(demo, focus, progress=step)
                links.append({"href": f"/reports/{out.name}", "text": demo.name})
                done.append(demo.name)
        except Exception as exc:  # noqa: BLE001 - eine kaputte Demo stoppt die anderen nicht
            failed.append(f"{demo.name}: {exc}")
    if not done:
        update(status="fehler", error="Keine Demo im Archiv auswertbar. " + " | ".join(failed)[:600])
        return
    msg = (f"{len(done)} Pro-Demo{'s' if len(done) != 1 else ''} gespeichert: {', '.join(done)}." if is_pro
           else f"{len(done)} Match{'es' if len(done) != 1 else ''} ausgewertet.")
    if failed:
        msg += f" Nicht auswertbar: {'; '.join(failed)[:400]}"
    update(status="fertig", stage="Fertig", frac=1.0, message=msg, links=links,
           report=links[0]["href"].removeprefix("/reports/") if len(links) == 1 and not failed else None)


@app.post("/analyze")
async def analyze_upload(
    demo: UploadFile = File(...), steamids: str = Form(""), pro: str = Form("")
) -> RedirectResponse:
    from cstaktik.archive import is_archive_name

    filename = demo.filename or ""
    if _USER.get() is not None and not _me() and not pro:
        raise HTTPException(400, "Erst unter Optionen mit Steam verbinden. Der Coach wertet die Matches "
                                 "deines Steam-Accounts aus und zeigt sie nur dir.")
    is_arc = is_archive_name(filename)
    if not pipeline.is_demo_name(filename) and not is_arc:
        raise HTTPException(400, "Nur .dem, .dem.gz, .dem.bz2, .dem.zst, .zip oder .rar.")
    # Pro-Demos getrennt ablegen, damit sie nie als eigenes Match ausgewertet werden
    folder = pipeline.PRO_DEMOS_DIR if pro else pipeline.DEMOS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    low = filename.lower()
    suffix = ((".zip" if low.endswith(".zip") else ".rar") if is_arc else pipeline.packed_suffix(low) or ".dem")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name[: -len(suffix)]).strip("._")[:80] if is_arc else None
    target = folder / f"{name or _safe_name(filename)}{suffix}"
    part = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    size = 0
    try:
        with part.open("wb") as fh:
            while chunk := await demo.read(1 << 20):
                size += len(chunk)
                if size > pipeline.MAX_DEMO_BYTES:
                    raise HTTPException(413, "Datei zu groß.")
                fh.write(chunk)
        ps = pipeline.packed_suffix(target.name)
        unpacked = target.with_name(target.name[: -len(ps)] + ".dem") if ps else None
        if not is_arc and (target.exists() or (unpacked is not None and unpacked.exists())):
            import filecmp

            from cstaktik.archive import _unique

            # gleicher Name, anderer Inhalt: eigener Name, sonst zeigt der alte Report plötzlich das neue Match.
            # .dem.bz2 wird nach dem Entpacken gelöscht: dann zählt die entpackte .dem daneben.
            same = target.exists() and target.stat().st_size == size and filecmp.cmp(part, target, shallow=False)
            if not same and not target.exists() and unpacked is not None and unpacked.exists():
                # nur die entpackte .dem liegt noch da: gepackten Upload damit vergleichen (Zeit im Thread)
                if await run_in_threadpool(_same_unpacked, part, unpacked, suffix):
                    part.unlink(missing_ok=True)
                    target = unpacked  # dieselbe Demo: vorhandene Datei und denselben Report nutzen
                    same = True
            if not same:
                target = _unique(folder, target.name)
        if part.exists():
            part.replace(target)  # erst die fertige Datei sichtbar machen
    finally:
        part.unlink(missing_ok=True)
    focus = {s.strip() for s in steamids.split(",") if s.strip()} or None
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "owner": _USER.get(),
            "status": "wartet",
            "name": _safe_name(filename),
            "stage": "Wartet",
            "frac": 0.0,
            "started": None,
            "estimate": None,
            "samples": 0,
            "cached": False,
            "report": None,
            "error": None,
        }
    _executor.submit(_run_archive_job if is_arc else _run_job, job_id, target, focus, bool(pro))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _get_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or not _own_job(job):
            raise HTTPException(404, "Auswertung nicht gefunden. Vielleicht wurde der Server neu gestartet. Reports stehen auf der Startseite.")
        return _job_view(job_id, job)


@app.get("/review", response_class=HTMLResponse)
def review_page(n: int = 5) -> str:
    from cstaktik import review

    hist = _load_hist()
    r = review.build(hist, max(1, min(n, 20)))
    if _me():  # mit Steam verbunden: nur das eigene Profil
        r["players"] = [x for x in r["players"] if x["sid"] == _me()]
        r["say"] = review._say(r["players"], r["n"]) + [x for x in r["say"] if x.startswith("Als Team")]
    return _env.get_template("review.html").render(nav_active="matches", r=r)


def _progress_ctx(p: str) -> dict:
    """Alles für Fortschritt und Fortschritt-Details: Profil, Fokus, Spieler-Tabs."""
    from cstaktik import pro
    from cstaktik.report.progress import profile

    hist = _load_hist()
    names = _names(hist)
    sids = sorted({s for h in hist for s in h.get("players", {})}, key=lambda s: names.get(s, s))
    sid = _default_sid({s: v for s, v in _players_state().items() if s in sids}, names, p) or (sids[0] if sids else None)
    if p in sids and not _me():  # mit Steam verbunden: nur das eigene Profil
        sid = p
    prof = profile(hist, sid, pro.duel_stats(_load_pro())) if sid else None
    if prof:
        prof["pro_duel_demos"] = sum(1 for d in _load_pro() if d.get("duels"))
    if prof:  # Kaufentscheidungen auf T: Team-Wert aus euren Matches gegen die Pros
        from cstaktik import playbook

        cfg = load_rules_config().get("playbook")
        mine, pros = [h for h in hist if sid in h.get("players", {})], _load_pro()
        prof["sides"] = []
        for side in ("t", "ct"):  # je Seite: nach dem Plant (T halten / CT Retake) und Kaufentscheidungen
            own_pp, pro_pp = playbook.postplant_mix(mine, side), playbook.postplant_mix(pros, side)
            own_b, pro_b = playbook.buy_mix(mine, cfg, side), playbook.buy_mix(pros, cfg, side)
            if own_pp["total"] or own_b["total"]:
                own_fb, pro_fb = playbook.firstblood_mix(mine, side), playbook.firstblood_mix(pros, side)
                key = playbook.SIDE_KEYS[side][0]
                prof["sides"].append({
                    "pro_demos": sum(1 for d in pros if d.get(key)),
                    "fb": {"own": own_fb, "pro": pro_fb, "reading": playbook.firstblood_reading(own_fb, pro_fb, side)},
                    "side": side, "pp": {"own": own_pp, "pro": pro_pp,
                                         "reading": playbook.postplant_reading(own_pp, pro_pp, side=side)},
                    "buys": {"own": own_b, "pro": pro_b, "reading": playbook.buy_reading(own_b, pro_b, side=side)}})
        prof["buy_cfg"] = {**playbook.DEFAULTS, **(cfg or {})}
        from cstaktik import levers

        prof["levers"] = levers.build(hist, pros, sid, cfg)
        from cstaktik import clutch

        prof["clutch"] = clutch.summary(hist, sid, pros)
        from cstaktik import impact

        prof["impact"] = impact.profile(hist, sid)
        from cstaktik import tilt

        prof["tilt"] = tilt.summary(hist, sid)
    auftrag = next((x for x in _auftrag(hist) if x["sid"] == sid), None)
    if prof:
        prof["summary"] = _profile_summary(prof, auftrag)
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in _mine(sids)]
    return {"p": prof, "a": auftrag, "tabs": tabs}


@app.get("/progress", response_class=HTMLResponse)
def progress_page(p: str = "") -> str:
    """Fortschritt auf einen Blick: Fokus-Verlauf, Impact-Trend, Stärke und Baustelle. Der Rest liegt unter Details."""
    ctx = _progress_ctx(p)
    sw = _strength_weakness(ctx["p"]) if ctx["p"] else {}
    return _env.get_template("profil.html").render(nav_active="progress", sw=sw, **ctx)


@app.get("/progress/details", response_class=HTMLResponse)
def progress_details(p: str = "") -> str:
    """Alle Auswertungen: Impact, Hebel, Duelle, Fehler, T/CT, Tilt, Clutch, Maps, letzte Matches."""
    return _env.get_template("fortschritt_details.html").render(nav_active="progress", **_progress_ctx(p))


_SIDE_GROUPS = (("fb", "rows", ("for", "against"), "Nach dem ersten Kill"),
                ("pp", "rows", ("up", "even", "down"), None),
                ("buys", "buys", ("eco", "force", "full"), "Kauf"))


def _strength_weakness(p: dict) -> dict:
    """Eine Stärke und eine Baustelle, nur aus Werten, die unter Details stehen, und nur bei klarer Datenlage:
    Impact nach Lage ab 10 Fällen und ±0,15 Runden pro Match, Seiten-Werte mit denselben Mindestzahlen wie die
    Texte der Seiten-Auswertung (mindestens 8 eigene und Pro-Runden, 15 Prozentpunkte Abstand). Baustelle zuerst der
    größte Hebel. Fehlt etwas, bleibt der Platz leer."""
    sid = p.get("sid")
    det = f"/progress/details?p={sid}"
    im = p.get("impact") or {}
    sure = [c for c in im.get("ctx") or [] if c.get("enough") and c.get("ctx") != "bomb"]
    strong = weak = None
    best = max(sure, key=lambda c: c["per_match"], default=None)
    if best and best["per_match"] >= 0.15:
        strong = {"title": best["label"], "text": f"{best['per_match_s']} Runden pro Match über dem Schnitt eurer Matches.",
                  "src": f"Impact nach Lage aus {best['n']} Kills und Toden, letzte {im['n']} Matches.",
                  "href": det + "#impact"}
    sides = []
    for sd in p.get("sides") or []:
        S = sd["side"].upper()
        for grp, field, keys, lbl in _SIDE_GROUPS:
            own, pro = (sd[grp]["own"].get(field) or {}), (sd[grp]["pro"].get(field) or {})
            where = lbl or ("Nach dem Plant" if sd["side"] == "t" else "Retake")
            for k in keys:
                o, q = own.get(k), pro.get(k)
                if o and q and o["n"] >= 8 and q["n"] >= 8 and abs(o["won_pct"] - q["won_pct"]) >= 15:
                    nd = sd.get("pro_demos")
                    basis = f"{q['n']} Runden" + (f" aus {nd} Demo{'s' if nd != 1 else ''}" if nd else "")
                    sides.append({"diff": o["won_pct"] - q["won_pct"], "title": f"{S}: {where}, {o['label']}",
                                  "text": f"Ihr gewinnt {o['won_pct']} %, {o['won']} von {o['n']}. "
                                          f"Pros: {q['won_pct']} % ({basis}).",
                                  "src": f"Eure {S}-Runden gegen die Pro-Demos, alle Maps.", "href": det + "#seiten"})
    if not strong:
        top = max(sides, key=lambda x: x["diff"], default=None)
        strong = top if top and top["diff"] > 0 else None
    if p.get("levers"):
        lv = p["levers"][0]
        weak = {"title": lv["title"],
                "text": lv["text"] if lv.get("thin") else f"Etwa {lv['gain_s']} Runden pro Match möglich. {lv['text']}",
                "src": "Gerechnet aus euren letzten Matches. Eine Rechnung, keine Garantie.", "href": det + "#hebel"}
    else:
        worst = min(sure, key=lambda c: c["per_match"], default=None)
        if worst and worst["per_match"] <= -0.15:
            weak = {"title": worst["label"], "text": f"{worst['per_match_s']} Runden pro Match unter dem Schnitt eurer Matches.",
                    "src": f"Impact nach Lage aus {worst['n']} Kills und Toden, letzte {im['n']} Matches.",
                    "href": det + "#impact"}
        else:
            low = min(sides, key=lambda x: x["diff"], default=None)
            weak = low if low and low["diff"] < 0 else None
    return {"strong": strong, "weak": weak}


def _profile_summary(p: dict, a: dict | None) -> list[dict]:
    """'Das Wichtigste' oben im Profil: die Aussagen, die die Auswertungen weiter unten schon treffen, an einem Ort.
    Nur Texte, die es unten gibt (nichts Neues), höchstens fünf."""
    out = []
    if a:
        ms = a.get("matches") or []
        last = ms[-1] if ms else None
        if last and last.get("rate") is not None:
            ok = last.get("met")  # wie der Fokus-Check: None = zu wenige Runden, zählt nicht
            out.append({"label": "Fokus", "anchor": "fokus", "tone": "" if ok is None else "good" if ok else "bad",
                        "text": f"{a['title']}. Letztes Match: {str(last['rate']).replace('.', ',')} pro 10 Runden, "
                                f"Ziel höchstens {str(a['target']).replace('.', ',')}."
                                + (" Zu wenige Runden, das Match zählt nicht." if ok is None
                                   else " Weiter so." if ok else "")})
        else:
            out.append({"label": "Fokus", "anchor": "fokus", "tone": "",
                        "text": f"{a['title']}: „{a['mantra']}“ Noch kein Match seit dem Fokus-Start."})
    if p.get("levers"):
        lv = p["levers"][0]
        out.append({"label": "Hebel", "anchor": "hebel", "tone": "bad",
                    "text": f"{lv['title']}. {lv['text']}" if lv.get("thin") else
                            f"{lv['title']}: etwa {lv['gain_s']} Runden pro Match möglich. {lv['text']}"})
    im = p.get("impact") or {}
    if im.get("ctx_reading"):
        out.append({"label": "Impact", "anchor": "impact", "tone": "", "text": im["ctx_reading"]})
    if p.get("reading"):
        out.append({"label": "Duelle", "anchor": "duelle", "tone": "", "text": p["reading"]})
    tl = (p.get("tilt") or {}).get("reading")
    if tl and "messbar schlechter" in tl:
        out.append({"label": "Tilt", "anchor": "tilt", "tone": "bad", "text": tl})
    cl = (p.get("clutch") or {}).get("reading")
    if cl:
        out.append({"label": "Clutch", "anchor": "clutch", "tone": "bad" if "liegen" in cl else "good", "text": cl})
    return out[:5]


@app.get("/progress/karte", response_class=HTMLResponse)
def progress(p: str = "") -> str:
    """Todes-Karte und Kurven eines Spielers. Öffnet mit dem eingeloggten Spieler (verbundene SteamID); andere
    Spieler nur ohne Steam-Verbindung (kein Login), dann per Tab. Die Seite nennt immer, wessen Daten sie zeigt."""
    from cstaktik.report.progress import build, karte_json

    hist = _load_hist()
    names = _names(hist)
    sids = sorted({s for h in hist for s in h.get("players", {})}, key=lambda s: names.get(s, s))
    sid = _default_sid({s: v for s, v in _players_state().items() if s in sids}, names, p) or (sids[0] if sids else None)
    if p in sids and not _me():
        sid = p
    show = [sid] if sid and _mine([sid]) else []
    data = build(hist, show, me=_me())
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in _mine(sids)]
    return _env.get_template("karte.html").render(nav_active="progress", data=data, data_json=karte_json(data),
                                                  tabs=tabs, sid=sid, who=names.get(sid) if show else None)


def _run_faceit_job(job_id: str) -> None:
    from cstaktik import faceit

    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        done = sum(1 for x in lines if x.startswith("ok"))
        update(stage=f"{done} Demos geladen" + (f" · zuletzt: {msg}" if msg else ""), frac=min(0.95, 0.05 + 0.08 * len(lines)))

    update(status="läuft", stage="FACEIT abfragen", started=time.monotonic())
    try:
        res = pipeline.faceit_sync(log=log)
        added = ", ".join(f"{m.removeprefix('de_').capitalize()} +{n}" for m, n in res["added"].items())
        update(status="fertig", stage="Fertig", frac=1.0, message=f"Pro-Demos geholt: {added}.")
    except faceit.FaceitError as exc:
        update(status="fehler", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        update(status="fehler", error=f"FACEIT-Sync fehlgeschlagen: {type(exc).__name__}: {exc}")


@app.post("/pro/sync")
def pro_sync() -> RedirectResponse:
    if not os.environ.get("FACEIT_API_KEY"):
        raise HTTPException(400, "FACEIT_API_KEY ist auf dem Server nicht gesetzt.")
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "wartet", "name": "Pro-Demos von FACEIT", "stage": "Wartet", "frac": 0.0,
                         "started": None, "estimate": None, "samples": 0, "cached": False, "report": None,
                         "error": None}
    _executor.submit(_run_faceit_job, job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/highlights", response_class=HTMLResponse)
def highlights_page(p: str = "") -> str:
    """Beste Plays und teuerste Momente über alle Matches (nach Siegchance), je mit Sprung ins Replay."""
    from cstaktik import impact

    hist = _load_hist()
    names = _names(hist)
    sids = sorted({m["sid"] for h in hist for m in h.get("moments") or [] if m.get("sid")}, key=lambda s: names.get(s, s))
    sid = _me() or (p if p in sids else None) or _default_sid({s: v for s, v in _players_state().items() if s in sids},
                                                               names) or (sids[0] if sids else None)
    hl = impact.highlights(hist, sid) if sid else None
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in _mine(sids)]
    return _env.get_template("highlights.html").render(nav_active="progress", hl=hl, name=names.get(sid, sid) if sid else None,
                                                       tabs=tabs)


@app.get("/mehr", response_class=HTMLResponse)
def more_page() -> str:
    """Einstellungen, seltene Auswertungen und die Anleitung an einem Ort."""
    return _env.get_template("mehr.html").render(nav_active="settings", n_history=len(_load_hist()), n_pro=len(_load_pro()))


@app.get("/spieler", response_class=HTMLResponse)
def players_page() -> str:
    """Wer wird analysiert? Spieler aus den letzten Matches zum Anklicken statt SteamIDs abtippen."""
    from cstaktik.config import load_focus_steamids

    from cstaktik import accounts

    return _env.get_template("spieler.html").render(nav_active="settings", roster=pipeline.roster(),
                                                    focus=sorted(load_focus_steamids()),
                                                    linked=bool(accounts.linked_steamids()))


@app.post("/spieler")
async def players_save(request: Request) -> RedirectResponse:
    from cstaktik import accounts
    from cstaktik.config import save_focus_steamids

    if accounts.linked_steamids():
        raise HTTPException(400, "Ausgewertet werden die mit Steam verbundenen Accounts. Die Auswahl hier gilt nur ohne Steam.")

    form = await request.form()
    chosen = [str(x) for x in form.getlist("sid") if str(x).isdigit()][:2]
    if not chosen:
        raise HTTPException(400, "Mindestens einen Spieler wählen.")
    names = {e["sid"]: e["name"] for e in pipeline.roster()}
    save_focus_steamids([(sid, names.get(sid, "")) for sid in chosen])
    return RedirectResponse(f"/jobs/{_start_rerender()}", status_code=303)


def _start_rerender() -> str:
    """Alle Reports und Aufträge im Hintergrund neu berechnen (neue Spielerauswahl)."""
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "wartet", "name": "Alles für die neue Spielerauswahl neu berechnen",
                         "stage": "Wartet", "frac": 0.0, "started": None, "estimate": None, "samples": 0,
                         "cached": False, "report": None, "error": None}
    _executor.submit(_run_rerender_job, job_id)
    return job_id


def _run_rerender_job(job_id: str) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft", stage="Reports neu berechnen", started=time.monotonic())
    try:
        n = pipeline.rerender_reports(progress=lambda stage, frac: update(stage=stage, frac=frac))
        update(status="fertig", stage="Fertig", frac=1.0,
               message=f"{n} Reports und alle Aufträge für die neue Spielerauswahl neu berechnet.")
    except Exception as exc:  # noqa: BLE001
        update(status="fehler", error=f"Neu berechnen fehlgeschlagen: {type(exc).__name__}: {exc}")


@app.get("/api/jobs/{job_id}")
def job_json(job_id: str) -> dict:
    return _get_job(job_id)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str) -> str:
    job = _get_job(job_id)
    return _env.get_template("job.html").render(nav_active="matches", job_id=job_id, name=job["name"])
