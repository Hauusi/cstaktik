import gzip
import io
import urllib.error

import pytest

from cstaktik import faceit

CFG = {"hubs": ["hub1"], "maps": ["de_mirage", "de_dust2"], "per_map": 1, "max_scan": 300}


def M(mid, mp, demo=True):
    return {"match_id": mid, "voting": {"map": {"pick": [mp]}}, "demo_url": [f"https://res/{mid}.dem.gz"] if demo else []}


def test_match_map():
    assert faceit.match_map(M("a", "de_mirage")) == "de_mirage"
    assert faceit.match_map({}) is None


def test_missing_key(monkeypatch):
    monkeypatch.delenv("FACEIT_API_KEY", raising=False)
    with pytest.raises(faceit.FaceitError, match="FACEIT_API_KEY"):
        faceit.hub_matches("x")


def test_403_on_download_api_is_explained(monkeypatch):
    monkeypatch.setenv("FACEIT_API_KEY", "k")

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

    monkeypatch.setattr(faceit.urllib.request, "urlopen", boom)
    with pytest.raises(faceit.FaceitError, match="Downloads API verweigert"):
        faceit.signed_url("https://res/x")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("payload,ok", [
    (gzip.compress(b"PBDEMS2\x00rest"), True),
    (b"PBDEMS2\x00raw", True),
    (__import__("zstandard").ZstdCompressor().compress(b"PBDEMS2\x00zst"), True),
    (b"\x28\xb5\x2f\xfdkaputt", False),
    (b"<html>", False),
])
def test_download_formats(tmp_path, monkeypatch, payload, ok):
    monkeypatch.setattr(faceit.urllib.request, "urlopen", lambda req, timeout: _Resp(payload))
    if ok:
        out = faceit.download("https://signed", tmp_path, "m1")
        assert out.read_bytes().startswith(b"PBDEMS2") and not list(tmp_path.glob("*.part"))
    else:
        with pytest.raises(faceit.FaceitError):
            faceit.download("https://signed", tmp_path, "m1")


def test_sync_quota_dedup_and_failures(tmp_path, monkeypatch):
    matches = [M("a", "de_mirage"), M("b", "de_mirage"), M("c", "de_inferno"), M("d", "de_dust2", demo=False),
               M("e", "de_dust2"), M("f", "de_dust2")]
    monkeypatch.setattr(faceit, "hub_matches", lambda hub, offset=0, limit=50: matches if offset == 0 else [])
    monkeypatch.setattr(faceit, "signed_url", lambda res: res + "?signed")

    def fake_download(url, d, name):
        if "/e." in url:
            raise faceit.FaceitError("kaputt")
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.dem"
        p.write_bytes(b"PBDEMS2")
        return p

    monkeypatch.setattr(faceit, "download", fake_download)
    seen = []

    def run_pro(path):
        seen.append(path.name)
        return {"map": "de_dust2" if "_f" in path.name else "de_mirage"}

    res = faceit.sync(CFG, tmp_path / "pro", tmp_path / "tmp", run_pro, log=lambda m: None, sleep_s=0)
    assert res["added"] == {"de_mirage": 1, "de_dust2": 1}
    assert seen == ["faceit_a.dem", "faceit_f.dem"]  # b: Mirage voll, c: falsche Map, d: ohne Demo, e: Fehler
    assert not list((tmp_path / "tmp").glob("*.dem"))  # Rohdateien gelöscht
    # zweiter Lauf: a/f bereits erledigt, e als fehlgeschlagen gemerkt -> nächste Mirage (b) wird geholt
    seen.clear()
    res2 = faceit.sync(CFG, tmp_path / "pro", tmp_path / "tmp", run_pro, log=lambda m: None, sleep_s=0)
    assert seen == ["faceit_b.dem"] and res2["total"]["de_mirage"] == 2


def test_sync_stops_on_missing_download_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(faceit, "hub_matches", lambda hub, offset=0, limit=50: [M("a", "de_mirage")] if offset == 0 else [])

    def denied(res):
        raise faceit.FaceitError("Downloads API verweigert (403): ...")

    monkeypatch.setattr(faceit, "signed_url", denied)
    with pytest.raises(faceit.FaceitError, match="Downloads API verweigert"):
        faceit.sync(CFG, tmp_path / "pro", tmp_path / "tmp", lambda p: {}, log=lambda m: None, sleep_s=0)


def test_sync_route_needs_key(monkeypatch):
    from fastapi.testclient import TestClient

    from cstaktik import api

    monkeypatch.delenv("FACEIT_API_KEY", raising=False)
    assert TestClient(api.app).post("/pro/sync").status_code == 400
