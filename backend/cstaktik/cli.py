"""CLI: cstaktik analyze | players | serve"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cstaktik", description="CS2-Coach: Post-Match-Analyse")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Demo (.dem) oder MatchData (.json) auswerten")
    a.add_argument("file", type=Path)
    a.add_argument("--me", action="append", default=[], help="Fokus-SteamID64 (mehrfach möglich)")
    a.add_argument("--out", type=Path, default=None, help="Zielordner für den Report")

    p = sub.add_parser("players", help="Spieler + SteamID64 einer Demo anzeigen")
    p.add_argument("file", type=Path)

    mp = sub.add_parser("maps", help="Radarbilder + Kalibrierung herunterladen (data/maps)")
    mp.add_argument("names", nargs="*", help="Maps, z. B. de_mirage (leer = Standardliste)")

    pp = sub.add_parser("pro", help="Pro-Demo als Referenz speichern (kein Report)")
    pp.add_argument("file", type=Path)

    dg = sub.add_parser("diagnose", help="Echtdaten-Check einer Demo (Text zum Kalibrieren der Schwellen)")
    dg.add_argument("file", type=Path)
    cs = sub.add_parser("check-spotted", help="Prüfen, ob eine Demo die Radar-Sichtbarkeit (spotted) liefert")
    cs.add_argument("file", type=Path)
    sub.add_parser("pro-update", help="Alte Pro-Daten nachrüsten und alle eigenen Reports neu bauen")
    sub.add_parser("faceit-test", help="FACEIT-Schlüssel, Hub und Downloads-API-Freigabe prüfen")
    sub.add_parser("faceit-sync", help="Pro-Demos pro Map über die FACEIT-API holen")

    sub.add_parser("icons", help="Waffen-Icons herunterladen (data/icons)")

    sub.add_parser("progress", help="Fortschritts-Seite aus dem Match-Verlauf schreiben")

    s = sub.add_parser("serve", help="Web-Upload starten")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)
    f = getattr(args, "file", None)
    if isinstance(f, Path) and not f.exists():
        # Upload über die Webseite entpackt .bz2 und löscht das Archiv: dann gibt es die .dem
        alt = f.with_name(f.name[:-4]) if f.name.lower().endswith(".bz2") else None
        if alt is not None and alt.exists():
            args.file = alt
        else:
            print(f"Datei nicht gefunden: {f}", file=sys.stderr)
            stem = f.name.split(".")[0]
            near = sorted(p.name for p in f.parent.glob(f"*{stem[-8:]}*")) if f.parent.exists() else []
            if near:
                print("Passende Dateien im Ordner: " + ", ".join(near), file=sys.stderr)
            elif f.parent.exists():
                print(f"Im Ordner {f.parent}: " + ", ".join(sorted(p.name for p in f.parent.iterdir())[:20]), file=sys.stderr)
            return 1

    if args.cmd == "analyze":
        from cstaktik import pipeline

        if not args.file.exists():
            print(f"Datei nicht gefunden: {args.file}", file=sys.stderr)
            return 2
        try:
            out = pipeline.run(args.file, set(args.me) or None, args.out or pipeline.REPORTS_DIR)
        except ValueError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 1
        print(out)
        return 0

    if args.cmd == "players":
        from demoparser2 import DemoParser

        df = DemoParser(str(args.file)).parse_player_info()
        for rec in df.to_dict("records"):
            print(f"{rec.get('steamid')}\t{rec.get('name')}")
        return 0

    if args.cmd == "maps":
        from cstaktik import maps
        from cstaktik.report.radar import LOCAL_MAPS_DIR

        failed = 0
        for name in args.names or maps.DEFAULT_MAPS:
            try:
                maps.fetch_map(name, LOCAL_MAPS_DIR)
                print(f"ok      {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FEHLER  {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1 if failed else 0

    if args.cmd == "pro":
        from cstaktik import pipeline

        info = pipeline.run_pro(args.file)
        print(f"Pro-Demo gespeichert: {info['map']}, {info['rounds']} Runden, {info['nades']} Granaten; "
              f"{info['reports']} eigene Reports aktualisiert")
        return 0

    if args.cmd == "diagnose":
        from cstaktik import diagnose, pipeline
        from cstaktik.config import load_focus_steamids, load_rules_config

        config = load_rules_config()
        match = pipeline.load_any(pipeline.prepare_demo(args.file), load_focus_steamids(), config)
        # Pro-Demo ohne eure SteamIDs: nur Datenfelder und Wurfdaten prüfen, keine Coach-Analyse
        findings = pipeline._coach(match, config)[0].findings if match.focus_ids() else []
        text = diagnose.report(match, findings, config)
        print(text)
        out = pipeline.REPORTS_DIR / f"diagnose-{pipeline.demo_stem(args.file.name)}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"\nGespeichert: {out} (im Browser: /reports/{out.name})")
        return 0

    if args.cmd == "check-spotted":
        from demoparser2 import DemoParser

        from cstaktik import pipeline

        path = pipeline.prepare_demo(args.file)
        parser = DemoParser(str(path))
        try:
            df = parser.parse_ticks(["spotted"], ticks=list(range(0, 200_000, 640)))
        except Exception as exc:  # noqa: BLE001
            print(f"spotted NICHT lesbar: {type(exc).__name__}: {exc}")
            return 1
        col = df["spotted"] if "spotted" in df.columns else None
        if col is None or len(col) == 0:
            print("spotted fehlt in dieser Demo.")
            return 1
        vals = col.dropna() if hasattr(col, "dropna") else col
        print(f"spotted lesbar: {len(vals)} Werte, davon sichtbar: {int(sum(bool(v) for v in vals))}")
        return 0

    if args.cmd == "pro-update":
        from cstaktik import pipeline

        print(f"Pro-Daten nachgerüstet: {pipeline.upgrade_pro()}")
        print(f"Verlauf nachgerüstet: {pipeline.upgrade_history()}")
        print(f"Reports neu gebaut: {pipeline.rerender_reports()}")
        return 0

    if args.cmd in ("faceit-test", "faceit-sync"):
        from cstaktik import faceit, pipeline
        from cstaktik.config import load_rules_config

        try:
            if args.cmd == "faceit-test":
                for line in faceit.selftest(load_rules_config()["faceit"]):
                    print(line)
            else:
                res = pipeline.faceit_sync()
                print("Neu:", res["added"], "Gesamt:", res["total"])
        except faceit.FaceitError as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "icons":
        from cstaktik import icons

        failed = icons.ensure_icons(set(icons.ALL_ICONS))
        print(f"{len(icons.ALL_ICONS) - len(failed)} Icons ok" + (f", Fehler: {', '.join(failed)}" if failed else ""))
        return 1 if failed else 0

    if args.cmd == "progress":
        from cstaktik import history, pipeline
        from cstaktik.report.progress import render_progress

        out = pipeline.REPORTS_DIR / "fortschritt.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_progress(history.load_all(pipeline.HISTORY_DIR)), encoding="utf-8")
        print(out)
        return 0

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("cstaktik.api:app", host=args.host, port=args.port)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
