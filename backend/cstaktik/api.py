"""FastAPI: Demo-Upload im Browser (PC), Report-Abruf im LAN (Handy)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cstaktik import pipeline

app = FastAPI(title="cstaktik")
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
    body = f"""<h1>cstaktik</h1>
<form class="card" action="/analyze" method="post" enctype="multipart/form-data">
<b>Demo hochladen (.dem oder .dem.bz2)</b>
<input type="file" name="demo" accept=".dem,.bz2" required>
<input type="text" name="steamids" placeholder="SteamID64, kommagetrennt (leer = players.yaml)">
<button type="submit">Analysieren</button>
<small>Parsen kann je nach Demo etwas dauern.</small></form>
<div class="card"><b>Reports</b><ul>{items}</ul></div>"""
    return _PAGE.format(body=body)


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
    try:
        target = pipeline.prepare_demo(target, remove_source=True)
        out = pipeline.run(target, focus)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Parser-Fehler verständlich melden
        raise HTTPException(422, f"Demo konnte nicht ausgewertet werden: {type(exc).__name__}: {exc}") from exc
    return RedirectResponse(f"/reports/{out.name}", status_code=303)
