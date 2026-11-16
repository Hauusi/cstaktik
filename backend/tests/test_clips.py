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

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None):
        calls.update(music_ss=music_ss, words=words)
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
    assert "2 Kills gefunden" in page and f'/clips/{job["id"]}/video' in page and "http-equiv" not in page
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
    assert c.post("/clips", files={"video": ("a.txt", b"x", "text/plain")}, headers=O).status_code == 400
    c.post("/clips", files={"video": ("a.mp4", b"x", "video/mp4")}, headers=O)
    assert "kein eigener Kill gefunden" in c.get("/clips").text
