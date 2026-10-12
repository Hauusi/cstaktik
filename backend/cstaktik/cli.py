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

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("cstaktik.api:app", host=args.host, port=args.port)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
