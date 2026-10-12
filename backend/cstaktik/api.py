"""FastAPI: Demo-Upload im Browser (PC), Report-Abruf im LAN (Handy)."""

from __future__ import annotations

import html
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cstaktik import pipeline

app = FastAPI(title="cstaktik")
# Auswertung läuft im Hintergrund: Der Browser muss nach dem Upload nicht offen bleiben.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=pipeline.REPORTS_DIR, html=True), name="reports")

_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>cstaktik</title>
<style>body{{margin:0;background:#0f1216;color:#e8ecf1;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:560px;margin:0 auto;padding:16px}}a{{color:#4fc3f7}}
.card{{background:#1a1f26;border:1px solid #2a313b;border-radius:12px;padding:14px;margin:12px 0}}
input,button{{font:inherit;width:100%;margin:6px 0;padding:10px;border-radius:8px;border:1px solid #2a313b;
background:#0f1216;color:inherit}}button{{background:#4fc3f7;color:#000;font-weight:600}}
small{{color:#8b95a3}}</style></head><body><main>{body}</main></body></html>"""


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pipeline.demo_stem(Path(name).name)).strip("._") or "demo"
    return stem[:80]


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    reports = sorted(pipeline.REPORTS_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = "".join(
        f'<li><a href="/reports/{html.escape(p.name)}">{html.escape(p.stem)}</a></li>' for p in reports
    ) or "<li><small>Noch keine Reports.</small></li>"
    with _jobs_lock:
        running = [(jid, j) for jid, j in _jobs.items() if j["status"] in ("wartet", "läuft")]
    jobs_html = "".join(
        f'<li><a href="/jobs/{jid}">{html.escape(j["name"])}</a> <small>({j["status"]})</small></li>' for jid, j in running
    )
    jobs_card = f'<div class="card"><b>In Arbeit</b><ul>{jobs_html}</ul></div>' if running else ""
    body = f"""<h1>cstaktik</h1>{jobs_card}
<form class="card" action="/analyze" method="post" enctype="multipart/form-data">
<b>Demo hochladen (.dem oder .dem.bz2)</b>
<input type="file" name="demo" accept=".dem,.bz2" required>
<input type="text" name="steamids" placeholder="SteamID64, kommagetrennt (leer = players.yaml)">
<button type="submit">Analysieren</button>
<small>Nach dem Upload läuft die Auswertung auf dem Server weiter. Handy sperren ist dann ok.</small></form>
<div class="card"><b>Reports</b><ul>{items}</ul></div>"""
    return _PAGE.format(body=body)


def _run_job(job_id: str, target: Path, focus: set[str] | None) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft")
    try:
        demo = pipeline.prepare_demo(target, remove_source=True)
        out = pipeline.run(demo, focus)
        update(status="fertig", report=out.name)
    except ValueError as exc:
        update(status="fehler", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - Parser-Fehler verständlich melden
        update(status="fehler", error=f"Demo konnte nicht ausgewertet werden: {type(exc).__name__}: {exc}")


@app.post("/analyze")
async def analyze_upload(demo: UploadFile = File(...), steamids: str = Form("")) -> RedirectResponse:
    filename = demo.filename or ""
    if not pipeline.is_demo_name(filename):
        raise HTTPException(400, "Nur .dem- oder .dem.bz2-Dateien.")
    pipeline.DEMOS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".dem.bz2" if filename.lower().endswith(".bz2") else ".dem"
    target = pipeline.DEMOS_DIR / f"{_safe_name(filename)}{suffix}"
    with target.open("wb") as fh:
        while chunk := await demo.read(1 << 20):
            fh.write(chunk)
    focus = {s.strip() for s in steamids.split(",") if s.strip()} or None
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "wartet", "name": _safe_name(filename), "report": None, "error": None}
    _executor.submit(_run_job, job_id, target, focus)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status(job_id: str) -> str:
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        raise HTTPException(404, "Auftrag unbekannt (Server neu gestartet?). Reports stehen auf der Startseite.")
    name = html.escape(job["name"])
    if job["status"] == "fertig":
        url = f"/reports/{html.escape(job['report'])}"
        body = f"""<div class="card"><b>{name}</b><p>Fertig.</p><a href="{url}">Report öffnen</a></div>
<script>location.replace("{url}")</script>"""
    elif job["status"] == "fehler":
        body = f"""<div class="card"><b>{name}</b><p>Fehler: {html.escape(job["error"] or "")}</p>
<a href="/">Zurück</a></div>"""
    else:
        body = f"""<meta http-equiv="refresh" content="3"><div class="card"><b>{name}</b>
<p>Auswertung {job["status"]} … Seite aktualisiert sich selbst.</p>
<small>Du kannst das Handy sperren. Der Report erscheint danach auch auf der <a href="/">Startseite</a>.</small></div>"""
    return _PAGE.format(body=body)
