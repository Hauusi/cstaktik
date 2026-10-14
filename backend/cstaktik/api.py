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
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cstaktik import pipeline
from cstaktik.config import load_rules_config

app = FastAPI(title="cstaktik")


@app.middleware("http")
async def _password(request: Request, call_next):
    """Optionaler Passwortschutz (HTTP Basic) für alle Seiten inkl. Reports.

    Aktiv, wenn die Umgebungsvariable CSTAKTIK_PASSWORD gesetzt ist (Benutzer: CSTAKTIK_USER, Standard "coach").
    """
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        # eigene Adresse: Host, hinter einem Proxy auch X-Forwarded-Host, zusätzlich CSTAKTIK_ALLOWED_HOSTS
        hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", "")}
        hosts |= {h.strip() for h in os.environ.get("CSTAKTIK_ALLOWED_HOSTS", "").split(",") if h.strip()}
        if origin and urlparse(origin).netloc not in hosts - {""}:  # "null" (Sandbox) gilt als fremd
            return Response("Fremde Herkunft", status_code=403)
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


class _GoalCfg:
    """Auftrags-Schwellen aus rules.yaml für die Texte (immer aktuell, keine festen Zahlen im Template)."""

    def __getattr__(self, name: str):
        return load_rules_config()["goals"].get(name, {"min_count": 3, "min_master_rounds": 40}.get(name))


_env.globals["goal_cfg"] = _GoalCfg()

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
    jobs = _running_jobs()

    hist = _load_hist()
    played = [h.get("map") for h in reversed(hist) if h.get("map")]
    maps = list(dict.fromkeys(played + ["de_mirage", "de_dust2", "de_inferno"]))
    from cstaktik.config import load_focus_steamids

    # eingestellter Spieler, der im letzten Match nicht vorkommt: der Coach sieht ihn nicht -> Hinweis
    missing = len(load_focus_steamids() - set((hist[-1].get("players") or {}) if hist else ()))
    return _env.get_template("index.html").render(
        nav_active="coach", jobs=jobs, n_history=len(hist), last=hist[-1] if hist else None, briefing_maps=maps,
        auftrag=_auftrag(hist), missing_players=missing if hist else 0,
    )


def _running_jobs() -> list[dict]:
    with _jobs_lock:
        return [_job_view(i, j) for i, j in _jobs.items() if j["status"] in ("wartet", "läuft")]


@app.get("/matches", response_class=HTMLResponse)
def matches_page() -> str:

    hist = _load_hist()
    return _env.get_template("matches.html").render(nav_active="matches", jobs=_running_jobs(),
                                                    reports=_report_entries(), n_history=len(hist))


@app.get("/pro", response_class=HTMLResponse)
def pro_page() -> str:
    from cstaktik import pro

    return _env.get_template("pro.html").render(nav_active="pro", jobs=_running_jobs(),
                                                pro_overview=pro.stats(pipeline.PRO_DIR),
                                                faceit_ready=bool(os.environ.get("FACEIT_API_KEY")))


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


def _default_sid(players: dict, names: dict, want: str = "") -> str | None:
    """Gewählter Spieler, sonst der erste mit Auftrag (nach Name sortiert), überall gleich."""
    if want in players:
        return want
    return next((s for s in sorted(players, key=lambda s: names.get(s, s)) if players[s].get("focus")), None)


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
        if not f or f["lesson"] not in LESSONS or f["lesson"] not in TEACH:
            continue  # Lektion gibt es nicht mehr (alte coaching.json)
        t = TEACH[f["lesson"]]
        out.append({"sid": sid, "name": names.get(sid, sid), "lesson": f["lesson"], "title": LESSONS[f["lesson"]][0],
                    "target": f["target"], "baseline": f["baseline"], "matches": f.get("matches", []),
                    "baseline_n": f.get("baseline_n"), "baseline_rounds": f.get("baseline_rounds"),
                    "rueckfall": f.get("rueckfall"),
                    "mantra": t["mantra"], "routine": t["routine"], "in_game": t["in_game"],
                    "drills": coaching.drills_since(slot, f.get("created_at")),
                    "scenes": min(12, sum(1 for sc in scenes if sc["lesson"] == f["lesson"] and sc.get("sid") == sid)),
                    "mastered": len(slot.get("done", []))})
    return out


@app.post("/training/done")
def training_done(p: str = "") -> RedirectResponse:
    from cstaktik import coaching, weekplan

    state = coaching.load(pipeline.COACHING_FILE)
    slot = state.get("players", {}).get(p)
    if slot and slot.get("focus"):
        coaching.drill_done(slot, slot["focus"]["lesson"])
        # dieselbe Übung im Wochenplan abhaken, damit sie nicht doppelt gezählt wird
        key = weekplan.week_key(weekplan.local_today())
        plan = slot.get("weeks", {}).get(key)
        if plan:
            open_ = next((t["id"] for t in plan["tasks"] if t["id"].startswith("routine") and t["id"] not in plan["done"]),
                         None)
            if open_:
                weekplan.toggle(slot, key, open_)
        coaching.save(state, pipeline.COACHING_FILE)
    return RedirectResponse("/", status_code=303)


def _scene_maps(scenes: list[dict]) -> dict[str, str]:
    """Lagebilder der Szenen auf das Radarbild der Map umrechnen (Pixel, Ausschnitt). Rückgabe: Map -> Bild."""
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    radars, imgs = {}, {}
    for sc in scenes:
        fr, m = sc.get("frame"), sc.get("map")
        if not fr or not m:
            continue
        if m not in radars:
            radars[m] = build_radar(MatchData(map_name=m, tickrate=64, tickrate_source="-", players=[], rounds=[]))
            if radars[m].image_data_uri:
                imgs[m] = radars[m].image_data_uri
        r = radars[m]
        if m not in imgs:
            continue
        px = lambda p: [round(v, 1) for v in r.to_px(p[0], p[1])]  # noqa: E731
        view = {"me": px(fr["me"]), "mates": [px(q) + [q[2]] for q in fr.get("mates", [])],
                "foes": [px(q) for q in fr.get("foes", [])], "spotted": fr.get("spotted")}
        if fr.get("killer"):
            view["killer"], view["dead"], view["kplace"] = px(fr["killer"]), px(fr["dead"]), fr.get("kplace")
        # Ausschnitt: du, Killer, sichtbare Gegner und der nächste Mitspieler (weit entfernte sind am Rand/außerhalb)
        near = sorted(view["mates"], key=lambda q: (q[0] - view["me"][0]) ** 2 + (q[1] - view["me"][1]) ** 2)[:1]
        pts = [view["me"]] + [q[:2] for q in near] + view["foes"] + ([view["killer"]] if "killer" in view else [])
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        size = min(1024, max(max(max(xs) - min(xs), max(ys) - min(ys)) + 240, 420))
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        view["vb"] = [round(min(max(cx - size / 2, 0), 1024 - size)), round(min(max(cy - size / 2, 0), 1024 - size)),
                      round(size)]
        sc["view"] = view
    return imgs


@app.get("/training/situationen", response_class=HTMLResponse)
def quiz_page(p: str = "") -> str:
    """Entscheidungs-Training mit eigenen Situationen aus allen Matches, zuerst zum laufenden Auftrag."""
    import json as _json

    from cstaktik.coach_voice import LESSONS

    hist = _load_hist()
    players = _players_state()
    names = _names(hist)
    sid = _default_sid(players, names, p)
    f = (players.get(sid) or {}).get("focus")
    scenes = [sc for sc in _all_scenes(hist) if sid is None or sc.get("sid") == sid]
    lesson = f["lesson"] if f else None
    pick = [sc for sc in scenes if sc["lesson"] == lesson] if lesson else []
    if len(pick) < 6:  # auffüllen mit den teuersten anderen Szenen
        rest = sorted((sc for sc in scenes if sc not in pick), key=lambda sc: -(sc.get("cost") or 0))
        pick += rest[: 12 - len(pick)]
    pick = [dict(sc) for sc in pick[:40]]  # Kopien: der Verlauf ist gecacht und wird nicht verändert
    radars = _scene_maps(pick)  # die Seite wählt daraus 12 (falsch beantwortete und neue zuerst)
    data = _json.dumps([{**sc, "lesson_title": LESSONS.get(sc["lesson"], ("?",))[0]} for sc in pick],
                       ensure_ascii=False).replace("</", "<\\/")
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s, v in players.items() if v.get("focus")]
    from cstaktik import coaching, weekplan

    week = weekplan.week_key(weekplan.local_today())
    plan = ((coaching.load(pipeline.COACHING_FILE).get("players", {}).get(sid) or {}).get("weeks") or {}).get(week)
    quiz_open = bool(plan) and any(t["id"] == "quiz" for t in plan["tasks"]) and "quiz" not in plan["done"]
    return _env.get_template("quiz.html").render(nav_active="training", title=LESSONS.get(lesson, ("?",))[0] if lesson else None,
                                                 n=min(12, len(pick)), data_json=data, tabs=tabs, who=names.get(sid),
                                                 sid=sid, week=week, quiz_open=quiz_open, radars=radars)


_CACHE: dict[str, tuple] = {}


def _dir_cached(name: str, folder: Path, loader) -> list[dict]:
    """Ordner-Inhalt nur neu laden, wenn sich Dateien geändert haben (Name, Größe, Änderungszeit).
    Die Seiten lesen die Daten nur; wer sie ändert, speichert sie und macht den Cache so ungültig."""
    if not folder.exists():
        return []
    key = (str(folder), tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in folder.glob("*.json"))))
    hit = _CACHE.get(name)
    if hit is None or hit[0] != key:
        hit = (key, loader(folder))
        _CACHE[name] = hit
    return hit[1]


def _load_hist() -> list[dict]:
    from cstaktik import history

    return _dir_cached("hist", pipeline.HISTORY_DIR, history.load_all)


def _load_pro() -> list[dict]:
    from cstaktik import pro

    return _dir_cached("pro", pipeline.PRO_DIR, pro.load_all)


def _names(hist: list[dict]) -> dict[str, str]:
    return {s: pp["name"] for h in hist for s, pp in h.get("players", {}).items()}


def _player_maps(hist: list[dict], sid: str | None) -> list[str]:
    """Maps des Spielers, zuletzt gespielte zuerst."""
    played = [h.get("map") for h in reversed(hist) if h.get("map") and (sid is None or sid in h.get("players", {}))]
    return list(dict.fromkeys(played))


def _plan_ctx(hist: list[dict], pro_all: list[dict], sid: str, focus: dict) -> dict:
    from cstaktik import lineups, mapbook
    from cstaktik.curriculum import TEACH

    cfg = load_rules_config()["mapbook"]
    maps = _player_maps(hist, sid)
    m = maps[0] if maps else None
    spot = lineup = None
    if m:
        book = mapbook.build(hist, pro_all, m, sid, cfg)
        spot = mapbook.worst_spot(book)
        cands = (spot or {}).get("lineups") or []
        if not cands:
            side = (spot or {}).get("side")
            allx = lineups.build(pro_all, m)
            cands = [l for l in allx if side is None or l["side"] == side] or allx
        # passend zum Auftrag: Utility-Auftrag -> Flash, lange Linien -> Smoke
        want = {"utility": "flash", "no_shot_far": "smoke", "no_shot_close": "flash"}.get(focus["lesson"])
        cands = sorted(cands, key=lambda l: l["kind"] != want) if want else cands
        lineup = cands[0] if cands else None
    scenes = sum(1 for sc in _all_scenes(hist) if sc.get("sid") == sid)
    t = TEACH[focus["lesson"]]
    return {"sid": sid, "lesson": focus["lesson"], "routine": t["routine"], "map": m,
            "map_label": m.removeprefix("de_").capitalize() if m else None, "spot": spot, "lineup": lineup,
            "scenes": scenes}


@app.get("/training", response_class=HTMLResponse)
def training_page(p: str = "") -> str:
    """Trainings-Zentrale: Wochenplan je Spieler, Map-Buch, Lineups, Situationen."""
    from cstaktik import coaching, weekplan
    from cstaktik.coach_voice import LESSONS

    hist = _load_hist()
    names = _names(hist)
    state = coaching.load(pipeline.COACHING_FILE)
    players = state.get("players", {})
    sid = _default_sid(players, names, p)
    slot = players.get(sid) or {}
    focus = slot.get("focus")
    plan = chk = key = None
    past = []
    if sid and focus:
        key, plan, changed = weekplan.ensure(slot, _plan_ctx(hist, _load_pro(), sid, focus))
        if changed:
            coaching.save(state, pipeline.COACHING_FILE)
        chk = weekplan.check(key, plan, hist, sid, focus,
                             min_rounds=load_rules_config()["goals"].get("min_master_rounds", 40))
        for k in sorted(slot.get("weeks", {}), reverse=True):
            if k != key:
                past.append(weekplan.check(k, slot["weeks"][k], hist, sid, None)
                            | {"title": LESSONS.get(slot["weeks"][k]["lesson"], ("?",))[0]})
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s, v in players.items() if v.get("focus")]
    return _env.get_template("training.html").render(
        nav_active="training", tabs=tabs, sid=sid, who=names.get(sid), plan=plan, week=key, chk=chk, past=past[:4],
        title=LESSONS.get(focus["lesson"], ("?",))[0] if focus else None, maps=_player_maps(hist, sid) or ["de_mirage"],
        pro_maps=sorted({d.get("map") for d in _load_pro() if d.get("map")}))


@app.post("/training/plan")
def plan_toggle(p: str = "", task: str = "", week: str = "") -> RedirectResponse:
    from cstaktik import coaching, weekplan

    state = coaching.load(pipeline.COACHING_FILE)
    slot = state.get("players", {}).get(p)
    if slot:
        now = weekplan.toggle(slot, week, task)
        if task.startswith("routine") and slot.get("focus") and now is not None:
            if now:
                coaching.drill_done(slot, slot["focus"]["lesson"])
            else:
                coaching.drill_undo(slot, slot["focus"]["lesson"])
        if now is not None:
            coaching.save(state, pipeline.COACHING_FILE)
    return RedirectResponse(f"/training?p={p}#plan", status_code=303)


@app.get("/mapbook/{map_name}", response_class=HTMLResponse)
def mapbook_page(map_name: str, p: str = "") -> str:
    from cstaktik import mapbook

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    hist = _load_hist()
    names = _names(hist)
    focus_ids = sorted({s for h in hist if h.get("map") == map_name for t in h.get("timeline", []) for s in [t["sid"]]},
                       key=lambda s: names.get(s, s))
    pref = _default_sid(_players_state(), names, p)
    sid = p if p in focus_ids else pref if pref in focus_ids else (focus_ids[0] if focus_ids else None)
    book = mapbook.build(hist, _load_pro(), map_name, sid, load_rules_config()["mapbook"]) \
        if sid else None
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in focus_ids]
    img = None
    if book:  # Schusslinien aufs Radarbild umrechnen
        from cstaktik.model import MatchData
        from cstaktik.report.radar import build_radar

        radar = build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))
        img = radar.image_data_uri
        if img:
            for sd in book["sides"].values():
                sd["px"] = [[*radar.to_px(l[0], l[1]), *radar.to_px(l[2], l[3]), l[4] if len(l) > 4 else None]
                            for l in sd["lines"]]
                if sd["px"]:  # auf den Bereich der Linien zoomen (am Handy sonst zu klein)
                    xs = [v for l in sd["px"] for v in (l[0], l[2])]
                    ys = [v for l in sd["px"] for v in (l[1], l[3])]
                    size = max(max(xs) - min(xs), max(ys) - min(ys)) + 220
                    size = min(1024, max(size, 380))
                    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
                    x0 = min(max(cx - size / 2, 0), 1024 - size)
                    y0 = min(max(cy - size / 2, 0), 1024 - size)
                    sd["vb"] = f"{x0:.0f} {y0:.0f} {size:.0f} {size:.0f}"
                    sd["sw"] = round(size / 340, 2)
    return _env.get_template("mapbook.html").render(img=img,nav_active="training", book=book, cfg=load_rules_config()["mapbook"], tabs=tabs, sid=sid,
                                                    who=names.get(sid), map_name=map_name,
                                                    label=map_name.removeprefix("de_").capitalize())


@app.get("/playbook", response_class=HTMLResponse)
def playbook_index() -> RedirectResponse:
    maps = sorted({d.get("map") for d in _load_pro() if d.get("map")})
    return RedirectResponse(f"/playbook/{maps[0] if maps else 'de_mirage'}", status_code=303)


@app.get("/playbook/{map_name}", response_class=HTMLResponse)
def playbook_page(map_name: str) -> str:
    """T-Taktiken aus den Pro-Demos dieser Map: Laufwege, Granaten, Plant, abspielbar auf dem Radar."""
    import json as _json

    from cstaktik import playbook
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    pro = _load_pro()
    book = playbook.build(pro, map_name, load_rules_config().get("playbook"))
    radar = build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))
    img = radar.image_data_uri
    for tac in book["tactics"]:
        ex = tac["example"]
        if not img:
            continue
        px = lambda x, y: [round(v, 1) for v in radar.to_px(x, y)]  # noqa: E731
        paths = [[px(*q) for q in pts] for pts in ex["paths"].values()]
        nades = [{"kind": n["kind"], "t": n["t"], "to": n.get("to"), "a": px(*(n["p"][:2] if n.get("p") else (n["fx"], n["fy"]))),
                  "b": px(n["tx"], n["ty"])} for n in ex["nades"]]
        plant = px(*ex["plant"]) if ex.get("plant") else None
        pts = [q for p in paths for q in p] + [q for n in nades for q in (n["a"], n["b"])] + ([plant] if plant else [])
        if not pts:
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        size = min(1024, max(max(xs) - min(xs), max(ys) - min(ys)) + 120)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        x0, y0 = min(max(cx - size / 2, 0), 1024 - size), min(max(cy - size / 2, 0), 1024 - size)
        sids = list(ex["paths"])
        evs = playbook.events(ex)
        for ev in evs:  # T-Tod: Punkt am Ende seines Laufwegs (Laufwege enden mit dem Tod)
            for it in ev["items"]:
                if it["kind"] == "death" and it.get("sid") in sids:
                    it["p"] = paths[sids.index(it["sid"])][-1]
        tac["draw"] = {"paths": paths, "nades": nades, "plant": plant, "step": playbook.PATH_STEP_S, "events": evs,
                       "plant_t": ex.get("plant_t"), "vb": [round(x0), round(y0), round(size)], "sw": round(size / 400, 2)}
    maps = sorted({d.get("map") for d in pro if d.get("map")} | {map_name})
    data = _json.dumps({t["id"]: t.get("draw") for t in book["tactics"]}, ensure_ascii=False).replace("</", "<\\/")
    return _env.get_template("playbook.html").render(nav_active="training", book=book, img=img, maps=maps,
                                                     map_name=map_name, data=data,
                                                     label=map_name.removeprefix("de_").capitalize())


@app.get("/lineups/{map_name}", response_class=HTMLResponse)
def lineups_page(map_name: str, side: str = "", kind: str = "", l: str = "", p: str = "") -> str:
    import json as _json

    from cstaktik import lineups
    from cstaktik.model import MatchData
    from cstaktik.report.radar import build_radar

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    allx = lineups.build(_load_pro(), map_name)
    if l and not any(x["id"] == l for x in allx):
        l = ""
    sel = [x for x in allx if (not side or x["side"] == side) and (not kind or x["kind"] == kind)]
    if l:  # gewähltes Lineup zuerst
        sel.sort(key=lambda x: x["id"] != l)
    radar = build_radar(MatchData(map_name=map_name, tickrate=64, tickrate_source="-", players=[], rounds=[]))
    for x in sel:
        if radar.image_data_uri:
            x["px"], x["py"] = radar.to_px(x["x"], x["y"])
            x["tpx"], x["tpy"] = radar.to_px(x["tx"], x["ty"])
            lo_x, hi_x = min(x["px"], x["tpx"]), max(x["px"], x["tpx"])
            lo_y, hi_y = min(x["py"], x["tpy"]), max(x["py"], x["tpy"])
            size = max(hi_x - lo_x, hi_y - lo_y) + 160
            size = max(size, 320)
            cx, cy = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
            x["vb"] = f"{cx - size / 2:.0f} {cy - size / 2:.0f} {size:.0f} {size:.0f}"
            x["sw"] = round(size / 300, 2)  # Strichstärke passend zum Ausschnitt
    data = _json.dumps(sel, ensure_ascii=False).replace("</", "<\\/")
    return _env.get_template("lineups.html").render(
        nav_active="training", items=sel, data_json=data, img=radar.image_data_uri, map_name=map_name,
        label=map_name.removeprefix("de_").capitalize(), side=side, kind=kind, sel=l, total=len(allx),
        kinds=lineups.KIND_DE, sid=re.sub(r"[^0-9]", "", p), n_demos=sum(1 for d in _load_pro() if d.get("map") == map_name))


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
    from cstaktik import briefing, goals

    if not re.fullmatch(r"[a-z0-9_]+", map_name):
        raise HTTPException(400, "Ungültiger Mapname.")
    hist = _load_hist()

    b = briefing.build(map_name, hist, goals.load(pipeline.GOALS_FILE), pro=_load_pro())
    return _env.get_template("briefing.html").render(nav_active="coach", b=b, map_lessons=_map_lessons(hist, map_name),
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
        mine = [sc for sc in scenes if sc["lesson"] == a["lesson"] and sc.get("sid") == a["sid"]]
        pts = []
        for sc in mine:
            x, y = sc["pos"]
            pts.append({"x": x, "y": y, "round": sc["round"], "report": sc.get("report"), "tick": sc.get("from") or sc["tick"],
                        "place": (sc.get("snap") or {}).get("place")})
        pts_all += pts
        from collections import Counter

        top = Counter(q["place"] for q in pts if q["place"]).most_common(1)
        from cstaktik import mapbook

        ang = {side: mapbook.angles(hist, map_name, a["sid"], side) for side in ("ct", "t")}
        angles = {side: g["killer_top"][:1] for side, g in ang.items()}
        seen_at = {s.upper(): g["seen"]["places"][0] for s, g in ang.items() if g["seen"] and g["seen"]["places"]}
        players.append({**a, "color": colors[i % len(colors)], "points": pts,
                        "top_place": top[0] if top and top[0][1] >= 2 else None,
                        "angles": {s.upper(): v[0] for s, v in angles.items() if v}, "seen_at": seen_at})
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
    focus_titles = {a["title"] for a in _auftrag(hist)}
    for sid, name in names.items():
        # erst ab 3 Vorkommen und 30 Runden auf der Map: ein einzelner Tod ist keine Baustelle
        ls = [l for l in _lessons(hist, sid) if (l["by_map"].get(map_name) or {}).get("count", 0) >= 3
              and l["by_map"][map_name]["rounds"] >= 30]
        ls = [l for l in ls if l["title"] not in focus_titles]  # Auftrag steht schon oben in der Kabine
        ls.sort(key=lambda l: -l["by_map"][map_name]["rate"])
        out += [{"name": name, "title": l["title"], "drill": l["drill"],
                 "rate": str(l["by_map"][map_name]["rate"]).replace(".", ","),
                 "count": l["by_map"][map_name]["count"], "rounds": l["by_map"][map_name]["rounds"]} for l in ls[:2]]
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
    part = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    size = 0
    try:
        with part.open("wb") as fh:
            while chunk := await demo.read(1 << 20):
                size += len(chunk)
                if size > pipeline.MAX_DEMO_BYTES:
                    raise HTTPException(413, "Datei zu groß.")
                fh.write(chunk)
        part.replace(target)  # erst die fertige Datei sichtbar machen
    finally:
        part.unlink(missing_ok=True)
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
    from cstaktik import review

    hist = _load_hist()
    return _env.get_template("review.html").render(nav_active="matches", r=review.build(hist, max(1, min(n, 20))))


@app.get("/progress", response_class=HTMLResponse)
def progress_page(p: str = "") -> str:
    """Spielerprofil: Auftrag, Duell-Profil gegen Pros, Fehler-Trends, Maps, letzte Matches."""
    from cstaktik import pro
    from cstaktik.report.progress import profile

    hist = _load_hist()
    names = _names(hist)
    sids = sorted({s for h in hist for s in h.get("players", {})}, key=lambda s: names.get(s, s))
    sid = _default_sid({s: v for s, v in _players_state().items() if s in sids}, names, p) or (sids[0] if sids else None)
    if p in sids:
        sid = p
    prof = profile(hist, sid, pro.duel_stats(_load_pro())) if sid else None
    auftrag = next((x for x in _auftrag(hist) if x["sid"] == sid), None)
    tabs = [{"sid": s, "name": names.get(s, s), "on": s == sid} for s in sids]
    return _env.get_template("profil.html").render(nav_active="progress", p=prof, a=auftrag, tabs=tabs)


@app.get("/progress/karte", response_class=HTMLResponse)
def progress() -> str:
    from cstaktik.report.progress import render_progress

    return render_progress(_load_hist())


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


@app.get("/mehr", response_class=HTMLResponse)
def more_page() -> str:
    """Einstellungen, seltene Auswertungen und die Anleitung an einem Ort."""
    return _env.get_template("mehr.html").render(nav_active="mehr", n_history=len(_load_hist()), n_pro=len(_load_pro()))


@app.get("/spieler", response_class=HTMLResponse)
def players_page() -> str:
    """Wer wird analysiert? Spieler aus den letzten Matches zum Anklicken statt SteamIDs abtippen."""
    from cstaktik.config import load_focus_steamids

    return _env.get_template("spieler.html").render(nav_active="mehr", roster=pipeline.roster(),
                                                    focus=sorted(load_focus_steamids()))


@app.post("/spieler")
async def players_save(request: Request) -> RedirectResponse:
    from cstaktik.config import save_focus_steamids

    form = await request.form()
    chosen = [str(x) for x in form.getlist("sid") if str(x).isdigit()][:2]
    if not chosen:
        raise HTTPException(400, "Mindestens einen Spieler wählen.")
    names = {e["sid"]: e["name"] for e in pipeline.roster()}
    save_focus_steamids([(sid, names.get(sid, "")) for sid in chosen])
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "wartet", "name": "Alles für die neue Spielerauswahl neu berechnen",
                         "stage": "Wartet", "frac": 0.0, "started": None, "estimate": None, "samples": 0,
                         "cached": False, "report": None, "error": None}
    _executor.submit(_run_rerender_job, job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _run_rerender_job(job_id: str) -> None:
    def update(**kw):
        with _jobs_lock:
            _jobs[job_id].update(kw)

    update(status="läuft", stage="Reports neu berechnen", started=time.monotonic())
    try:
        n = pipeline.rerender_reports(progress=lambda stage, frac: update(stage=stage, frac=frac))
        update(status="fertig", stage="Fertig", frac=1.0,
               message=f"{n} Reports und alle Aufträge für die neue Spielerauswahl neu berechnet.")
    except Exception as exc:  # noqa: BLE001
        update(status="fehler", error=f"Neu berechnen fehlgeschlagen: {type(exc).__name__}: {exc}")


@app.get("/api/jobs/{job_id}")
def job_json(job_id: str) -> dict:
    return _get_job(job_id)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str) -> str:
    job = _get_job(job_id)
    return _env.get_template("job.html").render(nav_active="matches", job_id=job_id, name=job["name"])
