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

    sub.add_parser("icons", help="Waffen-Icons herunterladen (data/icons)")

    sub.add_parser("progress", help="Fortschritts-Seite aus dem Match-Verlauf schreiben")

    s = sub.add_parser("serve", help="Web-Upload starten")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)

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
