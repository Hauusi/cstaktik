"""Schriften für das HUD-Design (Barlow, Barlow Condensed; SIL Open Font License).

Werden einmal von Google Fonts in data/fonts geladen und dann als data-URI in Report und Seiten
eingebettet. So bleibt der Report eine einzelne Datei, die auch ohne Internet funktioniert.
Ohne geladene Schriften greift die Systemschrift.
"""

from __future__ import annotations

import base64
import re
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "data" / "fonts"
CSS_URL = ("https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800"
           "&family=Barlow:wght@400;600;700&display=swap")
# Ein moderner User-Agent, damit Google woff2 liefert
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
WANTED = [("Barlow Condensed", w) for w in (600, 700, 800)] + [("Barlow", w) for w in (400, 600, 700)]


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste https-Quelle
        return resp.read(2_000_000)


def _file(family: str, weight: int, fonts_dir: Path) -> Path:
    return fonts_dir / f"{family.replace(' ', '')}-{weight}.woff2"


def ensure_fonts(fonts_dir: Path | None = None, timeout: float = 15.0) -> list[str]:
    """Lädt fehlende Schriften (nur Zeichensatz "latin", reicht für Deutsch). Gibt Fehlermeldungen zurück."""
    fonts_dir = fonts_dir or FONTS_DIR
    missing = [(f, w) for f, w in WANTED if not _file(f, w, fonts_dir).exists()]
    if not missing:
        return []
    try:
        css = _get(CSS_URL, timeout).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return [f"Schriften nicht geladen ({type(exc).__name__}): Systemschrift wird genutzt"]
    errors = []
    blocks = re.findall(r"/\* latin \*/\s*@font-face\s*{(.*?)}", css, re.S)
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for b in blocks:
        fam = re.search(r"font-family:\s*'([^']+)'", b)
        wt = re.search(r"font-weight:\s*(\d+)", b)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", b)
        if not (fam and wt and url) or (fam.group(1), int(wt.group(1))) not in missing:
            continue
        try:
            data = _get(url.group(1), timeout)
            if data[:4] != b"wOF2":
                raise ValueError("kein woff2")
            _file(fam.group(1), int(wt.group(1)), fonts_dir).write_bytes(data)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fam.group(1)} {wt.group(1)}: {type(exc).__name__}")
    return errors


_CSS_CACHE: dict[tuple, str] = {}


def font_css(fonts_dir: Path | None = None) -> str:
    """@font-face-Regeln mit eingebetteten Schriften (leer, wenn keine geladen sind). Gemerkt, bis sich die
    Schrift-Dateien ändern (jede Seite bettet sie ein)."""
    fonts_dir = fonts_dir or FONTS_DIR
    files = [_file(fam, wt, fonts_dir) for fam, wt in WANTED]
    key = (str(fonts_dir), tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in files))
    if key not in _CSS_CACHE:
        _CSS_CACHE.clear()
        _CSS_CACHE[key] = _font_css(fonts_dir)
    return _CSS_CACHE[key]


def _font_css(fonts_dir: Path) -> str:
    out = []
    for family, weight in WANTED:
        f = _file(family, weight, fonts_dir)
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode()
            out.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
                       f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "\n".join(out)
