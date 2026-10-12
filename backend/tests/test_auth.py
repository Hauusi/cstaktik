from fastapi.testclient import TestClient


def test_no_password_means_open(monkeypatch):
    from cstaktik import api

    monkeypatch.delenv("CSTAKTIK_PASSWORD", raising=False)
    assert TestClient(api.app).get("/").status_code == 200


def test_password_protects_everything(monkeypatch):
    from cstaktik import api

    monkeypatch.setenv("CSTAKTIK_PASSWORD", "geheim")
    c = TestClient(api.app)
    r = c.get("/")
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert c.get("/reports/x.html").status_code == 401
    assert c.post("/analyze").status_code == 401
    assert c.get("/", auth=("coach", "falsch")).status_code == 401
    assert c.get("/", auth=("coach", "geheim")).status_code == 200
    monkeypatch.setenv("CSTAKTIK_USER", "bro")
    assert c.get("/", auth=("bro", "geheim")).status_code == 200
