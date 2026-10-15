"""'Mit Steam verbinden' über Steam OpenID 2.0 (offizieller Steam-Login, kein API-Schlüssel nötig).

Ablauf: Weiterleitung zu steamcommunity.com, dort meldet man sich bei Steam an; Steam schickt die SteamID zurück.
Die Antwort wird direkt bei Steam gegengeprüft (check_authentication), sonst könnte sie jeder fälschen.
Ein zufälliger Wert im Rücksprung (state) verhindert, dass jemand fremde Logins unterschiebt.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

OPENID = "https://steamcommunity.com/openid/login"
NS = "http://specs.openid.net/auth/2.0"
ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(7656\d{13})$")


def login_url(return_to: str, realm: str) -> str:
    params = {"openid.ns": NS, "openid.mode": "checkid_setup", "openid.return_to": return_to,
              "openid.realm": realm, "openid.identity": f"{NS}/identifier_select",
              "openid.claimed_id": f"{NS}/identifier_select"}
    return f"{OPENID}?{urllib.parse.urlencode(params)}"


def _post(data: dict, timeout: float = 15) -> str:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(OPENID, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - feste https-Quelle
        return r.read(10_000).decode("utf-8", "ignore")


def verify(params: dict, expected_return_to: str, post=_post) -> str | None:
    """SteamID64 aus einer gültigen Steam-Antwort, sonst None."""
    if params.get("openid.mode") != "id_res" or params.get("openid.return_to") != expected_return_to:
        return None
    m = ID_RE.match(params.get("openid.claimed_id", ""))
    if not m:
        return None
    check = {k: v for k, v in params.items() if k.startswith("openid.")}
    check["openid.mode"] = "check_authentication"
    try:
        answer = post(check)
    except OSError:
        return None
    return m.group(1) if "is_valid:true" in answer else None
