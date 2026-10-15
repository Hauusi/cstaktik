"""Automatischer Download über den eigenen Steam-Account: Login, Matchliste, Download (ohne echtes Netz)."""

import base64
import bz2
import io
import json
from urllib.parse import unquote
from http.cookiejar import Cookie

import pytest
from fastapi.testclient import TestClient

from cstaktik import accounts, api, gcpd

O = {"Origin": "http://testserver"}
# kleiner Test-Schlüssel (2048 Bit wie bei Steam ist nicht nötig, nur genug Platz für Polsterung)
MOD = format((1 << 1023) + 12345 | 1, "x")
URL = "https://replay123.valve.net/730/003700000000000000001_0123456789.dem.bz2"


def _fake_http(calls):
    def http(url, data=None, cookies=None, timeout=20):
        calls.append((url, data))
        if "GetPasswordRSAPublicKey" in url:
            return json.dumps({"response": {"publickey_mod": MOD, "publickey_exp": "010001", "timestamp": "7"}}).encode()
        if "BeginAuthSessionViaCredentials" in url:
            return json.dumps({"response": {"client_id": 11, "request_id": "cmVx", "steamid": "76561198000000001",
                                            "allowed_confirmations": [{"confirmation_type": 3}]}}).encode()
        if "UpdateAuthSessionWithSteamGuardCode" in url:
            return b'{"response": {}}'
        if "PollAuthSessionStatus" in url:
            return b'{"response": {"refresh_token": "tok.en.x"}}'
        if "finalizelogin" in url:
            return json.dumps({"steamID": "76561198000000001", "transfer_info": [
                {"url": "https://steamcommunity.com/login/settoken", "params": {"nonce": "n"}}]}).encode()
        if "settoken" in url:
            cookies.set_cookie(Cookie(0, "steamLoginSecure", "x", None, False, "steamcommunity.com", True, False,
                                      "/", True, True, None, False, None, None, {}))
            return b"ok"
        if "gcpd/730" in url:
            return f'<script>g_sGcContinueToken = "1";</script><a href="{URL}">Download</a>'.encode()
        raise AssertionError(url)
    return http


def test_rsa_encrypt_has_key_length():
    enc = gcpd._rsa_encrypt("geheim", MOD, "010001")
    assert len(base64.b64decode(enc)) == 128
    with pytest.raises(gcpd.SteamLoginError):
        gcpd._rsa_encrypt("x" * 200, MOD, "010001")


def test_login_flow_never_sends_plain_password():
    calls = []
    sess = gcpd.begin_login("hausi", "Klartext-Passwort", _fake_http(calls))
    assert sess["needs"] == "app" and sess["steamid"] == "76561198000000001"
    assert gcpd.finish_login(sess, "ab12c", _fake_http(calls), wait_s=0) == "tok.en.x"
    assert not any("Klartext-Passwort" in json.dumps(d) for _, d in calls)
    code = [d for u, d in calls if "SteamGuardCode" in u][0]
    assert code["code"] == "AB12C" and code["code_type"] == "3"


def test_fetch_new_downloads_once():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    accounts.set_setting("gcpd_token:Hausi", "tok.en.x")
    payload = bz2.compress(b"HL2DEMO-test")
    opened = []

    def http_open(u):
        opened.append(u)
        return io.BytesIO(payload)

    out = gcpd.fetch_new("Hausi", _fake_http([]), http_open)
    assert [p.name for p in out] == ["match730_003700000000000000001.dem"]
    assert out[0].read_bytes() == b"HL2DEMO-test"
    assert gcpd.fetch_new("Hausi", _fake_http([]), http_open) == []  # schon erledigt
    assert opened == [URL]
    assert accounts.get_setting("gcpd_error:Hausi") is None


def test_expired_login_is_reported():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    accounts.set_setting("gcpd_token:Hausi", "alt")

    def http(url, data=None, cookies=None, timeout=20):
        return b'{"transfer_info": []}'

    with pytest.raises(gcpd.SteamLoginError):
        gcpd.fetch_new("Hausi", http)
    assert "neu anmelden" in accounts.get_setting("gcpd_error:Hausi")


def test_download_rejects_foreign_links(tmp_path):
    with pytest.raises(ValueError):
        gcpd.download("https://example.com/x.dem.bz2", tmp_path / "x.dem", lambda u: io.BytesIO(b""))


def test_steam_login_requires_https():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    r = c.post("/konto/steamlogin", data={"steam_user": "hausi", "steam_pass": "x"}, headers=O,
               follow_redirects=False)
    assert r.status_code == 303 and "HTTPS" in unquote(r.headers["location"])


def _jwt(sub):
    import base64 as b
    body = b.urlsafe_b64encode(json.dumps({"sub": sub, "exp": 2000000000}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def test_qr_login(monkeypatch):
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    polls = iter([{"new_challenge_url": "https://s.team/q/1/neu", "new_client_id": 22},
                  {"refresh_token": _jwt("76561198000000001")}])

    def http(url, data=None, cookies=None, timeout=20):
        if "BeginAuthSessionViaQR" in url:
            return json.dumps({"response": {"client_id": 21, "request_id": "cQ", "challenge_url": "https://s.team/q/1/a"}}).encode()
        if "PollAuthSessionStatus" in url:
            return json.dumps({"response": next(polls)}).encode()
        raise AssertionError(url)

    monkeypatch.setattr(gcpd, "_http", http)
    monkeypatch.setattr(api, "_gcpd_run", lambda users=None: None)
    c = TestClient(api.app, base_url="https://testserver")
    Os = {"Origin": "https://testserver"}
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=Os)
    r = c.post("/konto/steamqr", headers=Os, follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    assert "s.team/q/1/a" in c.get("/konto").text
    assert c.get("/konto/steamqr/status").json() == {"state": "wait", "url": "https://s.team/q/1/neu"}
    assert c.get("/konto/steamqr/status").json() == {"state": "done"}
    assert gcpd.token_steamid(accounts.get_setting("gcpd_token:Hausi")) == "76561198000000001"


def test_qr_login_rejects_other_account(monkeypatch):
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    api._STEAM_LOGINS["Hausi"] = {"client_id": "1", "request_id": "r", "url": "u", "qr": True, "until": 9e12}
    monkeypatch.setattr(gcpd, "poll_qr", lambda sess: _jwt("76561198000000999"))
    c = TestClient(api.app, base_url="https://testserver")
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers={"Origin": "https://testserver"})
    assert c.get("/konto/steamqr/status").json()["state"] == "error"
    assert accounts.get_setting("gcpd_token:Hausi") is None
