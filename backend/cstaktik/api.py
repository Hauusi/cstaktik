"""FastAPI: Demo-Upload, Auswertung im Hintergrund mit Fortschritt, Report-Abruf."""

from __future__ import annotations

import base64
import os
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cstaktik import pipeline

app = FastAPI(title="cstaktik")


@app.middleware("http")
async def _password(request: Request, call_next):
    """Optionaler Passwortschutz (HTTP Basic) für alle Seiten inkl. Reports.

    Aktiv, wenn die Umgebungsvariable CSTAKTIK_PASSWORD gesetzt ist (Benutzer: CSTAKTIK_USER, Standard "coach").
    """
    password = os.environ.get("CSTAKTIK_PASSWORD")
    if not password:
        return await call_next(request)
    user = os.environ.get("CSTAKTIK_USER", "coach")
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            got_user, _, got_pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            got_user, got_pw = "", ""
        if secrets.compare_digest(got_user.encode(), user.encode()) and secrets.compare_digest(
            got_pw.encode(), password.encode()
        ):
            return await call_next(request)
    return Response("Login erforderlich", status_code=401, headers={"WWW-Authenticate": 'Basic realm="cstaktik"'})

pipeline.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=pipeline.REPORTS_DIR, html=True), name="reports")
_env = Environment(loader=FileSystemLoader([Path(__file__).parent / "web", Path(__file__).parent / "report" / "templates"]),
                   autoescape=select_autoescape(["html"]))
_env.globals["font_css"] = lambda: __import__("cstaktik.fonts", fromlist=["font_css"]).font_css()

# Auswertung läuft im Hintergrund: Der Browser muss nach dem Upload nicht offen bleiben.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_SCORE = re.compile(r"^(.*?)\s+(\d+):(\d+)\s+–")


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pipeline.demo_stem(Path(name).name)).strip("._") or "demo"
    return stem[:80]


def _report_entries() -> list[dict]:
    """Reports für die Startseite; Map und Ergebnis kommen aus dem <title> des Reports."""
    out = []
    for p in sorted(pipeline.REPORTS_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.name == "fortschritt.html":  # CLI-Export der Fortschritts-Seite, kein Match
            continue
        with p.open(encoding="utf-8", errors="ignore") as fh:
            head = fh.read(4096)
        m = _TITLE.search(head)
        s = _SCORE.match(m.group(1).strip()) if m else None
        out.append(
            {
                "file": p.name,
                "name": p.stem,
                "map": s.group(1) if s else None,
                "won": int(s.group(2)) if s else None,
                "lost": int(s.group(3)) if s else None,
                "date": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            }
        )
    return out


def _job_view(job_id: str, job: dict) -> dict:
    return {
        "id": job_id,
        "name": job["name"],
        "status": job["status"],
        "stage": job["stage"],
        "frac": round(job["frac"], 3),
        "elapsed": round(time.monotonic() - job["started"], 1) if job["started"] else 0.0,
        "estimate": job["estimate"],
        "samples": job["samples"],
        "cached": job["cached"],
        "report": job["report"],
        "message": job.get("message"),
        "error": job["error"],
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with _jobs_lock:
        jobs = [_job_view(i, j) for i, j in _jobs.items() if j["status"] in ("wartet", "läuft")]
    from cstaktik import goals, history

    hist = history.load_all(pipeline.HISTORY_DIR) if pipeline.HISTORY_DIR.exists() else []
    state = goals.load(pipeline.GOALS_FILE)
    played = [h.get("map") for h in reversed(hist) if h.get("map")]
    maps = list(dict.fromkeys(played + ["de_mirage", "de_dust2", "de_inferno"]))
    return _env.get_template("index.html").render(
        jobs=jobs, reports=_report_entries(), n_history=len(hist), goals=state["active"],
        done_count=len(state["done"]), last=hist[-1] if hist else None, briefing_maps=maps,
        pro_overview=__import__("cstaktik.pro", fromlist=["stats"]).stats(pipeline.PRO_DIR),
        faceit_ready=bool(os.environ.get("FACEIT_API_KEY")),
        baustellen=_baustellen(hist),
        auftrag=_auftrag(hist),
    )


def _all_scenes(hist: list[dict]) -> list[dict]:
    """Trainings-Szenen aller Matches, neueste zuerst, jede Szene nur einmal."""
    seen: set = set()
    out = []
    for h in reversed(hist):
        for sc in h.get("scenes", []):
            key = (sc.get("report"), sc["round"], sc["tick"])
            if key not in seen:
                seen.add(key)
                out.append(sc)
    return out


def _players_state() -> dict:
    from cstaktik import coaching

    return coaching.load(pipeline.COACHING_FILE).get("players", {})


def _auftrag(hist: list[dict]) -> list[dict]:
    """Laufende Aufträge je Spieler für die Startseite: Lektion, Merksatz, Übung, Checks, erledigte Übungen."""
    from cstaktik import coaching
    from cstaktik.coach_voice import LESSONS
    from cstaktik.curriculum import TEACH

    names = {sid: p["name"] for h in hist for sid, p in h.get("players", {}).items()}
    scenes = _all_scenes(hist)
    out = []
    for sid, slot in sorted(_players_state().items(), key=lambda kv: names.get(kv[0], kv[0])):
        f = slot.get("focus")
        if not f:
            continue
        t = TEACH[f["lesson"]]
        out.append({"sid": sid, "name": names.get(sid, sid), "lesson": f["lesson"], "title": LESSONS[f["lesson"]][0],
                    "target": f["target"], "baseline": f["baseline"], "matches": f.get("matches", []),
                    "mantra": t["mantra"], "routine": t["routine"], "in_game": t["in_game"],
                    "drills": coaching.drills_since(slot, f.get("created_at")),
                    "scenes": sum(1 for sc in scenes if sc["lesson"] == f["lesson"] and sc.get("sid") in (sid, None)),
                    "mastered": len(slot.get("done", []))})
    return out


@app.post("/training/done")
def training_done(p: str = "") -> RedirectResponse:
    from cstaktik import coaching

    state = coaching.load(pipeline.COACHING_FILE)
    slot = state.get("players", {}).get(p)
    if slot and slot.get("focus"):
        coaching.drill_done(slot, slot["focus"]["lesson"])
        coaching.save(state, pipeline.COACHING_FILE)
    return RedirectResponse("/", status_code=303)


@app.get("/training", response_class=HTMLResponse)
def training_page(p: str = "") -> str:
    """Entscheidungs-Training mit eigenen Situationen aus allen Matches, zuerst zum laufenden Auftrag."""
    import json as _json

    from cstaktik import coaching, history
    from cstaktik.coach_voice import LESSONS

    hist = history.load_all(pipeline.HISTORY_DIR) if pipeline.HISTORY_DIR.exists() else []
    players = _players_state()
    sid = p if p in players else next((s for s, v in players.items() if v.get("focus")), None)
    f = (players.get(sid) or {}).get("focus")
    scenes = [sc for sc in _all_scenes(hist) if sid is None or sc.get("sid") in (sid, None)]
    lesson = f["lesson"] if f else None
    pick = [sc for sc in scenes if sc["lesson"] == lesson] if lesson else []
    if len(pick) < 6:  # auffüllen mit den teuersten anderen Szenen
        rest = sorted((sc for sc in scenes if sc not in pick), key=lambda sc: -(sc.get("cost") or 0))
        pick += rest[: 12 - len(pick)]
    pick = pick[:12]
    data = _json.dumps([{**sc, "lesson_title": LESSONS.get(sc["lesson"], ("?",))[0]} for sc in pick],
                       ensure_ascii=False).replace("</", "<\\/")
    names = {s: pp["name"] for h in hist for s, pp in h.get("players", {}).items()}
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s, v in players.items() if v.get("focus")]
    return _env.get_template("training.html").render(title=LESSONS[lesson][0] if lesson else None, n=len(pick),
                                                     data_json=data, tabs=tabs, who=names.get(sid))


def _baustellen(hist: list[dict]) -> list[dict]:
    """Je Fokus-Spieler die größte Coach-Lektion im Verlauf, mit Trend und schlechtester Map."""
    from cstaktik.report.progress import _lessons

    out = []
    names = {}
    for h in hist:
        for sid, p in h.get("players", {}).items():
            names[sid] = p["name"]
    for sid, name in names.items():
        ls = _lessons(hist, sid)
        if not ls:
            continue
        top = ls[0]
        have = [r for r in top["rates"] if r is not None]
        worst = max(top["by_map"].items(), key=lambda kv: kv[1]["rate"], default=(None, None))[0]
        out.append({"name": name, "title": top["title"], "state": top["trend"]["state"],
                    "now": str(round(have[-1], 1)).replace(".", ",") if have else "0",
                    "worst_map": worst.removeprefix("de_").capitalize() if worst and len(top["by_map"]) > 1 else None})
    return out


@app.get("/briefing/{map_name}", response_class=HTMLResponse)
def briefing_page(map_name: str) -> str:
    from cstaktik import briefing, goals, history

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    hist = history.load_all(pipeline.HISTORY_DIR) if pipeline.HISTORY_DIR.exists() else []
    from cstaktik import pro

    b = briefing.build(map_name, hist, goals.load(pipeline.GOALS_FILE), pro=pro.load_all(pipeline.PRO_DIR))
    return _env.get_template("briefing.html").render(b=b, map_lessons=_map_lessons(hist, map_name),
                                                     kabine=_kabine(hist, map_name))


def _kabine(hist: list[dict], map_name: str) -> dict | None:
    """Kabine vor dem Match: Auftrag je Spieler und wo auf dieser Map der Auftrags-Fehler passiert ist."""
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    auftr = _auftrag(hist)
    if not auftr:
        return None
    colors = ["#ff9f1c", "#6f9be8"]
    scenes = [sc for sc in _all_scenes(hist) if sc.get("map") == map_name and sc.get("pos")]
    radar = build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))
    img = radar.image_data_uri
    players = []
    pts_all = []
    for i, a in enumerate(auftr):
        mine = [sc for sc in scenes if sc["lesson"] == a["lesson"] and sc.get("sid") in (a["sid"], None)]
        pts = []
        for sc in mine:
            x, y = sc["pos"]
            pts.append({"x": x, "y": y, "round": sc["round"], "report": sc.get("report"), "tick": sc.get("from") or sc["tick"]})
        pts_all += pts
        players.append({**a, "color": colors[i % len(colors)], "points": pts})
    if img:
        for pl in players:
            for q in pl["points"]:
                q["px"], q["py"] = radar.to_px(q["x"], q["y"])
    elif pts_all:  # ohne Radarbild: Punkte in ihrem eigenen Rahmen
        xs, ys = [q["x"] for q in pts_all], [q["y"] for q in pts_all]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 500) * 1.3
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        for pl in players:
            for q in pl["points"]:
                q["px"], q["py"] = 512 + (q["x"] - cx) / span * 1024, 512 - (q["y"] - cy) / span * 1024
    return {"img": img, "players": players, "has_points": bool(pts_all)}


def _map_lessons(hist: list[dict], map_name: str) -> list[dict]:
    """Je Spieler die zwei häufigsten Coach-Lektionen auf dieser Map (aus dem Verlauf)."""
    from cstaktik.report.progress import _lessons

    names = {sid: p["name"] for h in hist for sid, p in h.get("players", {}).items()}
    out = []
    for sid, name in names.items():
        ls = [l for l in _lessons(hist, sid) if (l["by_map"].get(map_name) or {}).get("count")]
        ls.sort(key=lambda l: -l["by_map"][map_name]["rate"])
        out += [{"name": name, "title": l["title"], "drill": l["drill"],
                 "rate": str(l["by_map"][map_name]["rate"]).replace(".", ",")} for l in ls[:2]]
    return out


def _run_job(job_id: str, target: Path, focus: set[str] | None, is_pro: bool = False) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft", stage="Demo vorbereiten", started=time.monotonic())
    try:
        demo = pipeline.prepare_demo(target, remove_source=True)
        cached = pipeline.is_cached(demo)
        estimate = None if cached else pipeline.estimate_seconds(demo.stat().st_size)
        update(cached=cached, estimate=round(estimate, 1) if estimate else None, samples=pipeline.timing_samples())
        if is_pro:
            info = pipeline.run_pro(demo, progress=lambda stage, frac: update(stage=stage, frac=frac))
            label = (info["map"] or "?").removeprefix("de_").capitalize()
            update(status="fertig", stage="Fertig", frac=1.0,
                   message=f"Pro-Demo gespeichert: {label}, {info['rounds']} Runden, {info['nades']} Granaten. "
                           f"{info['reports']} eigene {label}-Reports mit den neuen Pro-Daten aktualisiert.")
        else:
            out = pipeline.run(demo, focus, progress=lambda stage, frac: update(stage=stage, frac=frac))
            update(status="fertig", stage="Fertig", frac=1.0, report=out.name)
    except ValueError as exc:
        update(status="fehler", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - Parser-Fehler verständlich melden
        update(status="fehler", error=f"Demo konnte nicht ausgewertet werden: {type(exc).__name__}: {exc}")


@app.post("/analyze")
async def analyze_upload(
    demo: UploadFile = File(...), steamids: str = Form(""), pro: str = Form("")
) -> RedirectResponse:
    filename = demo.filename or ""
    if not pipeline.is_demo_name(filename):
        raise HTTPException(400, "Nur .dem- oder .dem.bz2-Dateien.")
    # Pro-Demos getrennt ablegen, damit sie nie als eigenes Match ausgewertet werden
    folder = pipeline.PRO_DEMOS_DIR if pro else pipeline.DEMOS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    suffix = ".dem.bz2" if filename.lower().endswith(".bz2") else ".dem"
    target = folder / f"{_safe_name(filename)}{suffix}"
    with target.open("wb") as fh:
        while chunk := await demo.read(1 << 20):
            fh.write(chunk)
    focus = {s.strip() for s in steamids.split(",") if s.strip()} or None
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "wartet",
            "name": _safe_name(filename),
            "stage": "Wartet",
            "frac": 0.0,
            "started": None,
            "estimate": None,
            "samples": 0,
            "cached": False,
            "report": None,
            "error": None,
        }
    _executor.submit(_run_job, job_id, target, focus, bool(pro))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _get_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Auftrag unbekannt (Server neu gestartet?). Reports stehen auf der Startseite.")
        return _job_view(job_id, job)


@app.get("/review", response_class=HTMLResponse)
def review_page(n: int = 5) -> str:
    from cstaktik import history, review

    hist = history.load_all(pipeline.HISTORY_DIR) if pipeline.HISTORY_DIR.exists() else []
    return _env.get_template("review.html").render(r=review.build(hist, max(1, min(n, 20))))


@app.get("/progress", response_class=HTMLResponse)
def progress() -> str:
    from cstaktik import history
    from cstaktik.report.progress import render_progress

    return render_progress(history.load_all(pipeline.HISTORY_DIR))


def _run_faceit_job(job_id: str) -> None:
    from cstaktik import faceit

    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        done = sum(1 for x in lines if x.startswith("ok"))
        update(stage=f"{done} Demos geladen" + (f" · zuletzt: {msg}" if msg else ""), frac=min(0.95, 0.05 + 0.08 * len(lines)))

    update(status="läuft", stage="FACEIT abfragen", started=time.monotonic())
    try:
        res = pipeline.faceit_sync(log=log)
        added = ", ".join(f"{m.removeprefix('de_').capitalize()} +{n}" for m, n in res["added"].items())
        update(status="fertig", stage="Fertig", frac=1.0, message=f"Pro-Demos geholt: {added}.")
    except faceit.FaceitError as exc:
        update(status="fehler", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        update(status="fehler", error=f"FACEIT-Sync fehlgeschlagen: {type(exc).__name__}: {exc}")


@app.post("/pro/sync")
def pro_sync() -> RedirectResponse:
    if not os.environ.get("FACEIT_API_KEY"):
        raise HTTPException(400, "FACEIT_API_KEY ist auf dem Server nicht gesetzt.")
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "wartet", "name": "Pro-Demos von FACEIT", "stage": "Wartet", "frac": 0.0,
                         "started": None, "estimate": None, "samples": 0, "cached": False, "report": None,
                         "error": None}
    _executor.submit(_run_faceit_job, job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/api/jobs/{job_id}")
def job_json(job_id: str) -> dict:
    return _get_job(job_id)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str) -> str:
    job = _get_job(job_id)
    return _env.get_template("job.html").render(job_id=job_id, name=job["name"])
