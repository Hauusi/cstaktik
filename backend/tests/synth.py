"""Synthetische Mini-Matches für Tests. Koordinaten und Orte sind frei erfunden
(Test-Szenarien, keine echten Map-Daten) und tragen deshalb das Präfix 'Synth'."""

from __future__ import annotations

from cstaktik.model import Kill, MatchData, Player, PlayerEconomy, PositionSample, Round, Vec

TR = 64
ME, BRO = "76561190000000001", "76561190000000002"
MATES = [ME, BRO, "76561190000000003", "76561190000000004", "76561190000000005"]
ENEMIES = [f"7656119000000001{i}" for i in range(5)]
NAMES = {ME: "Ich", BRO: "Bruder", **{m: f"Mate{i}" for i, m in enumerate(MATES[2:], 3)},
         **{e: f"Gegner{i}" for i, e in enumerate(ENEMIES, 1)}}


def _round(num: int, winner: str, equip: dict[str, int] | None = None) -> Round:
    start = num * 10_000
    r = Round(num=num, start_tick=start, freeze_end_tick=start + 15 * TR, end_tick=start + 100 * TR, winner=winner)
    r.sides = {m: "ct" for m in MATES} | {e: "t" for e in ENEMIES}
    if equip is not None:
        r.economy_tick = r.freeze_end_tick + 5 * TR
        for sid in MATES:
            r.economy.append(PlayerEconomy(steamid=sid, side="ct", equip_value=equip.get(sid, 4500),
                                           balance=1000, cash_spent=equip.get(sid, 4500)))
        for sid in ENEMIES:
            r.economy.append(PlayerEconomy(steamid=sid, side="t", equip_value=4500, balance=1000, cash_spent=4500))
    return r


def _positions(r: Round, where: dict[str, Vec]) -> list[PositionSample]:
    """Jeder Spieler läuft von (x-400, y) nach where[sid], Sample alle 32 Ticks."""
    out = []
    for sid, end in where.items():
        for i, t in enumerate(range(r.freeze_end_tick, r.freeze_end_tick + 20 * TR, TR // 2)):
            frac = min(1.0, i / 30)
            out.append(PositionSample(round=r.num, tick=t, steamid=sid, side=r.sides[sid],
                                      pos=Vec(x=end.x - 400 * (1 - frac), y=end.y, z=0)))
    return out


def _kill(r: Round, sec: float, att: str, vic: str, vpos: Vec, place: str | None,
          inv: list[str] | None = None) -> Kill:
    return Kill(tick=r.freeze_end_tick + int(sec * TR), round=r.num, attacker_steamid=att, attacker_name=NAMES[att],
                attacker_side=r.sides[att], attacker_pos=Vec(x=vpos.x + 600, y=vpos.y), victim_steamid=vic,
                victim_name=NAMES[vic], victim_side=r.sides[vic], victim_pos=vpos, victim_place=place,
                weapon="ak47", headshot=True, victim_inventory=inv)


def build_match(focus: tuple[str, ...] = (ME, BRO)) -> MatchData:
    far = {m: Vec(x=3000 + 100 * i, y=3000) for i, m in enumerate(MATES)}
    spot = Vec(x=0, y=0)
    rounds, positions, kills = [], [], []

    # R1 Pistole, gewonnen, ohne Tode
    r1 = _round(1, "ct", {m: 800 for m in MATES})
    rounds.append(r1)

    # R2: ME stirbt als Erster in SynthMid allein (Mitspieler >1500 weg), mit Flash+Smoke. Uneinheitlicher Kauf.
    r2 = _round(2, "t", {ME: 4700, BRO: 800})
    rounds.append(r2)
    positions += _positions(r2, {ME: spot, **{m: far[m] for m in MATES[1:]}})
    kills.append(_kill(r2, 20, ENEMIES[0], ME, spot, "SynthMid", ["Glock-18", "Flashbang", "Smoke Grenade"]))

    # R3: ME stirbt in SynthMid, BRO steht 200 Units daneben -> kein Untraded-Finding
    r3 = _round(3, "ct")
    rounds.append(r3)
    positions += _positions(r3, {ME: spot, BRO: Vec(x=200, y=0), **{m: far[m] for m in MATES[2:]}})
    kills.append(_kill(r3, 20, ENEMIES[1], ME, spot, "SynthMid", ["USP-S"]))

    # R4: ME stirbt in SynthMid, Mitspieler weit weg, aber BRO tradet nach 1s -> kein Untraded-Finding
    r4 = _round(4, "ct")
    rounds.append(r4)
    positions += _positions(r4, {ME: spot, **{m: far[m] for m in MATES[1:]}})
    kills.append(_kill(r4, 20, ENEMIES[2], ME, spot, "SynthMid", []))
    kills.append(_kill(r4, 21, BRO, ENEMIES[2], Vec(x=600, y=0), "SynthMid"))

    # R5: Force (Ø 2500) verloren, R6: Ø 1000 -> Force-Finding
    r5 = _round(5, "t", {m: 2500 for m in MATES})
    r6 = _round(6, "t", {m: 1000 for m in MATES})
    rounds += [r5, r6]

    players = [Player(steamid=s, name=NAMES[s], is_focus=s in focus) for s in MATES + ENEMIES]
    return MatchData(map_name="de_mirage", tickrate=TR, tickrate_source="synthetisch", source_file="synth.json",
                     players=players, rounds=rounds, kills=kills, positions=positions)
