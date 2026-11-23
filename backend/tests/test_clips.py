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

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch", lyrics_shift=0.0,
                  drop_at=None, length="abschnitt"):
        calls.update(music_ss=music_ss, words=words)
        if drop_at is not None:
            calls["drop_at"] = drop_at
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
    assert r.status_code == 303 and calls == {"music_ss": 12.5, "words": ["EINS", "ZWEI\u00b6"]}
    page = c.get("/clips").text
    job = clips.jobs("Hausi")[0]
    assert "2 Kills im Video" in page and f'/clips/{job["id"]}/video' in page and "http-equiv" not in page
    assert c.get(f"/clips/{job['id']}/video").content == b"video"
    # Startfeld leer, Songtext eingefügt: Musik ab Anfang statt am Drop (Nutzer: Drop lag mitten im Lied)
    from cstaktik import beats

    monkeypatch.setattr(beats, "find_drop", lambda m: (_ for _ in ()).throw(AssertionError("kein Drop suchen")))
    monkeypatch.setattr(clips, "find_start", lambda m, ly, so: (None, so, "Song bei LRCLIB nicht gefunden"))
    c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
           data={"music_ss": "", "lyrics": "SO YOU KNOW"}, headers=O, follow_redirects=False)
    assert calls["music_ss"] == 0.0 and "Song bei LRCLIB nicht gefunden" in c.get("/clips").text
    for x in clips.jobs("Hausi"):
        if x["id"] != job["id"]:
            c.post(f"/clips/{x['id']}/delete", headers=O)
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


def test_lyrics_timing_adjust_routes(monkeypatch):
    import json
    c = _client()
    d = clips.new_job("Hausi")
    clips.set_state(d, status="fertig", name="x", music=True)
    (d / "out.mp4").write_bytes(b"v"); (d / "out.base.mp4").write_bytes(b"b")
    lyr = {"flat": [{"a": 1.0, "b": 1.4, "txt": "PAPA", "eol": True, "stop": 3.0}], "walls": [], "total": 5.0,
           "out_w": 1080, "out_h": 1920, "box": 1080, "box_y": 440, "box_x": 0, "fps": 60, "y_mid": 699, "band": 360,
           "font": "", "shift": 0.0}
    (d / "out.lyrics.json").write_text(json.dumps(lyr))
    page = c.get("/clips").text
    assert "Songtext-Timing nachjustieren" in page and f'data-job="{d.name}"' in page
    r = c.get(f"/clips/{d.name}/lyrics").json()
    assert r["words"][0]["txt"] == "PAPA" and r["words"][0]["fade"] and abs(r["y"] - 699 / 1920) < 1e-6
    assert c.get(f"/clips/{d.name}/base").status_code == 200 and c.get("/clips/font.ttf").status_code == 200
    got = {}
    monkeypatch.setattr(clips, "start_relyric", lambda dd, sh: got.update(d=dd, sh=sh))
    r = c.post(f"/clips/{d.name}/lyrics-shift", data={"shift": "-0,25"}, headers=O, follow_redirects=False)
    assert r.status_code == 303 and got["sh"] == -0.25 and got["d"] == d


def test_find_start_uses_lrclib_passage(monkeypatch):
    from cstaktik import lrclib

    lines = [(10.0, "So you know what I mean"), (14.0, "Let me take you dancing"), (40.0, "Let me take you dancing")]
    monkeypatch.setattr(memeclip, "duration", lambda p: 180.0)
    monkeypatch.setattr(lrclib, "fetch", lambda q, dur=None: {"track": "Take You Dancing", "artist": "Jason Derulo",
                                                              "duration": 181.0, "lines": lines})
    t, song, why = clips.find_start("m.mp3", "Let me take you dancing", None)
    assert t == 14.0 - lrclib.LEAD_S and song == "Take You Dancing Jason Derulo" and "Stelle" in why
    monkeypatch.setattr(memeclip, "duration", lambda p: 30.0)  # nur ein Ausschnitt: Stelle nicht bestimmbar
    t, song, why = clips.find_start("m.mp3", "Let me take you dancing", "Derulo")
    assert t is None and song == "Derulo" and "nicht der ganze Song" in why


def test_drop_second_from_form(monkeypatch):
    calls = {}

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch", lyrics_shift=0.0,
                  drop_at=None, length="abschnitt"):
        calls.update(drop_at=drop_at)
        open(out, "wb").write(b"video")
        return {"kills": [1], "seconds": 9.5, "bpm": 120.0}

    monkeypatch.setattr(memeclip, "make_beat", fake_beat)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    c = _client()
    c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
           data={"music_ss": "30", "drop_at": "47,5"}, headers=O, follow_redirects=False)
    assert calls == {"drop_at": 47.5}
    for x in clips.jobs("Hausi"):
        c.post(f"/clips/{x['id']}/delete", headers=O)


def test_song_without_text_starts_before_deezer_hook(monkeypatch):
    from cstaktik import preview

    calls = {}

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch", lyrics_shift=0.0,
                  drop_at=None, length="abschnitt"):
        calls.update(music_ss=music_ss, drop_at=drop_at)
        open(out, "wb").write(b"video")
        return {"kills": [1], "seconds": 9.5, "bpm": 120.0}

    monkeypatch.setattr(memeclip, "make_beat", fake_beat)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    monkeypatch.setattr(preview, "best_part", lambda music, q, tmp: (40.0, "Hook laut Deezer-Hörprobe bei Sekunde 40.0"))
    c = _client()
    c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
           data={"music_ss": "", "song": "Kesha Cannibal"}, headers=O, follow_redirects=False)
    assert calls == {"music_ss": 40.0 - preview.INTRO_S, "drop_at": 40.0}
    assert "Hook laut Deezer" in c.get("/clips").text
    for x in clips.jobs("Hausi"):
        c.post(f"/clips/{x['id']}/delete", headers=O)


def test_lrclib_hook_without_deezer_starts_before_and_drops_on_hook(monkeypatch):
    from cstaktik import lrclib, preview

    calls = {}

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch", lyrics_shift=0.0,
                  drop_at=None, length="abschnitt"):
        calls.update(music_ss=music_ss, drop_at=drop_at)
        open(out, "wb").write(b"video")
        return {"kills": [1], "seconds": 9.5, "bpm": 120.0}

    monkeypatch.setattr(memeclip, "make_beat", fake_beat)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    monkeypatch.setattr(preview, "best_part", lambda music, q, tmp: (None, "keine Deezer-Hörprobe gefunden"))
    monkeypatch.setattr(clips, "find_start", lambda m, ly, so: (60.0 - lrclib.LEAD_S, "Cannibal Kesha",
                                                               "Cannibal: Hook (am häufigsten wiederholte Zeile)"))
    c = _client()
    c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
           data={"music_ss": "", "song": "Kesha Cannibal"}, headers=O, follow_redirects=False)
    assert calls == {"music_ss": 60.0 - preview.INTRO_S, "drop_at": 60.0}
    page = c.get("/clips").text
    assert "Deezer-Hörprobe: keine Deezer-Hörprobe gefunden" in page
    for x in clips.jobs("Hausi"):
        c.post(f"/clips/{x['id']}/delete", headers=O)


def test_length_choice_from_form(monkeypatch):
    calls = []

    def fake_beat(src, music, out, music_ss=0.0, words=None, progress=None, song=None, fmt="hoch", lyrics_shift=0.0,
                  drop_at=None, length="abschnitt"):
        calls.append(length)
        open(out, "wb").write(b"video")
        return {"kills": [1], "seconds": 9.5, "bpm": 120.0}

    monkeypatch.setattr(memeclip, "make_beat", fake_beat)
    monkeypatch.setattr(clips, "start", lambda d, user=None: clips.render(d, user))
    c = _client()
    for data in ({"music_ss": "30"}, {"music_ss": "30", "length": "kills"}, {"music_ss": "30", "length": "x"}):
        c.post("/clips", files={"video": ("a.mp4", b"x" * 10, "video/mp4"), "music": ("m.mp3", b"y", "audio/mpeg")},
               data=data, headers=O, follow_redirects=False)
    assert calls == ["abschnitt", "kills", "abschnitt"]  # Standard: Song-Abschnitt
    for x in clips.jobs("Hausi"):
        c.post(f"/clips/{x['id']}/delete", headers=O)
