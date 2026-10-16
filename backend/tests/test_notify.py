"""Push-Nachrichten: Verschlüsselung (RFC 8291), VAPID-Ausweis, Versand an Mitspieler, App-Dateien ohne Login."""

import json
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

from cstaktik import accounts, api, notify

O = {"Origin": "http://testserver"}


def _device():
    """Wie ein Browser: eigenes Schlüsselpaar und Auth-Geheimnis."""
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": notify.b64u(pub), "auth": notify.b64u(auth)}}


def _decrypt(body: bytes, key, sub) -> bytes:
    """Entschlüsseln wie der Browser (Gegenprobe zu notify.encrypt)."""
    salt, (rs, idlen) = body[:16], struct.unpack("!IB", body[16:21])
    as_public = body[21:21 + idlen]
    ua_public = notify.unb64u(sub["keys"]["p256dh"])
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = HKDF(hashes.SHA256(), 32, notify.unb64u(sub["keys"]["auth"]),
               b"WebPush: info\x00" + ua_public + as_public).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    assert rs == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_roundtrip():
    key, sub = _device()
    body = notify.encrypt(b'{"title": "Mirage 13:10"}', sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert _decrypt(body, key, sub) == b'{"title": "Mirage 13:10"}'


def test_send_signs_with_vapid_and_drops_expired(monkeypatch):
    accounts.add_user("Hausi", "Geheim-12345")
    key, sub = _device()
    notify.subscribe("Hausi", sub)
    sent = []

    def post(url, body, headers):
        sent.append((url, body, headers))
        return 201

    assert notify.send_user("Hausi", {"title": "Test"}, post) == 1
    url, body, headers = sent[0]
    assert json.loads(_decrypt(body, key, sub)) == {"title": "Test"}
    assert headers["Content-Encoding"] == "aes128gcm"
    t, k = headers["Authorization"].removeprefix("vapid t=").split(", k=")
    h, c, sig = t.split(".")
    assert json.loads(notify.unb64u(c))["aud"] == "https://fcm.googleapis.com"
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), notify.unb64u(k))
    raw = notify.unb64u(sig)
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))  # wirft bei falscher Signatur
    assert notify.send_user("Hausi", {"title": "x"}, lambda *a: 410) == 0
    assert notify.subs("Hausi") == []  # abgelaufenes Abo gelöscht


def test_notify_match_only_players():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.add_user("Bruder", "Geheim-12345")
    accounts.link_steamid("Hausi", "76561198000000001")
    accounts.link_steamid("Bruder", "76561198000000002")
    for u in ("Hausi", "Bruder"):
        notify.subscribe(u, {**_device()[1], "endpoint": f"https://fcm.googleapis.com/fcm/send/{u}"})
    got = []
    h = {"map": "de_mirage", "won": 13, "lost": 10, "report_file": "r.html",
         "players": {"76561198000000001": "Hausi"}, "impact": {"76561198000000001": {"total": 250}}}
    assert notify.notify_match(h, lambda url, body, headers: got.append(url) or 201) == 1
    assert got == ["https://fcm.googleapis.com/fcm/send/Hausi"]
    msg = notify.match_message(h, "76561198000000001")
    assert msg["title"] == "Mirage 13:10 gewonnen" and msg["url"] == "/reports/r.html" and "Impact" in msg["body"]


def test_app_files_without_login_and_push_routes():
    accounts.add_user("Hausi", "Geheim-12345")
    c = TestClient(api.app)
    assert c.get("/manifest.webmanifest").json()["display"] == "standalone"
    assert "showNotification" in c.get("/sw.js").text
    assert c.get("/icon-192.png").headers["content-type"] == "image/png"
    assert c.get("/push/key", follow_redirects=False).status_code in (303, 401)  # nur eingeloggt
    c.post("/login", data={"name": "Hausi", "password": "Geheim-12345"}, headers=O)
    assert len(notify.unb64u(c.get("/push/key").json()["key"])) == 65
    _, sub = _device()
    assert c.post("/push/subscribe", json=sub, headers=O).json() == {"ok": True}
    assert c.post("/push/subscribe", json={"endpoint": "http://x"}, headers=O).status_code == 400
    assert c.post("/push/subscribe", json={**sub, "endpoint": "https://intern.example/x"}, headers=O).status_code == 400
    assert notify.subs("Hausi") == [sub]
    c.post("/push/unsubscribe", json={"endpoint": sub["endpoint"]}, headers=O)
    assert notify.subs("Hausi") == []
    assert "Benachrichtigungen" in c.get("/konto").text


def test_new_matches_marked_until_opened():
    accounts.add_user("Hausi", "Geheim-12345")
    since, files = api._seen("Hausi")
    old = {"report_file": "alt.html", "analyzed_at": "2000-01-01T00:00:00"}
    new = {"report_file": "neu.html", "analyzed_at": "2999-01-01T00:00:00"}
    seen = api._seen("Hausi")
    assert not api._is_new(old, seen)  # vor dem Start der Zählung: gilt als gesehen
    assert api._is_new(new, seen)
    api._mark_seen("Hausi", "neu.html")
    assert not api._is_new(new, api._seen("Hausi"))
    assert api._seen("Hausi")[0] == since
    assert api._seen(None) is None


def test_bad_keys_rejected_and_device_not_silently_moved():
    accounts.add_user("Hausi", "Geheim-12345")
    accounts.add_user("Bruder", "Geheim-12345")
    _, sub = _device()
    import pytest
    with pytest.raises(ValueError):
        notify.subscribe("Hausi", {**sub, "keys": {"p256dh": "AAAA", "auth": sub["keys"]["auth"]}})
    notify.subscribe("Hausi", sub)
    c = TestClient(api.app)
    c.post("/login", data={"name": "Bruder", "password": "Geheim-12345"}, headers=O)
    r = c.post("/push/subscribe", json=sub, headers=O)
    assert r.status_code == 409 and r.json()["owner"] == "Hausi"
    assert c.post("/push/subscribe", json={**sub, "take": True}, headers=O).json() == {"ok": True}
    assert notify.owner(sub["endpoint"]) == "Bruder"


def test_removed_bot_deletes_config():
    from cstaktik import autodl

    autodl.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (autodl.CONFIG_DIR / "config.json").write_text("{}")
    assert autodl.write_config() is False
    assert not (autodl.CONFIG_DIR / "config.json").exists()
