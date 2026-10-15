"""Automatischer Demo-Download: Konfiguration für cs-demo-downloader und Übernahme fertiger Demos."""

import json

from fastapi.testclient import TestClient

from cstaktik import accounts, api, autodl, pipeline

O = {"Origin": "http://testserver"}


def _setup_user():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    accounts.set_setting("steam_web_api_key", "A" * 32)
    accounts.save_codes("Hausi", "ABCD-12345-WXYZ", "CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee")


def test_config_needs_bot_key_and_codes():
    assert autodl.build_config() is None
    _setup_user()
    assert autodl.build_config() is None  # noch kein Bot
    c = TestClient(api.app)
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    r = c.post("/konto/bot", data={"bot_user": "meinbot", "bot_pass": "bot-pass-123"}, headers=O, follow_redirects=False)
    assert r.status_code == 303
    cfg = json.loads((autodl.CONFIG_DIR / "config.json").read_text())
    assert cfg["authCodeLogin"] == {"username": "meinbot", "password": "bot-pass-123", "secret": ""}
    assert cfg["steamApiKey"] == "A" * 32
    assert cfg["authCodes"] == [{"authCode": "ABCD-12345-WXYZ", "steamId64": "76561198000000001",
                                 "oldestShareCode": "CSGO-aaaaa-bbbbb-ccccc-ddddd-eeeee"}]
    page = c.get("/konto").text
    assert "Automatischer Download" in page and "docker run" in page and "meinbot" in page
    assert "bot-pass-123" not in page  # Passwort nie zurück an den Browser
    c.post("/konto/bot", data={"bot_user": "meinbot", "bot_pass": ""}, headers=O)  # leer = Passwort bleibt
    assert accounts.get_setting("autodl_bot_pass") == "bot-pass-123"


def test_finished_demo_is_taken_and_analysed(monkeypatch):
    autodl.DEMOS_DIR.mkdir(parents=True)
    (autodl.DEMOS_DIR / "temp").mkdir()
    (autodl.DEMOS_DIR / "temp" / "halb.dem").write_bytes(b"x")  # noch im Download: nicht anfassen
    (autodl.DEMOS_DIR / "match730_1_2_129.dem").write_bytes(b"PBDEMS2 demo")
    ran = []
    monkeypatch.setattr(api, "_jobs", {})
    monkeypatch.setattr(api._executor, "submit", lambda fn: ran.append(fn))
    assert api._autodl_import() == 1
    assert (pipeline.DEMOS_DIR / "match730_1_2_129.dem").exists()
    assert not (autodl.DEMOS_DIR / "match730_1_2_129.dem").exists() and (autodl.DEMOS_DIR / "temp" / "halb.dem").exists()
    assert api._autodl_import() == 0  # nicht doppelt
    monkeypatch.setattr(api, "_run_job", lambda job_id, target, focus: None)
    ran[0]()
    assert autodl.status()["imported"][0]["name"] == "match730_1_2_129.dem"
