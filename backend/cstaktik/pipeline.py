"""Gemeinsamer Ablauf für CLI und Web: Demo/JSON -> MatchData -> Analyse -> HTML."""

from __future__ import annotations

import bz2
import json
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from cstaktik.config import load_focus_steamids, load_rules_config
from cstaktik.model import MatchData
from cstaktik.parser.loader import load_match, save_match
from cstaktik.report.render import write_report
from cstaktik.rules import analyze

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEMOS_DIR = DATA_DIR / "demos_raw"
REPORTS_DIR = DATA_DIR / "reports"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_DIR = DATA_DIR / "history"
GOALS_FILE = DATA_DIR / "goals.json"
COACHING_FILE = DATA_DIR / "coaching.json"
PRO_DIR = DATA_DIR / "pro"
PRO_DEMOS_DIR = DATA_DIR / "pro_demos"  # hochgeladene Pro-Demos, getrennt von den eigenen
# Bei Änderungen am Datenmodell erhöhen, damit alte Caches neu geparst werden.
CACHE_SCHEMA = 15
# Obergrenze für entpackte Demos (Schutz gegen manipulierte .bz2-Dateien).
MAX_DEMO_BYTES = 2 * 1024**3


def demo_stem(name: str) -> str:
    """'match.dem.bz2' -> 'match', 'match.dem' -> 'match'."""
    low = name.lower()
    for suffix in (".dem.bz2", ".bz2", ".dem", ".json"):
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_demo_name(name: str) -> bool:
    return name.lower().endswith((".dem", ".dem.bz2"))


def decompress_bz2(src: Path, dst: Path, max_bytes: int = MAX_DEMO_BYTES) -> Path:
    written = 0
    try:
        with bz2.open(src, "rb") as fin, dst.open("wb") as fout:
            while chunk := fin.read(1 << 20):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(f"Entpackte Demo größer als {max_bytes // 1024**2} MB")
                fout.write(chunk)
    except (OSError, EOFError, ValueError) as exc:
        dst.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"Keine gültige .bz2-Datei: {exc}") from exc
    return dst


def prepare_demo(path: Path, remove_source: bool = False) -> Path:
    """.dem.bz2 wird neben die Quelle als .dem entpackt; alles andere bleibt unverändert."""
    if not path.name.lower().endswith(".bz2"):
        return path
    target = decompress_bz2(path, path.with_name(f"{demo_stem(path.name)}.dem"))
    if remove_source:
        path.unlink(missing_ok=True)
    return target


Progress = Callable[[str, float], None]
TIMINGS_FILE = CACHE_DIR / "timings.json"
_TIMINGS_KEEP = 20


def _record_timing(size_bytes: int, seconds: float) -> None:
    """Gemessene Parse-Dauer speichern: Basis für die Restzeit-Schätzung."""
    try:
        data = json.loads(TIMINGS_FILE.read_text()) if TIMINGS_FILE.exists() else []
    except (OSError, ValueError):
        data = []
    data.append({"mb": round(size_bytes / 1024**2, 2), "s": round(seconds, 1)})
    TIMINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMINGS_FILE.write_text(json.dumps(data[-_TIMINGS_KEEP:]))


def estimate_seconds(size_bytes: int) -> float | None:
    """Median Sekunden/MB der bisherigen Läufe auf diesem Rechner x Dateigröße. None ohne Messwerte."""
    try:
        data = json.loads(TIMINGS_FILE.read_text()) if TIMINGS_FILE.exists() else []
    except (OSError, ValueError):
        return None
    rates = [d["s"] / d["mb"] for d in data if d.get("mb", 0) > 0]
    if not rates:
        return None
    return statistics.median(rates) * size_bytes / 1024**2


def timing_samples() -> int:
    try:
        return len(json.loads(TIMINGS_FILE.read_text())) if TIMINGS_FILE.exists() else 0
    except (OSError, ValueError):
        return 0


def cache_file(match_id: str | None) -> Path | None:
    """Neuester vorhandener Cache einer Demo (auch ältere Schema-Versionen, z. B. für Pro-Szenen)."""
    if not match_id:
        return None
    cur = CACHE_DIR / f"{match_id}.v{CACHE_SCHEMA}.json"
    if cur.exists():
        return cur
    def version(p: Path) -> int:
        v = p.stem.rsplit(".v", 1)[-1]
        return int(v) if v.isdigit() else 0

    old = sorted(CACHE_DIR.glob(f"{match_id}.v*.json"), key=version, reverse=True) if CACHE_DIR.exists() else []
    return old[0] if old else None


def is_cached(path: Path) -> bool:
    if path.suffix.lower() != ".dem":
        return False
    from cstaktik.parser.awpy_adapter import sha256_of

    return (CACHE_DIR / f"{sha256_of(path)}.v{CACHE_SCHEMA}.json").exists()


def load_any(
    path: Path, focus: set[str], config: dict, use_cache: bool = True, progress: Progress | None = None
) -> MatchData:
    """``.dem`` wird mit awpy geparst (Ergebnis als JSON gecacht), ``.json`` direkt geladen."""
    if path.suffix.lower() == ".json":
        match = load_match(path)
    elif path.suffix.lower() == ".dem":
        from cstaktik.parser.awpy_adapter import parse_demo, sha256_of

        cache = CACHE_DIR / f"{sha256_of(path)}.v{CACHE_SCHEMA}.json"
        if use_cache and cache.exists():
            match = load_match(cache)
        else:
            t0 = time.monotonic()
            match = parse_demo(path, focus, config["parser"], progress)
            _record_timing(path.stat().st_size, time.monotonic() - t0)
            save_match(match, cache)
    else:
        raise ValueError(f"Unbekanntes Format: {path.suffix} (erwartet .dem oder .json)")
    if focus:  # Fokus-Spieler immer aus der aktuellen Config, nicht aus dem Cache
        for p in match.players:
            p.is_focus = p.steamid in focus
    return match


def _coach(match: MatchData, config: dict):
    """Regeln + Vorbild (eigene Siegrunden) + Pro-Vergleich. Gemeinsam für run() und rerender_reports()."""
    from cstaktik import history as _history
    from cstaktik import pro as _pro
    from cstaktik.reference import enrich, enrich_pro

    from cstaktik.reference import pro_clips

    from cstaktik import situation

    result = analyze(match, config)
    hist = _history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else []
    enrich(match, result.findings, hist)
    pro = _pro.load_all(PRO_DIR)
    enrich_pro(match, result.findings, pro)
    # Gewinnchance je Lage: eure anderen Matches + Pro-Demos. Dieses Match nicht, sonst bewertet es sich selbst.
    me = match.source_sha256 or match.source_file
    states = [s for h in hist if h.get("id") != me for s in h.get("states", [])]
    states += [s for d in pro for s in d.get("states", [])]
    model = situation.WinModel(states, config["situation"]["win_min_rounds"])
    situation.enrich(match, result.findings, model, config["situation"], config["coach"]["trade_window_s"])
    situation.enrich_pro(match, result.findings, pro, config["situation"]["pro_min_cases"])
    from cstaktik import coach_voice

    coach_voice.apply(result.findings, config["rules"]["death_review"]["close_units"])
    clips = pro_clips(match, result.findings, load_pro_matches(pro, match.map_name), pro)

    return result, clips


MAX_PRO_MATCHES = 8  # so viele Pro-Demos derselben Map werden für Pro-Szenen geladen (neueste zuerst)


def load_pro_matches(pro: list[dict], map_name: str | None) -> list[MatchData]:
    """Vollständige Pro-Demos (aus dem Cache) für die Pro-Szenen im Replay. Ohne Cache keine Szene."""
    out = []
    for d in sorted((d for d in pro if d.get("map") == map_name), key=lambda d: d.get("analyzed_at", ""),
                    reverse=True):
        cache = cache_file(d.get("id"))
        if cache is not None:
            try:
                out.append(load_match(cache))
            except (OSError, ValueError):
                continue
        if len(out) >= MAX_PRO_MATCHES:
            break
    return out


def run(
    path: Path, focus: set[str] | None = None, out_dir: Path = REPORTS_DIR, progress: Progress | None = None
) -> Path:
    """``progress(stufe, anteil)``: Parsen belegt 0–0.9, Regeln und Report den Rest."""
    report = progress or (lambda _stage, _frac: None)
    config = load_rules_config()
    focus = focus or load_focus_steamids()
    path = prepare_demo(path)
    match = load_any(path, focus, config, progress=lambda st, f: report(st, 0.9 * f))
    report("Fehler suchen", 0.92)
    upgrade_pro()
    upgrade_history()
    result, clips = _coach(match, config)
    report("Karte laden", 0.94)
    from cstaktik import goals, history, maps
    from cstaktik.report.radar import LOCAL_MAPS_DIR

    note = maps.ensure_map(match.map_name, LOCAL_MAPS_DIR)
    if note:
        match.missing.append(note)
    from cstaktik import icons

    used = {icons.icon_for(w) for w in {p.weapon for p in match.positions} | {sh.weapon for sh in match.shots}
            | {g.grenade_type for g in match.grenades}}
    used |= {"smokegrenade", "flashbang", "hegrenade", "molotov", "incgrenade", "decoy"}
    failed = icons.ensure_icons(used - {None}, icons.ICONS_DIR)
    from cstaktik import fonts

    fonts.ensure_fonts()  # ohne Netz: Systemschrift
    if failed:
        match.missing.append(f"Waffen-Icons nicht geladen ({', '.join(failed)}): einfache Form statt Icon")
    report("Ziele prüfen", 0.95)
    stem = demo_stem(path.name)
    my_id = match.source_sha256 or match.source_file
    all_hist = history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else []
    old = next((h for h in all_hist if h.get("id") == my_id), None)
    # erneut ausgewertet: zählt zum ursprünglichen Zeitpunkt; "vorher" sind nur Matches bis dahin
    when = (old or {}).get("analyzed_at") or coaching_now()
    past = [h for h in all_hist if h.get("id") != my_id and (h.get("analyzed_at") or "") <= when]
    summary = history.summarize(match, result, f"{stem}.html", past=past)
    summary["analyzed_at"] = when
    state = goals.load(GOALS_FILE)
    goal_check = goals.update(state, summary, config["goals"], config.get("mechanics"))
    goals.save(state, GOALS_FILE)
    # Ziel-Check mitspeichern, damit der Report später (z. B. nach neuen Pro-Demos) neu gebaut werden kann
    summary["goal_check"] = goal_check if goal_check.get("checks") or not old else old.get("goal_check", goal_check)
    # Auftrag (Fokus-Lektion) prüfen und ggf. neu setzen; mitspeichern für spätere Neubauten des Reports
    from cstaktik import coaching

    cstate = coaching.load(COACHING_FILE)
    if coaching_stale(cstate, load_focus_steamids()):  # Fokus aus players.yaml, nicht aus einem Einzel-Upload
        if past:  # Aufträge stammen aus der alten Zählweise: einmal alles neu berechnen, bevor geprüft wird
            report("Aufträge neu berechnen (einmalig)", 0.95)
            rerender_reports()
            cstate = coaching.load(COACHING_FILE)
            past = [h for h in history.load_all(HISTORY_DIR) if h.get("id") != my_id
                    and (h.get("analyzed_at") or "") <= when]
        cstate["count_version"] = coaching.COUNT_VERSION
        cstate["focus_ids"] = sorted(load_focus_steamids())
    summary["focus_check"] = coaching.update_all(cstate, summary, summary.get("lesson_rank_by") or {},
                                                 past=past, **goal_kw(config))
    coaching.save(cstate, COACHING_FILE)
    history.save(summary, HISTORY_DIR)
    report("Report bauen", 0.96)
    from cstaktik import coach_voice

    prev = history.previous(history.load_all(HISTORY_DIR), summary)
    mem = coach_voice.memory(prev, summary.get("lessons") or {}, summary.get("rounds") or 0)
    from cstaktik.coach_voice import recurrence

    out = write_report(match, result, out_dir / f"{stem}.html", goal_check=summary["goal_check"], pro_clips=clips,
                       recur=recurrence(past), past=past,
                       memory=mem, focus=summary["focus_check"])
    report("Fertig", 1.0)
    return out


def coaching_stale(state: dict, focus: set[str]) -> bool:
    """Aufträge neu berechnen? Bei alter Zählweise oder wenn andere Spieler im Fokus stehen als beim Berechnen.
    Ältere Dateien ohne 'focus_ids' gelten beim Fokus als passend (kein unnötiger Neubau)."""
    from cstaktik import coaching

    if "players" not in state or state.get("count_version") != coaching.COUNT_VERSION:
        return True
    return "focus_ids" in state and set(state["focus_ids"]) != set(focus or ())


def coaching_now() -> str:
    from cstaktik.coaching import now_local

    return now_local()


def goal_kw(config: dict) -> dict:
    """Auftrags-Schwellen aus rules.yaml (goals) für coaching.update_all."""
    g = config["goals"]
    return {"target_factor": g["target_factor"], "done_after": g["done_after"],
            "min_master_rounds": g.get("min_master_rounds", 40), "min_check_rounds": g.get("min_check_rounds", 12),
            "pool_matches": g.get("pool_matches", 5), "min_count": g.get("min_count", 3)}


def _current_match(h: dict, focus: set[str], config: dict) -> MatchData:
    """Match aus dem Cache; ist der Cache von einer älteren Version (z. B. ohne Blendungen oder Wurfdaten) und liegt
    die Demo noch in data/demos_raw, wird sie neu gelesen. Sonst bleibt es beim alten Cache."""
    cache = cache_file(h["id"])
    demo = DEMOS_DIR / str(h.get("source_file") or "")
    if (cache is None or not cache.name.endswith(f".v{CACHE_SCHEMA}.json")) and h.get("source_file") and demo.exists():
        try:
            return load_any(demo, focus, config)
        except Exception:  # noqa: BLE001 - kaputte Demo: alter Cache ist besser als kein Report
            pass
    return load_match(cache)


def roster(n: int = 4) -> list[dict]:
    """Spieler aus den letzten ``n`` eigenen Matches (aus dem Cache): Name, SteamID, in wie vielen Matches,
    wie oft im selben Team wie die aktuellen Fokus-Spieler. Grundlage für die Seite 'Spieler'."""
    from cstaktik import history

    focus = load_focus_steamids()
    hist = [h for h in (history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else []) if cache_file(h.get("id"))]
    seen: dict[str, dict] = {}
    for h in hist[-n:]:
        try:
            m = load_match(cache_file(h["id"]))
        except (OSError, ValueError):
            continue
        names = {p.steamid: p.name for p in m.players}
        mates: set[str] = set()
        for r in m.rounds:
            fs = {r.sides.get(f) for f in focus if f in r.sides}
            mates |= {sid for sid, side in r.sides.items() if side in fs}
        for sid, name in names.items():
            e = seen.setdefault(sid, {"sid": sid, "name": name, "matches": 0, "with_focus": 0,
                                      "focus": sid in focus, "maps": set()})
            e["matches"] += 1
            e["with_focus"] += sid in mates
            e["name"] = name
            e["maps"].add((m.map_name or "?").removeprefix("de_").capitalize())
    out = sorted(seen.values(), key=lambda e: (-e["focus"], -e["with_focus"], -e["matches"], e["name"].lower()))
    for e in out:
        e["maps"] = sorted(e["maps"])
    return out


def rerender_reports(maps: set[str] | None = None, progress: Progress | None = None) -> int:
    """Baut die Reports eigener Matches aus dem Cache neu (z. B. nach neuen Pro-Demos).

    Verlauf und Ziele bleiben unverändert. Matches ohne Cache (Schema geändert) werden übersprungen."""
    from cstaktik import history

    report = progress or (lambda _stage, _frac: None)
    config = load_rules_config()
    focus = load_focus_steamids()
    todo = [h for h in (history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else [])
            if h.get("report_file") and (maps is None or h.get("map") in maps)
            and cache_file(h["id"]) is not None]
    from cstaktik import coaching

    # Aufträge aus dem Verlauf neu aufbauen (nur beim Neubau aller Matches), wenn es noch keine Datei gibt, sie im
    # alten Format ist oder mit einer älteren Zählweise der Lektionen entstand. Übungen und Wochenpläne bleiben.
    old_state = coaching.load(COACHING_FILE)
    stale = coaching_stale(old_state, focus) or not COACHING_FILE.exists()
    rebuild = None
    if maps is None and stale:
        rebuild = {"players": {sid: {"focus": None, "done": [], "drills": slot.get("drills", []),
                                     "weeks": slot.get("weeks", {})}
                               for sid, slot in old_state.get("players", {}).items()}}
    done = 0
    in_todo = {h["id"]: h for h in todo}
    everything = [in_todo.get(h.get("id"), h) for h in (history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else [])]

    def before(h: dict) -> list[dict]:
        """Matches vor diesem (alle Maps), mit den in diesem Lauf schon neu gezählten Einträgen."""
        return [x for x in everything if x.get("id") != h.get("id")
                and (x.get("analyzed_at") or "") <= (h.get("analyzed_at") or "")]

    for i, h in enumerate(todo):
        report(f"Report {i + 1}/{len(todo)} aktualisieren", i / max(1, len(todo)))
        match = _current_match(h, focus, config)
        if focus:  # wie load_any: Fokus aus der aktuellen Config, sonst aus dem Cache
            for p in match.players:
                p.is_focus = p.steamid in focus
        if not match.focus_ids():
            continue
        result, clips = _coach(match, config)
        # ganze Zusammenfassung neu (Spieler, Lektionen, Duelle, Tode ...), damit z. B. ein neu gewählter
        # Fokus-Spieler überall auftaucht; Zeitpunkt, Report und Ziel-Check bleiben
        keep = {k: h[k] for k in ("id", "analyzed_at", "report_file", "goal_check", "focus_check") if k in h}
        fresh = history.summarize(match, result, h.get("report_file"), past=before(h))
        h.clear()
        h.update(fresh)
        h.update(keep)
        if rebuild is not None:  # Aufträge chronologisch neu durchspielen (alle Matches)
            h["focus_check"] = coaching.update_all(rebuild, h, h["lesson_rank_by"], past=before(h), **goal_kw(config))
        history.save(h, HISTORY_DIR)
        from cstaktik import coach_voice

        prev = history.previous(history.load_all(HISTORY_DIR), h)
        mem = coach_voice.memory(prev, h["lessons"], h.get("rounds") or 0)
        write_report(match, result, REPORTS_DIR / h["report_file"], goal_check=h.get("goal_check"), pro_clips=clips,
                     recur=coach_voice.recurrence(before(h)), past=before(h),
                     memory=mem, focus=h.get("focus_check"))
        done += 1
    if rebuild is not None and done:
        rebuild["count_version"] = coaching.COUNT_VERSION
        rebuild["focus_ids"] = sorted(focus)
        coaching.save(rebuild, COACHING_FILE)
    return done


def upgrade_history() -> int:
    """Ältere Verlaufs-Einträge ohne Rundenzustände (Gewinnchance) oder T-Laufwege (Playbook) aus dem Cache ergänzen."""
    from cstaktik import history
    from cstaktik.situation import round_states

    from cstaktik.playbook import ct_plays, plays

    focus = load_focus_steamids()
    n = 0
    for h in history.load_all(HISTORY_DIR) if HISTORY_DIR.exists() else []:
        cache = cache_file(h.get("id"))
        if ("states" in h and "plays" in h and "ct_plays" in h) or cache is None:
            continue
        try:  # ein kaputter oder veralteter Cache darf Uploads und pro-update nicht blockieren
            m = load_match(cache)
        except (OSError, ValueError):
            continue
        h.setdefault("states", round_states(m))
        team = focus & {p.steamid for p in m.players} or m.focus_ids()  # aktuelle Spieler-Einstellung zuerst
        if team:  # ohne Fokus-Spieler nichts speichern, sonst gilt der Eintrag als nachgerüstet
            h.setdefault("plays", plays(m, team=team))
            h.setdefault("ct_plays", ct_plays(m, team=team))
        history.save(h, HISTORY_DIR)
        n += 1
    return n


def upgrade_pro() -> int:
    """Ältere Pro-Zusammenfassungen (nur Positionen) aus dem Cache um Granaten/Tode ergänzen."""
    from cstaktik import pro

    n = 0
    for d in pro.load_all(PRO_DIR):
        if d.get("version", 1) >= pro.VERSION:
            continue
        cache = cache_file(d.get("id"))
        demo = PRO_DEMOS_DIR / str(d.get("source_file") or "")
        if (cache is None or not cache.name.endswith(f".v{CACHE_SCHEMA}.json")) and d.get("source_file") and demo.exists():
            # Cache zu alt für neue Felder (z. B. Duelle): Pro-Demo neu parsen
            try:
                run_pro(demo, rerender=False)
                n += 1
            except Exception:  # noqa: BLE001 - einzelne Demo überspringen
                pass
            continue
        if cache is None:
            continue
        summary = pro.summarize(load_match(cache), load_rules_config()["coach"]["trade_window_s"])
        summary["analyzed_at"] = d.get("analyzed_at", summary["analyzed_at"])
        pro.save(summary, PRO_DIR)
        n += 1
    return n


def run_pro(path: Path, progress: Progress | None = None, use_cache: bool = True, rerender: bool = True) -> dict:
    """Pro-Demo parsen und als Referenz speichern (keine Fokus-Spieler). Danach werden die eigenen
    Reports derselben Map mit den neuen Pro-Daten neu gebaut.

    ``use_cache=False`` (FACEIT-Sync): kein großer JSON-Cache, nur die kleine Zusammenfassung bleibt."""
    from cstaktik import pro

    report = progress or (lambda _stage, _frac: None)
    config = load_rules_config()
    path = prepare_demo(path)
    if use_cache:
        match = load_any(path, set(), config, progress=lambda st, f: report(st, 0.85 * f))
    else:
        from cstaktik.parser.awpy_adapter import parse_demo

        match = parse_demo(path, set(), config["parser"], lambda st, f: report(st, 0.85 * f))
    summary = pro.summarize(match, config["coach"]["trade_window_s"])
    pro.save(summary, PRO_DIR)
    if not rerender:
        return {"map": summary["map"], "rounds": summary["rounds"], "players": len(match.players),
                "nades": len(summary["nades"]), "reports": 0}
    upgrade_pro()
    updated = rerender_reports({summary["map"]}, lambda st, f: report(st, 0.85 + 0.15 * f))
    report("Fertig", 1.0)
    return {"map": summary["map"], "rounds": summary["rounds"], "players": len(match.players),
            "nades": len(summary["nades"]), "reports": updated}


def faceit_sync(log=print) -> dict:
    """Pro-Demos über die FACEIT-API holen (siehe faceit.py)."""
    from cstaktik import faceit

    cfg = load_rules_config()["faceit"]
    return faceit.sync(cfg, PRO_DIR, DATA_DIR / "faceit_tmp", lambda p: run_pro(p), log=log)
