"""Erkennt anhand der Spalten, welche Art von FM-Ansicht exportiert wurde."""

from __future__ import annotations

from .normalize import ATTRIBUTE_KEYS

KINDS = {
    "players": "Spieler",
    "staff": "Mitarbeiter",
    "clubs": "Vereine",
    "league_table": "Tabelle",
    "matches": "Spiele",
    "generic": "Sonstiges",
}

STAFF_KEYS = {
    "coaching_attacking", "coaching_defending", "coaching_fitness", "coaching_mental",
    "coaching_tactical", "coaching_technical", "judging_ability", "judging_potential", "motivating",
}


def classify(keys: set[str]) -> str:
    attrs = len(keys & ATTRIBUTE_KEYS)
    staff = len(keys & STAFF_KEYS)
    if staff >= 3 and staff > attrs:
        return "staff"
    if attrs >= 3 or ({"name", "position"} <= keys) or ({"name", "age"} <= keys and keys & {"value", "wage", "ca", "pa", "goals", "apps"}):
        return "players"
    if {"points", "played"} <= keys:
        return "league_table"
    if keys & {"opponent", "result"} and keys & {"date", "competition", "venue"}:
        return "matches"
    if "name" in keys and keys & {"stadium", "balance", "transfer_budget", "capacity", "reputation"}:
        return "clubs"
    return "generic"


def entity_key(kind: str, data: dict, row_index: int) -> str:
    """Stabiler Schlüssel, um dieselbe Entität über mehrere Importe zu verfolgen."""
    if data.get("uid"):
        return f"uid:{data['uid']}"
    name = data.get("name") or data.get("club")
    if kind == "matches":
        return "|".join(str(data.get(k) or "") for k in ("date", "competition", "opponent", "venue"))
    if kind == "league_table":
        return f"team:{data.get('club') or data.get('name') or row_index}"
    if not name:
        return f"row:{row_index}"
    if kind in ("players", "staff"):
        for extra in ("dob", "nationality", "club"):
            if data.get(extra):
                return f"{name}|{data[extra]}"
    return str(name)
