"""Clips in der App: Upload, Hintergrund-Schnitt (gemockt), Ansehen, Löschen, nur eigene Aufträge."""

from fastapi.testclient import TestClient

from cstaktik import accounts, api, clips, memeclip

O = {"Origin": "http://testserver"}


def _client(name="Hausi"):
    accounts.add_user(name, "Geheim-12345")
    c = TestClient(api.app)
    c.post("/login", data={"name": name, "password": "Geheim-12345"}, headers=O)
    return c


def test_upload_render_view_delete(monkeypatch):
    calls = {}

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch"):
        calls.update(music_ss=music_ss, words=words)
        if song:
            calls["song"] = song
        open(out, "wb").write(b"video")
        return {"kills": [1, 2], "seconds": 9.5, "bpm": 120.0}

    monkeypatch.setattr(memeclip, "make_beat", fake_beat)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))  # im Test sofort statt im Thread
    c = _client()
    assert 'data-block="upload"' in c.get("/clips").text
    r = c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
               data={"music_ss": "12,5", "lyrics": "EINS  ZWEI"}, headers=O, follow_redirects=False)
    assert r.status_code == 303 and calls == {"music_ss": 12.5, "words": ["EINS", "ZWEI"]}
    page = c.get("/clips").text
    job = clips.jobs("Hausi")[0]
    assert "2 Kills im Video" in page and f'/clips/{job["id"]}/video' in page and "http-equiv" not in page
    assert c.get(f"/clips/{job['id']}/video").content == b"video"
    other = _client("Bruder")
    assert other.get(f"/clips/{job['id']}/video").status_code == 404  # nur eigene Clips
    c.post(f"/clips/{job['id']}/delete", headers=O)
    assert clips.jobs("Hausi") == []


def test_no_kill_and_bad_file(monkeypatch):
    def no_kill(src, out, progress=None):
        raise ValueError("Im Clip wurde kein eigener Kill gefunden.")

    monkeypatch.setattr(memeclip, "make", no_kill)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    c = _client()
    assert clips.safe_ext("VID_1.MP4", ".mp4") == ".mp4" and clips.safe_ext("1000012345", ".mp4") == ".mp4"
    assert clips.safe_ext("a.3gp", ".mp4") == ".3gp" and clips.safe_ext("x.tar.gz!!", ".mp3") == ".mp3"
    c.post("/clips", files={"video": ("a.mp4", b"x", "video/mp4")}, headers=O)
    assert "kein eigener Kill gefunden" in c.get("/clips").text


def test_chunked_upload(monkeypatch):
    def fake(src, out, progress=None):
        assert [open(x, "rb").read() for x in src] == [b"aaabbb", b"zz"]  # Stücke in Reihenfolge, zwei Clips
        open(out, "wb").write(b"v")
        return {"kills": [1], "seconds": 3.0}  # noqa

    monkeypatch.setattr(memeclip, "make", fake)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    c = _client()
    assert c.post("/clips/new", json={"v": 4}, headers=O).status_code == 400
    assert c.post("/clips/new", json={"videos": ["a.mp4"]}, headers=O).status_code == 409  # alter Stand der Seite/App
    jid = c.post("/clips/new", json={"v": 4, "videos": ["mein clip.mp4", "1000012345"], "music_ss": "3"}, headers=O).json()["id"]
    assert "Upload nicht abgeschlossen" in c.get("/clips").text
    assert c.post(f"/clips/{jid}/start", headers=O).status_code == 404  # noch keine Datei
    for part in (b"aaa", b"bbb"):
        assert c.post(f"/clips/{jid}/chunk?kind=video", content=part, headers=O).json()["ok"]
    assert c.post(f"/clips/{jid}/chunk?kind=video&n=1", content=b"zz", headers=O).json()["ok"]
    assert c.post(f"/clips/{jid}/chunk?kind=video&n=2", content=b"zz", headers=O).status_code == 404
    assert c.post(f"/clips/{jid}/chunk?kind=video", content=b"x" * (2 * 1024 * 1024 + 1), headers=O).status_code == 413
    assert c.post(f"/clips/{jid}/start", headers=O).json()["ok"]
    assert clips.jobs("Hausi")[0]["status"] == "fertig"
    assert c.post(f"/clips/{jid}/chunk?kind=video", content=b"c", headers=O).status_code == 404  # nach dem Start zu
