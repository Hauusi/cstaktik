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
    assert c.get("/mehr").status_code == 200 and "Konto und Steam" in c.get("/mehr").text
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
    assert steam_sync.sync_user(accounts.steam_users()[0])["error"].startswith("Auf dem Server fehlt")
