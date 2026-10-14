"""Datenmodell. Alles, was die Regeln und der Report sehen, kommt aus diesen Objekten.

Felder, die eine Demo nicht liefert, bleiben ``None``. Regeln prüfen das und melden
"nicht auswertbar" statt zu raten.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["ct", "t"]


class Vec(BaseModel):
    x: float
    y: float
    z: float = 0.0


class Player(BaseModel):
    steamid: str
    name: str
    is_focus: bool = False


class PlayerEconomy(BaseModel):
    """Geld/Equipment eines Spielers, gemessen am Sample-Tick der Runde (siehe Round.economy_tick)."""

    steamid: str
    side: Side
    equip_value: int | None = None
    balance: int | None = None  # Geld nach dem Kauf
    cash_spent: int | None = None  # in dieser Runde ausgegeben

    @property
    def money_before_buy(self) -> int | None:
        if self.balance is None or self.cash_spent is None:
            return None
        return self.balance + self.cash_spent


class Round(BaseModel):
    num: int
    start_tick: int
    freeze_end_tick: int | None = None
    end_tick: int
    winner: Side | None = None
    reason: str | None = None
    bomb_site: str | None = None
    sides: dict[str, Side] = Field(default_factory=dict)  # steamid -> Seite in dieser Runde
    economy_tick: int | None = None
    economy: list[PlayerEconomy] = Field(default_factory=list)


class Kill(BaseModel):
    tick: int
    round: int
    attacker_steamid: str | None = None  # None z. B. bei Fallschaden/Bombe
    attacker_name: str | None = None
    attacker_side: Side | None = None
    attacker_pos: Vec | None = None
    attacker_place: str | None = None
    victim_steamid: str
    victim_name: str
    victim_side: Side | None = None
    victim_pos: Vec | None = None
    victim_place: str | None = None
    weapon: str | None = None
    headshot: bool | None = None
    victim_inventory: list[str] | None = None  # Inventar kurz vor dem Tod


NadeKind = Literal["smoke", "molotov", "flash", "he", "decoy", "other"]


class GrenadeThrow(BaseModel):
    """Flugbahn eines Granaten-Projektils (Positionen aus der Demo, ausgedünnt)."""

    round: int
    entity_id: int
    thrower_steamid: str | None = None
    grenade_type: str  # Rohwert aus der Demo
    kind: NadeKind
    points: list[tuple[int, float, float, float]]  # (tick, x, y, z)
    # Werfer im Tick vor dem Abwurf: [tick, x, y, z, yaw, pitch, tempo_xy, tempo_z, duck] (duck None = unbekannt)
    throw: list[float | None] | None = None


class PositionSample(BaseModel):
    round: int
    tick: int
    steamid: str
    side: Side | None = None
    pos: Vec
    place: str | None = None
    alive: bool = True
    yaw: float | None = None  # Blickrichtung in Grad (Spielkoordinaten)
    weapon: str | None = None  # Waffe in der Hand (active_weapon_name)
    spotted: bool | None = None  # für das gegnerische Team sichtbar (Radar, Demo-Feld "spotted"); None = unbekannt


class UtilityArea(BaseModel):
    """Wirkung aus Detonations-Events der Demo: Smoke/Molotov mit Dauer, Flash/HE als Zeitpunkt."""

    round: int
    kind: Literal["smoke", "molotov", "flash", "he"]
    start_tick: int
    end_tick: int | None = None
    end_known: bool = True  # False: kein Ende-Event in der Demo, Rundenende als Grenze
    thrower_steamid: str | None = None
    pos: Vec


class Blind(BaseModel):
    """Geblendet (player_blind-Event der Demo)."""

    round: int
    tick: int
    victim_steamid: str
    attacker_steamid: str | None = None
    duration: float  # Sekunden laut Demo


class Shot(BaseModel):
    """Schuss (weapon_fire) mit horizontaler Geschwindigkeit des Schützen im Schuss-Tick."""

    round: int
    tick: int
    steamid: str
    weapon: str
    speed: float | None = None  # Units/s aus velocity_X/Y; None wenn nicht lesbar


class Damage(BaseModel):
    round: int
    tick: int
    attacker_steamid: str | None = None
    victim_steamid: str
    dmg: int  # tatsächlich abgezogene HP (awpy: dmg_health_real)
    weapon: str | None = None


class BombEvent(BaseModel):
    round: int
    tick: int
    event: str  # plant | defuse | detonate | drop | pickup (wie in awpy)
    steamid: str | None = None
    pos: Vec | None = None


class Duel(BaseModel):
    """Ein entschiedenes Duell (siehe duels.py). w_* = Sieger (Killer), l_* = Verlierer (Opfer)."""

    round: int
    tick: int  # Kill-Tick
    contact: int  # erster Schuss eines der beiden
    winner: str
    loser: str
    w_err: float | None = None  # Fadenkreuz-Abweichung zum Gegnerkopf im Kontakt-Tick (Grad)
    l_err: float | None = None
    w_react_ms: int | None = None  # eigener erster Schuss nach Kontakt (0 = zuerst geschossen)
    l_react_ms: int | None = None
    w_first_hit: bool | None = None
    l_first_hit: bool | None = None
    w_speed: int | None = None
    l_speed: int | None = None
    w_shots: int = 0
    l_shots: int = 0
    # Sichtung (Demo-Feld approximate_spotted_by = m_bSpottedByMask, vom Spiel berechnet): Tick, ab dem der Sieger
    # den Verlierer (w_seen) bzw. der Verlierer den Sieger (l_seen) durchgehend sah. None = in der Zeit nicht gesehen.
    seen_known: bool = False  # False = Demo/Parser liefert keine Sichtung, dann sagen w_seen/l_seen nichts
    w_seen: int | None = None
    l_seen: int | None = None


class MatchData(BaseModel):
    map_name: str | None = None
    tickrate: int
    tickrate_source: str  # woher der Wert stammt (Transparenz)
    source_file: str | None = None
    source_sha256: str | None = None
    players: list[Player]
    rounds: list[Round]
    kills: list[Kill] = Field(default_factory=list)
    damages: list[Damage] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    blinds: list[Blind] = Field(default_factory=list)
    grenades: list[GrenadeThrow] = Field(default_factory=list)
    positions: list[PositionSample] = Field(default_factory=list)
    utility: list[UtilityArea] = Field(default_factory=list)
    bomb: list[BombEvent] = Field(default_factory=list)
    duels: list[Duel] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # Hinweise auf fehlende Datenarten

    def focus_ids(self) -> set[str]:
        return {p.steamid for p in self.players if p.is_focus}

    def name_of(self, steamid: str) -> str:
        for p in self.players:
            if p.steamid == steamid:
                return p.name
        return steamid

    def round_by_num(self, num: int) -> Round | None:
        for r in self.rounds:
            if r.num == num:
                return r
        return None

    def focus_side(self, round_num: int) -> Side | None:
        r = self.round_by_num(round_num)
        if r is None:
            return None
        for sid in self.focus_ids():
            if sid in r.sides:
                return r.sides[sid]
        return None


Severity = Literal["hoch", "mittel", "niedrig", "gut"]  # "gut" = Lob, kein Fehler


class Finding(BaseModel):
    rule_id: str
    title: str
    round: int | None  # None bei rundenübergreifenden Findings
    tick: int | None
    steamid: str | None
    player_name: str | None
    severity: Severity
    text: str  # was passiert ist (kurz, deutsch)
    tip: str  # konkreter Tipp (ein Satz)
    evidence: dict = Field(default_factory=dict)  # Rohwerte aus den Daten
    rounds: list[int] = Field(default_factory=list)  # betroffene Runden (für Muster-Findings)
    # Zeichenhilfe fürs Replay in Spielkoordinaten, z. B. {"line": [[x, y], [x, y]], "label": "..."}
    overlay: dict = Field(default_factory=dict)


class RuleStatus(BaseModel):
    rule_id: str
    title: str
    evaluated: bool
    reason: str | None = None  # warum nicht auswertbar


class PlayerStats(BaseModel):
    steamid: str
    name: str
    rounds: int
    kills: int
    deaths: int
    adr: float | None  # None ohne Schadensdaten
    opening_kills: int
    opening_deaths: int
    traded_deaths: int
    utility_thrown: dict[str, int]


class AnalysisResult(BaseModel):
    findings: list[Finding]
    rule_status: list[RuleStatus]
    stats: list[PlayerStats] = Field(default_factory=list)
