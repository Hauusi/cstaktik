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


class GrenadeEvent(BaseModel):
    tick: int
    round: int
    thrower_steamid: str
    grenade_type: str
    pos: Vec


class PositionSample(BaseModel):
    round: int
    tick: int
    steamid: str
    side: Side | None = None
    pos: Vec
    place: str | None = None
    alive: bool = True
    yaw: float | None = None  # Blickrichtung in Grad (Spielkoordinaten)


class UtilityArea(BaseModel):
    """Liegende Smoke/Molotov aus den Detonations-Events der Demo."""

    round: int
    kind: Literal["smoke", "molotov"]
    start_tick: int
    end_tick: int | None = None
    thrower_steamid: str | None = None
    pos: Vec


class BombEvent(BaseModel):
    round: int
    tick: int
    event: str  # plant | defuse | detonate | drop | pickup (wie in awpy)
    steamid: str | None = None
    pos: Vec | None = None


class MatchData(BaseModel):
    map_name: str | None = None
    tickrate: int
    tickrate_source: str  # woher der Wert stammt (Transparenz)
    source_file: str | None = None
    source_sha256: str | None = None
    players: list[Player]
    rounds: list[Round]
    kills: list[Kill] = Field(default_factory=list)
    grenades: list[GrenadeEvent] = Field(default_factory=list)
    positions: list[PositionSample] = Field(default_factory=list)
    utility: list[UtilityArea] = Field(default_factory=list)
    bomb: list[BombEvent] = Field(default_factory=list)
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


Severity = Literal["hoch", "mittel", "niedrig"]


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


class RuleStatus(BaseModel):
    rule_id: str
    title: str
    evaluated: bool
    reason: str | None = None  # warum nicht auswertbar


class AnalysisResult(BaseModel):
    findings: list[Finding]
    rule_status: list[RuleStatus]
