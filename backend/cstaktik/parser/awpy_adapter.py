"""Einzige Stelle, die awpy/demoparser2 kennt: .dem -> MatchData.

Spaltennamen geprüft gegen awpy 2.0.2 (Demo.parse, fix_common_names) und
demoparser2 0.42 (parse_ticks mit ``ticks=``). Alles Optionale wird einzeln
abgefangen; was fehlt, landet in ``MatchData.missing``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from pathlib import Path

from cstaktik.model import (
    BombEvent,
    GrenadeThrow,
    Kill,
    MatchData,
    Player,
    PlayerEconomy,
    PositionSample,
    Round,
    UtilityArea,
    Vec,
)

_SIDE_MAP = {"ct": "ct", "t": "t", "CT": "ct", "TERRORIST": "t"}


def _side(value) -> str | None:
    if value is None:
        return None
    return _SIDE_MAP.get(str(value))


def _sid(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        sid = int(value)
    except (TypeError, ValueError):
        return None
    return str(sid) if sid > 0 else None


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _vec(row: dict, prefix: str) -> Vec | None:
    x, y, z = (_num(row.get(f"{prefix}{a}")) for a in ("X", "Y", "Z"))
    if x is None or y is None:
        return None
    return Vec(x=x, y=y, z=z or 0.0)


def _int_or_none(value) -> int | None:
    f = _num(value)
    return None if f is None else int(f)


_NADE_KEYWORDS = [
    ("smoke", "smoke"),
    ("flash", "flash"),
    ("molotov", "molotov"),
    ("incend", "molotov"),
    ("inferno", "molotov"),
    ("incgrenade", "molotov"),
    ("decoy", "decoy"),
    ("hegrenade", "he"),
    ("high explosive", "he"),
    ("he_grenade", "he"),
]


def nade_kind(raw: str | None) -> str:
    """Granatentyp aus dem Rohwert der Demo per Teilwort; Unbekanntes bleibt 'other'."""
    low = (raw or "").lower()
    for key, kind in _NADE_KEYWORDS:
        if key in low:
            return kind
    return "other"


def thin_path(points: list[tuple[int, float, float, float]], every: int) -> list[tuple[int, float, float, float]]:
    """Jeden ``every``-ten Tick behalten, Stillstand zusammenfassen, letzten Punkt immer behalten."""
    out: list[tuple[int, float, float, float]] = []
    for i, p in enumerate(points):
        last = i == len(points) - 1
        if not last and out and p[0] - out[-1][0] < every:
            continue
        if out and not last and abs(p[1] - out[-1][1]) < 1 and abs(p[2] - out[-1][2]) < 1 and abs(p[3] - out[-1][3]) < 1:
            continue  # liegt still
        out.append(p)
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_demo(
    path: Path,
    focus_steamids: set[str],
    parser_cfg: dict,
    progress: Callable[[str, float], None] | None = None,
) -> MatchData:
    """``progress(stufe, anteil)`` meldet den Fortschritt (0..1) für die Statusanzeige."""
    from awpy import Demo  # import hier, damit Tests ohne awpy-Parsing laufen

    step = progress or (lambda _stage, _frac: None)
    tickrate = int(parser_cfg["tickrate"])
    step("Demo einlesen", 0.0)
    dem = Demo(path, tickrate=tickrate)
    step("Demo parsen", 0.02)
    dem.parse(player_props=["yaw"])
    missing: list[str] = []

    step("Runden", 0.75)
    # --- Runden ---------------------------------------------------------------
    rounds: list[Round] = []
    for r in dem.rounds.to_dicts():
        rounds.append(
            Round(
                num=int(r["round_num"]),
                start_tick=int(r["start"]),
                freeze_end_tick=_int_or_none(r.get("freeze_end")),
                end_tick=int(r["end"]),
                winner=_side(r.get("winner")),
                reason=r.get("reason"),
                bomb_site=r.get("bomb_site"),
            )
        )
    round_by_num = {r.num: r for r in rounds}

    step("Positionen", 0.78)
    # --- Ticks: Spieler, Seiten, Positionen ------------------------------------
    ticks = dem.ticks
    step = max(1, tickrate // int(parser_cfg["position_samples_per_second"]))
    players: dict[str, str] = {}
    positions: list[PositionSample] = []
    for row in ticks.select(["tick", "steamid", "name", "side", "round_num"]).unique(
        subset=["steamid", "round_num"]
    ).to_dicts():
        sid = _sid(row["steamid"])
        side = _side(row["side"])
        if sid is None:
            continue
        players.setdefault(sid, row["name"])
        rnd = round_by_num.get(int(row["round_num"]))
        if rnd is not None and side is not None:
            rnd.sides[sid] = side

    cols = [
        c
        for c in ("tick", "steamid", "side", "round_num", "X", "Y", "Z", "place", "health", "yaw")
        if c in ticks.columns
    ]
    sampled = ticks.filter((ticks["tick"] % step) == 0).select(cols)
    for row in sampled.to_dicts():
        sid = _sid(row["steamid"])
        pos = _vec(row, "")
        if sid is None or pos is None:
            continue
        health = _num(row.get("health"))
        positions.append(
            PositionSample(
                round=int(row["round_num"]),
                tick=int(row["tick"]),
                steamid=sid,
                side=_side(row.get("side")),
                pos=pos,
                place=row.get("place") or None,
                alive=health is None or health > 0,
                yaw=_num(row.get("yaw")),
            )
        )

    step("Kills", 0.86)
    # --- Kills -------------------------------------------------------------------
    kills: list[Kill] = []
    for row in dem.kills.to_dicts():
        victim = _sid(row.get("victim_steamid"))
        if victim is None:
            continue
        kills.append(
            Kill(
                tick=int(row["tick"]),
                round=int(row["round_num"]),
                attacker_steamid=_sid(row.get("attacker_steamid")),
                attacker_name=row.get("attacker_name"),
                attacker_side=_side(row.get("attacker_side")),
                attacker_pos=_vec(row, "attacker_"),
                attacker_place=row.get("attacker_place") or None,
                victim_steamid=victim,
                victim_name=row.get("victim_name") or players.get(victim, victim),
                victim_side=_side(row.get("victim_side")),
                victim_pos=_vec(row, "victim_"),
                victim_place=row.get("victim_place") or None,
                weapon=row.get("weapon"),
                headshot=row.get("headshot"),
            )
        )

    step("Inventar", 0.88)
    # --- Inventar kurz vor dem Tod (optional) ------------------------------------
    if kills:
        try:
            wanted = sorted({k.tick - 1 for k in kills})
            inv = dem.parser.parse_ticks(["inventory"], ticks=wanted)
            inv_map = {}
            for rec in inv.to_dict("records"):
                sid = _sid(rec.get("steamid"))
                if sid is not None and rec.get("inventory") is not None:
                    inv_map[(int(rec["tick"]), sid)] = [str(i) for i in rec["inventory"]]
            for k in kills:
                k.victim_inventory = inv_map.get((k.tick - 1, k.victim_steamid))
        except Exception as exc:  # noqa: BLE001 - Daten optional, Fehler melden
            missing.append(f"Inventar beim Tod nicht lesbar ({type(exc).__name__})")

    step("Economy", 0.92)
    # --- Economy am Sample-Tick (optional) ----------------------------------------
    offset = int(parser_cfg["economy_sample_offset_s"] * tickrate)
    sample_ticks = {}
    for r in rounds:
        if r.freeze_end_tick is not None:
            sample_ticks[r.num] = min(r.freeze_end_tick + offset, r.end_tick)
    if sample_ticks:
        try:
            eco = dem.parser.parse_ticks(
                ["balance", "current_equip_value", "cash_spent_this_round", "team_name"],
                ticks=sorted(set(sample_ticks.values())),
            )
            by_tick: dict[int, list[dict]] = {}
            for rec in eco.to_dict("records"):
                by_tick.setdefault(int(rec["tick"]), []).append(rec)
            for r in rounds:
                t = sample_ticks.get(r.num)
                if t is None:
                    continue
                r.economy_tick = t
                for rec in by_tick.get(t, []):
                    sid = _sid(rec.get("steamid"))
                    side = _side(rec.get("team_name"))
                    if sid is None or side is None:
                        continue
                    r.economy.append(
                        PlayerEconomy(
                            steamid=sid,
                            side=side,
                            equip_value=_int_or_none(rec.get("current_equip_value")),
                            balance=_int_or_none(rec.get("balance")),
                            cash_spent=_int_or_none(rec.get("cash_spent_this_round")),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            missing.append(f"Economy-Daten nicht lesbar ({type(exc).__name__})")
    else:
        missing.append("Keine Freeze-End-Ticks: Economy nicht auswertbar")

    step("Granaten", 0.96)
    # --- Granaten-Flugbahnen ----------------------------------------------------------
    grenades: list[GrenadeThrow] = []
    try:
        by_entity: dict[int, list[dict]] = {}
        for row in dem.grenades.sort("tick").to_dicts():
            if row.get("entity_id") is None or row.get("round_num") is None:
                continue
            by_entity.setdefault(int(row["entity_id"]), []).append(row)
        every = int(parser_cfg.get("grenade_sample_ticks", 4))
        for eid, rows in by_entity.items():
            pts = [
                (int(r["tick"]), float(r["X"]), float(r["Y"]), float(r["Z"] or 0.0))
                for r in rows
                if _num(r.get("X")) is not None and _num(r.get("Y")) is not None
            ]
            if not pts:
                continue
            raw = str(rows[0].get("grenade_type"))
            grenades.append(
                GrenadeThrow(
                    round=int(rows[0]["round_num"]),
                    entity_id=eid,
                    thrower_steamid=_sid(rows[0].get("thrower_steamid")),
                    grenade_type=raw,
                    kind=nade_kind(raw),
                    points=thin_path(pts, every),
                )
            )
        unknown = sorted({g.grenade_type for g in grenades if g.kind == "other"})
        if unknown:
            missing.append(f"Unbekannte Granatentypen (grau dargestellt): {', '.join(unknown)}")
    except Exception as exc:  # noqa: BLE001
        missing.append(f"Granaten nicht lesbar ({type(exc).__name__})")

    step("Smokes & Molotovs", 0.97)
    # --- Smokes / Molotovs (Detonation bis Ende) --------------------------------------
    utility: list[UtilityArea] = []
    for kind, attr in (("smoke", "smokes"), ("molotov", "infernos")):
        try:
            for row in getattr(dem, attr).to_dicts():
                pos = _vec(row, "")
                if pos is None or row.get("round_num") is None:
                    continue
                utility.append(
                    UtilityArea(
                        round=int(row["round_num"]),
                        kind=kind,
                        start_tick=int(row["start_tick"]),
                        end_tick=_int_or_none(row.get("end_tick")),
                        thrower_steamid=_sid(row.get("thrower_steamid")),
                        pos=pos,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{kind} nicht lesbar ({type(exc).__name__})")

    step("Bombe", 0.99)
    # --- Flash / HE: Detonationszeitpunkt und -ort -----------------------------------
    rounds_for = sorted(rounds, key=lambda r: r.start_tick)

    def round_of(tick: int) -> int | None:
        for r in rounds_for:
            if r.start_tick <= tick <= r.end_tick:
                return r.num
        return None

    for kind, event in (("flash", "flashbang_detonate"), ("he", "hegrenade_detonate")):
        try:
            df = dem.events.get(event)
            for row in df.to_dicts() if df is not None else []:
                pos = _vec(row, "") or _vec({k.upper(): v for k, v in row.items() if k in ("x", "y", "z")}, "")
                rnd = round_of(int(row["tick"]))
                if pos is None or rnd is None:
                    continue
                utility.append(
                    UtilityArea(
                        round=rnd,
                        kind=kind,
                        start_tick=int(row["tick"]),
                        end_tick=int(row["tick"]),
                        thrower_steamid=_sid(row.get("user_steamid")),
                        pos=pos,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{event} nicht lesbar ({type(exc).__name__})")

    # --- Bombe -------------------------------------------------------------------------
    bomb: list[BombEvent] = []
    try:
        for row in dem.bomb.to_dicts():
            if row.get("round_num") is None:
                continue
            bomb.append(
                BombEvent(
                    round=int(row["round_num"]),
                    tick=int(row["tick"]),
                    event=str(row.get("event")),
                    steamid=_sid(row.get("steamid")),
                    pos=_vec(row, ""),
                )
            )
    except Exception as exc:  # noqa: BLE001
        missing.append(f"Bomben-Events nicht lesbar ({type(exc).__name__})")

    unknown_focus = focus_steamids - set(players)
    if unknown_focus:
        missing.append(f"Fokus-SteamIDs nicht in der Demo: {', '.join(sorted(unknown_focus))}")

    return MatchData(
        map_name=dem.header.get("map_name"),
        tickrate=tickrate,
        tickrate_source="config (parser.tickrate)",
        source_file=path.name,
        source_sha256=sha256_of(path),
        players=[Player(steamid=s, name=n, is_focus=s in focus_steamids) for s, n in sorted(players.items())],
        rounds=rounds,
        kills=sorted(kills, key=lambda k: k.tick),
        grenades=grenades,
        positions=positions,
        utility=utility,
        bomb=bomb,
        missing=missing,
    )
