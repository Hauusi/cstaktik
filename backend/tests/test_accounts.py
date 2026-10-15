"""Accounts: Passwort-Hash, Sitzung, Login-Pflicht, Steam-Daten und Sharecode-Abruf."""

import pytest
from fastapi.testclient import TestClient

from cstaktik import accounts, steam_sync


def test_password_hash_and_session():
    h = accounts.hash_password("Geheim-12345")
    assert "Geheim" not in h and accounts.check_password("Geheim-12345", h)
    assert not accounts.check_password("falsch-12345", h)
    tok = accounts.make_session("Hausi")
    assert accounts.read_session(tok) == "Hausi"
    assert accounts.read_session(tok.replace("Hausi", "Admin")) is None  # Signatur passt nicht mehr
    assert accounts.read_session(accounts.make_session("Hausi", days=-1)) is None  # abgelaufen
    with pytest.raises(ValueError):
        accounts.add_user("Hausi", "kurz")


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
