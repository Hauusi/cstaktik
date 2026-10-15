"""Accounts: Passwort-Hash, Sitzung, Login-Pflicht, Steam-Daten und Sharecode-Abruf."""

import pytest
from fastapi.testclient import TestClient

from cstaktik import accounts, steam_sync


def test_password_hash_and_session():
    h = accounts.hash_password("Geheim-12345")
    assert "Geheim" not in h and accounts.check_password("Geheim-12345", h)
    assert not accounts.check_password("falsch-12345", h)
    assert accounts.read_session(accounts.make_session("Hausi")) is None  # Nutzer gibt es (noch) nicht
    accounts.add_user("Hausi", "Test-Passwort-1")
    tok = accounts.make_session("Hausi")
    assert accounts.read_session(tok) == "Hausi"
    assert accounts.read_session("Hausi|9999999999|ä") is None  # kein Absturz bei Sonderzeichen
    assert accounts.read_session(tok.replace("Hausi", "Admin")) is None  # Signatur passt nicht mehr
    assert accounts.read_session(accounts.make_session("Hausi", days=-1)) is None  # abgelaufen
    accounts.set_password("Hausi", "Neues-Passwort-2")
    assert accounts.read_session(tok) is None  # Passwortwechsel meldet alte Sitzungen ab
    with pytest.raises(ValueError):
        accounts.add_user("Hausi2", "kurz")


def test_login_required_once_users_exist():
    from cstaktik import api

    c = TestClient(api.app)
    assert c.get("/mehr").status_code == 200  # noch keine Accounts: offen wie bisher
    accounts.add_user("Hausi", "Geheim-12345")
    r = c.get("/mehr", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert c.get("/fonts.css").status_code == 200  # öffentlich
    bad = c.post("/login", data={"name": "Hausi", "password": "nein-nein-nein", "next": "/mehr"},
                 headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert "falsch" in bad.headers["location"] and accounts.COOKIE not in bad.cookies
    ok = c.post("/login", data={"name": "Hausi", "password": "Geheim-12345", "next": "/mehr"},
                headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert ok.headers["location"] == "/mehr"
    assert c.get("/mehr").status_code == 200 and "Optionen" in c.get("/mehr").text
    assert "Eingeloggt als <b>Hausi</b>" in c.get("/konto").text


def test_open_redirect_blocked():
    from cstaktik import api

    accounts.add_user("Hausi", "Geheim-12345")
    r = TestClient(api.app).post("/login", data={"name": "Hausi", "password": "Geheim-12345",
                                                 "next": "//evil.example"},
                                 headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_steam_save_and_validation():
    accounts.add_user("Hausi", "Geheim-12345")
    with pytest.raises(ValueError, match="SteamID64"):
        accounts.save_steam("Hausi", "123", "ABCD-ABCDE-ABCD", "CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee")
    accounts.save_steam("Hausi", "76561198000000001", "ABCD-ABCDE-ABCD", "CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee")
    assert accounts.get_steam("Hausi")["auth_code"] == "ABCD-ABCDE-ABCD"


def test_next_codes_follows_chain_and_reports_errors():
    chain = {"CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa": "CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb",
             "CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb": "CSGO-ccccc-ccccc-ccccc-ccccc-ccccc"}

    def fake(params):
        nxt = chain.get(params["knowncode"])
        return (200, {"result": {"nextcode": nxt}}) if nxt else (202, {"result": {"nextcode": "n/a"}})

    codes, err = steam_sync.next_codes("7656", "ABCD-ABCDE-ABCD", "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa", "k", fake)
    assert codes == ["CSGO-bbbbb-bbbbb-bbbbb-bbbbb-bbbbb", "CSGO-ccccc-ccccc-ccccc-ccccc-ccccc"] and err is None
    codes, err = steam_sync.next_codes("7656", "x", "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa", "k", lambda p: (403, {}))
    assert codes == [] and "Authentication Code" in err

    accounts.add_user("Hausi", "Geheim-12345")
    accounts.save_steam("Hausi", "76561198000000001", "ABCD-ABCDE-ABCD", "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa")
    row = accounts.steam_users()[0]
    res = steam_sync.sync_user(row, key="k", get=fake)
    st = accounts.get_steam("Hausi")
    assert res == {"new": 2, "error": None} and st["last_code"] == "CSGO-ccccc-ccccc-ccccc-ccccc-ccccc"
    assert [c["code"] for c in st["codes"]] and len(st["codes"]) == 2
    assert steam_sync.sync_user(accounts.steam_users()[0])["error"].startswith("Es fehlt der Steam-Web-API-Schlüssel")
    accounts.set_setting("steam_web_api_key", "ABC")
    assert accounts.steam_key() == "ABC"


O = {"Origin": "http://testserver"}


def test_first_account_via_setup_page_only_once():
    from cstaktik import api

    c = TestClient(api.app)
    assert "Account anlegen" in c.get("/login").text
    r = c.post("/setup", data={"name": "Hausi", "password": "Geheim-12345", "password2": "Geheim-12345"},
               headers=O, follow_redirects=False)
    assert r.headers["location"].startswith("/konto") and accounts.has_users()
    assert "Eingeloggt als <b>Hausi</b>" in c.get("/konto").text  # direkt eingeloggt
    again = TestClient(api.app).post("/setup", data={"name": "X", "password": "Geheim-12345", "password2": "Geheim-12345"},
                                     headers=O)
    assert again.status_code == 403


def test_steam_openid_verify():
    from cstaktik import steam_openid

    rt = "http://testserver/auth/steam/callback?state=abc"
    good = {"openid.mode": "id_res", "openid.return_to": rt,
            "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198000000001"}
    assert steam_openid.verify(good, rt, post=lambda d: "ns:x\nis_valid:true\n") == "76561198000000001"
    assert steam_openid.verify(good, rt, post=lambda d: "is_valid:false") is None  # Steam bestätigt nicht
    assert steam_openid.verify({**good, "openid.return_to": "http://evil/"}, rt, post=lambda d: "is_valid:true") is None
    sent = {}
    steam_openid.verify(good, rt, post=lambda d: sent.update(d) or "is_valid:true")
    assert sent["openid.mode"] == "check_authentication"


def test_connect_steam_then_login_with_steam(monkeypatch):
    from cstaktik import api, steam_openid

    monkeypatch.setattr(steam_openid, "verify", lambda params, rt, post=None: "76561198000000001"
                        if rt.endswith("state=" + params.get("state", "")) else None)
    accounts.add_user("Hausi", "Geheim-12345")
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    start = c.get("/auth/steam", follow_redirects=False)
    assert start.headers["location"].startswith("https://steamcommunity.com/openid/login?")
    state = c.cookies.get("cstaktik_steam_state")
    r = c.get(f"/auth/steam/callback?state={state}", follow_redirects=False)
    assert "verbunden" in r.headers["location"] and accounts.get_steam("Hausi")["steamid"] == "76561198000000001"
    # neuer Browser ohne Sitzung: mit Steam einloggen
    c2 = TestClient(api.app)
    c2.get("/auth/steam", follow_redirects=False)
    r2 = c2.get(f"/auth/steam/callback?state={c2.cookies.get('cstaktik_steam_state')}", follow_redirects=False)
    assert r2.headers["location"] == "/" and c2.get("/mehr").status_code == 200
    # falscher state: abgelehnt
    c3 = TestClient(api.app)
    c3.get("/auth/steam", follow_redirects=False)
    r3 = c3.get("/auth/steam/callback?state=falsch", follow_redirects=False)
    assert "nicht" in r3.headers["location"] and "error" in r3.headers["location"]


def test_options_key_codes_and_second_user():
    from cstaktik import api

    accounts.add_user("Hausi", "Geheim-12345")
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    r = c.post("/konto", data={"auth_code": "ABCD-ABCDE-ABCD", "last_code": "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa"},
               headers=O, follow_redirects=False)
    assert "Steam" in r.headers["location"] and "error" in r.headers["location"]  # erst mit Steam verbinden
    accounts.link_steamid("Hausi", "76561198000000001")
    c.post("/konto", data={"auth_code": "ABCD-ABCDE-ABCD", "last_code": "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa"}, headers=O)
    assert accounts.get_steam("Hausi")["auth_code"] == "ABCD-ABCDE-ABCD"
    c.post("/konto/key", data={"key": "0123456789abcdef0123456789ABCDEF"}, headers=O)
    assert accounts.steam_key() == "0123456789ABCDEF0123456789ABCDEF"
    assert "gespeichert (…CDEF)" in c.get("/konto").text and "0123456789AB" not in c.get("/konto").text
    c.post("/konto/user", data={"name": "Bruder", "password": "Bruder-12345"}, headers=O)
    assert accounts.verify("Bruder", "Bruder-12345")
    with pytest.raises(ValueError, match="anderen Nutzer"):
        accounts.link_steamid("Bruder", "76561198000000001")


def test_entered_token_is_listed_and_empty_sync_explained(monkeypatch):
    from cstaktik import api, steam_sync

    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    monkeypatch.setattr(steam_sync, "_get", lambda params, timeout=15: (202, {"result": {"nextcode": "n/a"}}))
    accounts.set_setting("steam_web_api_key", "K")
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    r = c.post("/konto", data={"auth_code": "ABCD-ABCDE-ABCD", "last_code": "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa"},
               headers=O, follow_redirects=False)
    assert "Verbindung%20zu%20Steam%20klappt" in r.headers["location"]
    assert [x["code"] for x in accounts.get_steam("Hausi")["codes"]] == ["CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa"]


def test_steam_unreachable_gives_message_not_crash(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("Netz weg")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    codes, err = steam_sync.next_codes("7656", "ABCD-ABCDE-ABCD", "CSGO-aaaaa-aaaaa-aaaaa-aaaaa-aaaaa", "k")
    assert codes == [] and "nicht erreichbar" in err


def test_logged_in_player_sees_only_own_profile():
    from cstaktik import api, coaching, history, pipeline

    focus = {"lesson": "alone", "target": 1.0, "baseline": 2.0, "created_at": "2026-10-01T10:00", "matches": [],
             "status": "aktiv"}
    me, bro = "76561198000000001", "76561198000000002"
    coaching.save({"players": {me: {"focus": focus, "done": [], "drills": []},
                               bro: {"focus": {**focus, "lesson": "utility"}, "done": [], "drills": []}}},
                  pipeline.COACHING_FILE)
    history.save({"id": "a1", "map": "de_mirage", "rounds": 20, "analyzed_at": "2026-10-02T10:00",
                  "players": {me: {"name": "Satoru"}, bro: {"name": "Bruder"}}, "scenes": []}, pipeline.HISTORY_DIR)
    c = TestClient(api.app)
    both = c.get("/").text
    assert "Satoru" in both and "Bruder" in both  # ohne Accounts: beide wie bisher
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", me)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    home = c.get("/").text
    assert "Satoru" in home and "Bruder" not in home
    prog = c.get(f"/progress?p={bro}").text
    assert "Bruder" not in prog  # auch über den Link nicht das fremde Profil
    assert c.post(f"/training/done?p={bro}", headers=O, follow_redirects=False).status_code == 403
    assert c.post(f"/training/done?p={me}", headers=O, follow_redirects=False).status_code == 303
    assert "Bruder" not in c.get("/review").text


def test_personal_report_injects_own_steamid(tmp_path):
    import asyncio

    from fastapi.responses import Response

    from cstaktik import api
    from cstaktik.config import load_rules_config
    from cstaktik.report.render import render_report
    from cstaktik.rules import analyze
    from synth import build_match

    from cstaktik.report import render

    m = build_match()
    orig = render._duel_cmp
    from cstaktik import duels

    row = {**duels.stats([{"won": True, "err": 5.0}]), "sid": "76561198000000002", "name": "Bruder", "reading": None}
    render._duel_cmp = lambda match: {"players": [row], "pro": None}
    try:
        html = render_report(m, analyze(m, load_rules_config()), maps_dirs=[tmp_path])
    finally:
        render._duel_cmp = orig
    assert 'data-sid="76561198000000002"' in html and "window.__ME" in html  # markiert, Filter-Skript vorhanden

    async def run():
        async def it():
            yield b"<html><head></head><body>x</body></html>"
        r = Response(media_type="text/html")
        r.body_iterator = it()
        return await api._personal_report(r, "76561198000000001")
    out = asyncio.run(run())
    assert b'window.__ME="76561198000000001";</script></head>' in out.body


def test_only_steam_linked_players_are_analysed(monkeypatch):
    from cstaktik import api
    from cstaktik.config import load_focus_steamids, save_focus_steamids
    from cstaktik import config

    monkeypatch.setattr(config, "PLAYERS_FILE", accounts.DB_FILE.parent / "players.yaml")
    save_focus_steamids([("76561198000000001", "Ich"), ("76561198000000002", "Bruder")])
    assert load_focus_steamids() == {"76561198000000001", "76561198000000002"}  # niemand verbunden: players.yaml
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    assert load_focus_steamids() == {"76561198000000001"}  # verbunden: nur er, der Bruder nicht
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    assert "verbundenen Accounts" in c.get("/spieler").text
    assert c.post("/spieler", data={"sid": "76561198000000002"}, headers=O).status_code == 400


def test_each_account_sees_only_own_matches():
    from cstaktik import api, history, pipeline

    me, bro = "76561198000000001", "76561198000000002"
    pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for i, sid, name in (("m1", me, "Satoru"), ("m2", bro, "Datenschutzduhund")):
        history.save({"id": i, "map": "de_mirage", "rounds": 20, "analyzed_at": f"2026-10-0{i[-1]}T10:00",
                      "report_file": f"{i}.html", "won": 13, "lost": 7, "players": {sid: {"name": name}},
                      "scenes": []}, pipeline.HISTORY_DIR)
        (pipeline.REPORTS_DIR / f"{i}.html").write_text(f"<html><head><title>Mirage 13:7 – x</title></head>{name}</html>")
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Hausi", me)
    a, b = TestClient(api.app), TestClient(api.app)
    a.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    b.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    # Bruder noch nicht verbunden: sieht nichts, wird zum Verbinden aufgefordert, darf nicht hochladen
    home_b = b.get("/").text
    assert "Mit Steam verbinden" in home_b and "Satoru" not in home_b
    blocked = "Report nicht gefunden."  # Antwort des Filters (die Reports selbst liegen im Test nicht im Mount-Ordner)
    assert b.get("/reports/m1.html").text == blocked
    assert b.post("/analyze", files={"demo": ("x.dem", b"demo")}, headers=O).status_code == 400
    # ich: nur mein Match
    ma = a.get("/matches").text
    assert "m1.html" in ma and "m2.html" not in ma
    assert a.get("/reports/m2.html").text == blocked and a.get("/reports/m1.html").text != blocked
    # Bruder verbunden: nur sein Match
    accounts.link_steamid("Bruder", bro)
    mb = b.get("/matches").text
    assert "m2.html" in mb and "m1.html" not in mb and b.get("/reports/m1.html").text == blocked


def test_https_proxy_locks_direct_access():
    from cstaktik import api

    c = TestClient(api.app)
    assert c.get("/login", follow_redirects=False).status_code == 200  # ohne HTTPS-Proxy: wie bisher
    c.get("/login", headers={"x-forwarded-proto": "https", "host": "evil.example"})  # direkt: Header zählt nicht
    assert accounts.get_setting("public_url") is None
    TestClient(api.app, base_url="https://cs2coach.duckdns.org").get("/login")  # über den Proxy (Schema https)
    assert accounts.get_setting("public_url") == "https://cs2coach.duckdns.org"
    r = c.get("/login?next=/x", follow_redirects=False)  # direkt von außen: umgeleitet
    assert r.status_code == 307 and r.headers["location"] == "https://cs2coach.duckdns.org/login?next=/x"
    assert c.post("/login", data={"name": "a", "password": "b"}, headers=O).status_code == 403
    accounts.set_setting("public_url", None)
