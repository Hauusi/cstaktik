"""Erinnerung vor dem Match: eine Push-Nachricht kurz vor der Uhrzeit, zu der ihr meist spielt.

Warum: Gewohnheiten entstehen, wenn dieselbe Handlung immer im selben Moment kommt (gleicher Auslöser). Bis sie von
selbst läuft, dauert es meist Wochen (Lally u. a. 2010, stark schwankend). Deshalb ein fester Auslöser: die
Spielzeit, die du einstellst. Nur eine Nachricht am Tag, nicht, wenn das Warm-up schon erledigt ist.

Gespeichert in den Server-Settings (accounts): ``reminder:<user>`` = "HH:MM", ``reminder_sent:<user>`` = Datum.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

LEAD_MIN = 15  # so viele Minuten vor der Spielzeit
WINDOW_MIN = 15  # bis zur Spielzeit selbst wird noch gesendet (Server-Neustart, Schleife verpasst eine Minute)


def get(user: str) -> str | None:
    from cstaktik import accounts

    v = accounts.get_setting(f"reminder:{user}")
    return v if v and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else None


def set_time(user: str, value: str | None) -> None:
    from cstaktik import accounts

    v = (value or "").strip()
    if v and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError("Uhrzeit bitte als HH:MM, z. B. 20:00.")
    accounts.set_setting(f"reminder:{user}", v or None)


def _local_now() -> datetime:
    from cstaktik.coaching import now_local

    return datetime.fromisoformat(now_local()[:19])


def message(sid: str | None) -> dict:
    """Text der Erinnerung: die Abmachung und der Weg ins Warm-up."""
    from cstaktik import course_texts, drills

    plan = drills.current_plan(sid) if sid else None
    body = (f"Deine Abmachung: {plan['text']}" if plan and plan.get("text") else
            "Zwei Minuten Warm-up: Plan, Kopfkino, Szenen.")
    cue = course_texts.CUEWORDS.get((plan or {}).get("lesson") or "")
    if cue:
        body += f" Schlüsselwort: „{cue}“."
    return {"title": "Gleich geht's los. Kurz aufwärmen?", "body": body, "url": "/warmup"}


def check(now: datetime | None = None, post=None) -> list[str]:
    """Allen Nutzern mit Spielzeit die Erinnerung schicken, wenn es Zeit ist. Rückgabe: benachrichtigte Nutzer."""
    from cstaktik import accounts, drills, notify

    now = now or _local_now()
    sent = []
    for user in accounts.list_users():
        t = get(user)
        if not t:
            continue
        hh, mm = (int(x) for x in t.split(":"))
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (start - timedelta(minutes=LEAD_MIN) <= now <= start + timedelta(minutes=WINDOW_MIN - LEAD_MIN)):
            continue
        day = now.date().isoformat()
        if accounts.get_setting(f"reminder_sent:{user}") == day:
            continue
        sid = (accounts.get_steam(user) or {}).get("steamid")
        if sid and any(w[:10] == day for w in drills.load(sid).get("warmups") or []):
            accounts.set_setting(f"reminder_sent:{user}", day)  # heute schon aufgewärmt
            continue
        if not notify.subs(user):
            continue
        accounts.set_setting(f"reminder_sent:{user}", day)
        if notify.send_user(user, message(sid), post):
            sent.append(user)
    return sent


WEEKLY_DAY, WEEKLY_HOUR = 6, 19  # sonntags ab 19 Uhr (deutsche Zeit)


def weekly_check(now: datetime | None = None, post=None, hist: list[dict] | None = None) -> list[str]:
    """Sonntagabend den Wochenrückblick schicken, einmal pro Kalenderwoche und nur nach einer Woche mit Match."""
    from cstaktik import accounts, coaching, history, notify, pipeline, weekly

    now = now or _local_now()
    if now.weekday() != WEEKLY_DAY or now.hour < WEEKLY_HOUR:
        return []
    wk = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    sent = []
    if hist is None:
        hist = history.load_all(pipeline.HISTORY_DIR) if pipeline.HISTORY_DIR.exists() else []
    players = coaching.load(pipeline.COACHING_FILE).get("players", {})
    for user in accounts.list_users():
        if accounts.get_setting(f"weekly_sent:{user}") == wk or not notify.subs(user):
            continue
        sid = (accounts.get_steam(user) or {}).get("steamid")
        if not sid:
            continue
        r = weekly.build(hist, sid, now, players.get(sid))
        if not r or not r["matches"]:
            continue
        accounts.set_setting(f"weekly_sent:{user}", wk)
        if notify.send_user(user, weekly.message(r), post):
            sent.append(user)
    return sent
