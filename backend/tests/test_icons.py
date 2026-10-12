import pytest

from cstaktik import icons


@pytest.mark.parametrize("name,icon", [
    ("AK-47", "ak47"), ("weapon_ak47", "ak47"), ("M4A1-S", "m4a1_silencer"), ("weapon_m4a1_silencer", "m4a1_silencer"),
    ("M4A4", "m4a1"), ("weapon_m4a1", "m4a1"), ("Glock-18", "glock"), ("USP-S", "usp_silencer"), ("P2000", "hkp2000"),
    ("Desert Eagle", "deagle"), ("CZ75-Auto", "cz75a"), ("Dual Berettas", "elite"), ("R8 Revolver", "revolver"),
    ("PP-Bizon", "bizon"), ("SG 553", "sg556"), ("Galil AR", "galilar"), ("Zeus x27", "taser"),
    ("Karambit", "knife"), ("weapon_knife_t", "knife"), ("High Explosive Grenade", "hegrenade"),
    ("Incendiary Grenade", "incgrenade"), ("C4 Explosive", "c4"), ("Smoke Grenade", "smokegrenade"),
])
def test_icon_mapping(name, icon):
    assert icons.icon_for(name) == icon and icon in icons.ALL_ICONS


def test_unknown_weapon_has_no_icon():
    assert icons.icon_for("Irgendwas") is None and icons.icon_for(None) is None


def test_fetch_validates_svg(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "_get", lambda url, timeout: b'<?xml version="1.0"?><svg></svg>')
    assert icons.fetch_icon("ak47", tmp_path).exists()
    monkeypatch.setattr(icons, "_get", lambda url, timeout: b"<html>nope</html>")
    with pytest.raises(ValueError):
        icons.fetch_icon("awp", tmp_path)
    with pytest.raises(ValueError):
        icons.fetch_icon("../x", tmp_path)
    assert icons.ensure_icons({"awp"}, tmp_path) == ["awp"]
