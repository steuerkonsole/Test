"""Normalisierung von FM-Spaltennamen und -Werten.

FM-Exporte enthalten formatierte Werte ("€12,5 Mio.", "1,85 m", "12-15" bei
nicht vollständig gescouteten Attributen ...). Dieses Modul wandelt sie in
saubere, maschinenlesbare Werte um und ordnet Spaltennamen (englische und
deutsche Oberfläche) kanonischen Schlüsseln zu. Unbekannte Spalten bleiben
unter einem "slug" des Originalnamens erhalten – es geht nichts verloren.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------
# Spalten-Aliasse
# --------------------------------------------------------------------------

# kanonischer Schlüssel -> (Typ, [Aliasse ...])
# Typen: text, int, float, money, wage, height, weight, attr, percent, date
COLUMNS: dict[str, tuple[str, list[str]]] = {
    # Identität / Basis
    "uid": ("text", ["UID", "Unique ID", "ID", "Eindeutige ID"]),
    "name": ("text", ["Name", "Player", "Spieler", "Staff", "Mitarbeiter"]),
    "club": ("text", ["Club", "Verein", "Team", "Mannschaft"]),
    "based": ("text", ["Based", "Ansässig"]),
    "division": ("text", ["Division", "Liga", "Wettbewerb", "Competition"]),
    "position": ("text", ["Position", "Positionen", "Best Pos", "Beste Position"]),
    "best_role": ("text", ["Best Role", "Beste Rolle"]),
    "age": ("int", ["Age", "Alter"]),
    "dob": ("date", ["DoB", "Date of Birth", "Geburtsdatum", "Geb.-Datum"]),
    "nationality": ("text", ["Nationality", "Nationalität", "Nation", "Nat."]),
    "second_nationality": ("text", ["2nd Nat", "Second Nationality", "Zweite Nationalität"]),
    "personality": ("text", ["Personality", "Persönlichkeit"]),
    "media_handling": ("text", ["Media Handling", "Medienverhalten"]),
    "preferred_foot": ("text", ["Preferred Foot", "Pref Foot", "Starker Fuß", "Bevorzugter Fuß"]),
    "left_foot": ("text", ["Left Foot", "Linker Fuß"]),
    "right_foot": ("text", ["Right Foot", "Rechter Fuß"]),
    "height": ("height", ["Height", "Größe"]),
    "weight": ("weight", ["Weight", "Gewicht"]),
    "inf": ("text", ["Inf", "Info"]),
    # Fähigkeiten
    "ca": ("int", ["CA", "Current Ability", "Aktuelle Fähigkeit", "Akt. Fähigkeit", "AF"]),
    "pa": ("int", ["PA", "Potential Ability", "Potenzielle Fähigkeit", "Pot. Fähigkeit", "PF"]),
    "ability": ("text", ["Ability", "Fähigkeit"]),
    "potential": ("text", ["Potential", "Potenzial"]),
    # Vertrag / Geld
    "value": ("money", ["Value", "Transfer Value", "Est. Value", "Wert", "Transferwert", "Marktwert", "Geschätzter Wert"]),
    "asking_price": ("money", ["Asking Price", "AP", "Ablöseforderung", "Forderung"]),
    "wage": ("wage", ["Wage", "Gehalt", "Lohn"]),
    "expires": ("date", ["Expires", "Contract Expires", "Vertrag bis", "Vertragsende", "Läuft aus"]),
    "release_clause": ("money", ["Min Fee Rls", "Release Clause", "Ausstiegsklausel"]),
    "transfer_status": ("text", ["Transfer Status", "Transferstatus"]),
    "loan_status": ("text", ["Loan Status", "Leihstatus"]),
    # Statistiken
    "apps": ("text", ["Apps", "Appearances", "Einsätze", "Spiele"]),
    "starts": ("int", ["Starts", "Startelf"]),
    "goals": ("int", ["Gls", "Goals", "Tore"]),
    "assists": ("int", ["Ast", "Assists", "Vorlagen"]),
    "avg_rating": ("float", ["Av Rat", "Avg Rating", "Average Rating", "Ø-Note", "Durchschnittsnote", "Note"]),
    "minutes": ("int", ["Mins", "Minutes", "Minuten"]),
    "player_of_match": ("int", ["PoM", "Player of the Match", "Spieler des Spiels"]),
    "xg": ("float", ["xG"]),
    "xa": ("float", ["xA"]),
    "pass_pct": ("percent", ["Pas %", "Pass %", "Passquote"]),
    "yellow": ("int", ["Yel", "Yellow Cards", "Gelbe Karten", "Gelb"]),
    "red": ("int", ["Red", "Red Cards", "Rote Karten", "Rot"]),
    "condition": ("percent", ["Con", "Condition", "Kondition", "Zustand"]),
    "match_sharpness": ("text", ["Match Sharpness", "Spielpraxis"]),
    "morale": ("text", ["Morale", "Moral"]),
    "injury": ("text", ["Injury", "Verletzung"]),
    # Vereine / Spiele
    "reputation": ("text", ["Reputation", "Ansehen", "Rep"]),
    "balance": ("money", ["Balance", "Kontostand"]),
    "transfer_budget": ("money", ["Transfer Budget", "Transferbudget"]),
    "wage_budget": ("wage", ["Wage Budget", "Gehaltsbudget"]),
    "stadium": ("text", ["Stadium", "Stadion"]),
    "capacity": ("int", ["Capacity", "Kapazität"]),
    "pos_table": ("int", ["Pos.", "Pl.", "Platz", "Rank"]),
    "played": ("int", ["Pld", "P", "Sp."]),
    "won": ("int", ["Won", "W", "S"]),
    "drawn": ("int", ["Drn", "D", "U"]),
    "lost": ("int", ["Lst", "L", "N"]),
    "goals_for": ("int", ["For", "GF", "Tore+"]),
    "goals_against": ("int", ["Ag", "Agst", "GA", "Tore-"]),
    "goal_diff": ("int", ["GD", "Tordiff.", "Diff."]),
    "points": ("int", ["Pts", "Punkte", "Pkt."]),
    "date": ("date", ["Date", "Datum"]),
    "competition": ("text", ["Comp", "Wettb."]),
    "venue": ("text", ["Venue", "Ort", "H/A"]),
    "opponent": ("text", ["Opposition", "Opponent", "Gegner"]),
    "result": ("text", ["Result", "Score", "Ergebnis"]),
    "attendance": ("int", ["Attendance", "Zuschauer"]),
    # Trainer-Attribute
    "coaching_attacking": ("attr", ["Att", "Attacking", "Angriff"]),
    "coaching_defending": ("attr", ["Def", "Defending", "Verteidigung"]),
    "coaching_fitness": ("attr", ["Fit", "Fitness"]),
    "coaching_mental": ("attr", ["Men", "Mental", "Mentales"]),
    "coaching_tactical": ("attr", ["Tac", "Tactical", "Taktik"]),
    "coaching_technical": ("attr", ["Tcn", "Technical", "Technik"]),
    "judging_ability": ("attr", ["JA", "Judging Ability", "Fähigkeit beurteilen"]),
    "judging_potential": ("attr", ["JP", "Judging Potential", "Potenzial beurteilen"]),
    "motivating": ("attr", ["Mot", "Motivating", "Motivieren"]),
}

# Spieler-Attribute (1–20). Englische Kürzel + Klartext + deutsche Namen.
PLAYER_ATTRIBUTES: dict[str, list[str]] = {
    # Technik
    "corners": ["Cor", "Corners", "Ecken", "Eck"],
    "crossing": ["Cro", "Crossing", "Flanken", "Fla."],
    "dribbling": ["Dri", "Dribbling"],
    "finishing": ["Fin", "Finishing", "Abschluss", "Abs"],
    "first_touch": ["Fir", "First Touch", "Ballannahme", "Bal."],
    "free_kicks": ["Fre", "Free Kick Taking", "Freistöße", "Frs"],
    "heading": ["Hea", "Heading", "Kopfball", "Kop"],
    "long_shots": ["Lon", "Long Shots", "Distanzschüsse", "Dis"],
    "long_throws": ["L Th", "Long Throws", "Weite Einwürfe", "Ein"],
    "marking": ["Mar", "Marking", "Manndeckung", "Man"],
    "passing": ["Pas", "Passing", "Passen", "Pas."],
    "penalty_taking": ["Pen", "Penalty Taking", "Elfmeter", "Elf"],
    "tackling": ["Tck", "Tackling", "Tacklings", "Tac."],
    "technique": ["Tec", "Technique", "Technik."],
    # Mental
    "aggression": ["Agg", "Aggression", "Aggressivität", "Agr"],
    "anticipation": ["Ant", "Anticipation", "Antizipation"],
    "bravery": ["Bra", "Bravery", "Mut"],
    "composure": ["Cmp", "Composure", "Nervenstärke", "Ner"],
    "concentration": ["Cnt", "Concentration", "Konzentration", "Kon"],
    "decisions": ["Dec", "Decisions", "Entscheidungen", "Ent"],
    "determination": ["Det", "Determination", "Entschlossenheit", "Ens"],
    "flair": ["Fla", "Flair", "Übersicht"],
    "leadership": ["Ldr", "Leadership", "Führungsqualitäten", "Füh"],
    "off_the_ball": ["OtB", "Off the Ball", "Ohne Ball", "OhB"],
    "positioning": ["Pos", "Positioning", "Stellungsspiel", "Ste"],
    "teamwork": ["Tea", "Teamwork", "Teamgeist", "Tea."],
    "vision": ["Vis", "Vision", "Kreativität", "Kre"],
    "work_rate": ["Wor", "Work Rate", "Einsatzfreude", "Esf"],
    # Physis
    "acceleration": ["Acc", "Acceleration", "Antritt", "Ant."],
    "agility": ["Agi", "Agility", "Beweglichkeit", "Bew"],
    "balance_attr": ["Bal", "Balance", "Balance."],
    "jumping_reach": ["Jum", "Jumping Reach", "Sprungkraft", "Spr"],
    "natural_fitness": ["Natural Fitness", "Grundfitness", "Gfi"],
    "pace": ["Pac", "Pace", "Schnelligkeit", "Sch"],
    "stamina": ["Sta", "Stamina", "Ausdauer", "Aus"],
    "strength": ["Str", "Strength", "Kraft", "Kra"],
    # Torwart
    "aerial_reach": ["Aer", "Aerial Reach", "Strafraumbeherrschung"],
    "command_of_area": ["Cmd", "Command of Area", "Herauslaufen"],
    "communication": ["Com", "Communication", "Kommunikation"],
    "eccentricity": ["Ecc", "Eccentricity", "Exzentrik"],
    "handling": ["Han", "Handling", "Fangsicherheit"],
    "kicking": ["Kic", "Kicking", "Abschlag"],
    "one_on_ones": ["1v1", "One on Ones", "Eins gegen Eins"],
    "punching": ["Pun", "Punching (Tendency)", "Faustabwehr"],
    "reflexes": ["Ref", "Reflexes", "Reflexe"],
    "rushing_out": ["TRO", "Rushing Out (Tendency)", "Herauslaufen (Tendenz)"],
    "throwing": ["Thr", "Throwing", "Abwurf"],
}

# Mehrdeutige Kürzel: Entscheidung anhand des Wertes.
# "Nat" = Nationalität (Text) oder Natürliche Fitness (1-20)
AMBIGUOUS: dict[str, tuple[str, str]] = {
    "nat": ("nationality", "natural_fitness"),
}

ATTRIBUTE_KEYS = set(PLAYER_ATTRIBUTES)


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "col"


_ALIAS: dict[str, tuple[str, str]] = {}
for _canon, (_typ, _aliases) in COLUMNS.items():
    for _a in _aliases:
        _ALIAS.setdefault(_key(_a), (_canon, _typ))
for _canon, _aliases in PLAYER_ATTRIBUTES.items():
    for _a in _aliases:
        _ALIAS.setdefault(_key(_a), (_canon, "attr"))


def resolve_header(header: str, value: str = "") -> tuple[str, str]:
    """Liefert (kanonischer Schlüssel, Typ) für eine Spaltenüberschrift."""
    k = _key(header)
    if k in AMBIGUOUS:
        text_key, attr_key = AMBIGUOUS[k]
        if parse_attr(value) is not None:
            return attr_key, "attr"
        return text_key, "text"
    if k in _ALIAS:
        return _ALIAS[k]
    return slugify(header), "auto"


# --------------------------------------------------------------------------
# Wert-Parser
# --------------------------------------------------------------------------

_EMPTY = {"", "-", "--", "—", "n/a", "na", "none", "keine", "unknown", "unbekannt", "?"}


def is_empty(v: str) -> bool:
    return v.strip().lower() in _EMPTY


def parse_number(s: str) -> float | None:
    """Parst Zahlen in englischer (1,234.5) und deutscher (1.234,5) Notation."""
    s = s.strip().replace("\xa0", "").replace(" ", "").replace("'", "")
    m = re.search(r"-?\d[\d.,]*", s)
    if not m:
        return None
    num = m.group(0).rstrip(".,")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        parts = num.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            num = num.replace(",", ".")
        else:
            num = num.replace(",", "")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    elif num.count(".") == 1:
        int_part, frac = num.split(".")
        # deutsches Tausendertrennzeichen: "81.365", "25.000"
        if len(frac) == 3 and int_part.lstrip("-") not in ("", "0"):
            num = num.replace(".", "")
    try:
        return float(num)
    except ValueError:
        return None


def parse_int(s: str) -> int | None:
    if is_empty(s):
        return None
    n = parse_number(s)
    return int(round(n)) if n is not None else None


def parse_float(s: str) -> float | None:
    if is_empty(s):
        return None
    return parse_number(s)


def parse_percent(s: str) -> float | None:
    return parse_float(s.replace("%", ""))


def parse_attr(s: str) -> int | float | None:
    """Attribut 1–20, auch Bereiche ("12-15") bei verdeckten Werten → Mittelwert."""
    s = s.strip()
    m = re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= 20 and 1 <= hi <= 20:
            return (lo + hi) / 2
        return None
    if re.fullmatch(r"\d{1,2}", s):
        v = int(s)
        return v if 0 <= v <= 20 else None
    return None


_CURRENCY = {"€": "EUR", "£": "GBP", "$": "USD", "eur": "EUR", "gbp": "GBP", "usd": "USD", "chf": "CHF", "¥": "JPY"}

_MULT = [
    (r"(bn|bio\.?|mrd\.?|billion|milliarden?)(?![a-z])", 1e9),
    (r"(m|mio\.?|million(en)?)(?![a-z])", 1e6),
    (r"(k|tsd\.?|tausend|t)(?![a-z])", 1e3),
]


def _single_money(s: str) -> float | None:
    s = s.strip()
    if not re.search(r"\d", s):
        return None
    n = parse_number(s)
    if n is None:
        return None
    low = s.lower()
    tail = re.sub(r"^[^\d]*-?\d[\d.,\s]*", "", low)
    tail = tail.replace("€", "").replace("£", "").replace("$", "").strip()
    for pat, mult in _MULT:
        if re.match(pat, tail):
            return n * mult
    return n


def detect_currency(s: str) -> str | None:
    low = s.lower()
    for sym, code in _CURRENCY.items():
        if sym in low:
            return code
    return None


def parse_money(s: str) -> dict | None:
    """'€1,5 Mio. - €3 Mio.' -> {'min':1.5e6,'max':3e6,'value':2.25e6,'currency':'EUR'}"""
    if is_empty(s):
        return None
    cur = detect_currency(s)
    parts = re.split(r"\s+[-–]\s+|[-–](?=\s*[€£$])|\s+(?:to|bis)\s+", s)
    vals = [v for v in (_single_money(p) for p in parts) if v is not None]
    if not vals:
        return {"text": s.strip(), "currency": cur}
    lo, hi = min(vals), max(vals)
    return {"value": (lo + hi) / 2, "min": lo, "max": hi, "currency": cur}


_PERIOD = [
    (r"(p/w|\bpw\b|per week|/w\b|\bp\.\s?w\.?|pro woche|/woche|wöchentlich)", 1.0, "week"),
    (r"(p/m|\bpm\b|per month|/m\b|\bp\.\s?m\.?|pro monat|/monat|monatlich)", 12 / 52, "month"),
    (r"(p/a|\bpa\b|per (annum|year)|/y\b|\bp\.\s?a\.?|pro jahr|/jahr|jährlich)", 1 / 52, "year"),
]


def parse_wage(s: str) -> dict | None:
    """Gehalt → wöchentlicher Betrag (FM-Standard)."""
    m = parse_money(s)
    if not m or "value" not in m:
        return m
    low = s.lower()
    factor, period = 1.0, "week"
    for pat, f, name in _PERIOD:
        if re.search(pat, low):
            factor, period = f, name
            break
    m.update({
        "per_week": round(m["value"] * factor, 2),
        "per_year": round(m["value"] * factor * 52, 2),
        "period": period,
    })
    return m


def parse_height(s: str) -> int | None:
    """→ Zentimeter."""
    if is_empty(s):
        return None
    m = re.search(r"(\d+)\s*'\s*(\d+)?", s)
    if m:
        ft, inch = int(m.group(1)), int(m.group(2) or 0)
        return round((ft * 12 + inch) * 2.54)
    n = parse_number(s)
    if n is None:
        return None
    if n < 3:  # Meter
        return round(n * 100)
    return round(n)


def parse_weight(s: str) -> int | None:
    """→ Kilogramm."""
    if is_empty(s):
        return None
    n = parse_number(s)
    if n is None:
        return None
    if re.search(r"lb|pfund|st\b", s.lower()):
        if re.search(r"st\b", s.lower()) and n < 40:
            return round(n * 6.35029)
        return round(n * 0.453592)
    return round(n)


def parse_auto(s: str):
    """Für unbekannte Spalten: Zahl wenn eindeutig, sonst Text."""
    if is_empty(s):
        return None
    st = s.strip()
    a = parse_attr(st)
    if a is not None:
        return a
    if re.fullmatch(r"-?\d+", st):
        return int(st)
    if re.fullmatch(r"-?\d+[.,]\d+", st):
        return float(st.replace(",", "."))
    if re.fullmatch(r"-?\d+(\.\d+)?\s*%", st):
        return float(st.rstrip("% "))
    if detect_currency(st) and re.search(r"\d", st):
        return parse_money(st)
    return st


PARSERS = {
    "text": lambda s: None if is_empty(s) else s.strip(),
    "date": lambda s: None if is_empty(s) else s.strip(),
    "int": parse_int,
    "float": parse_float,
    "percent": parse_percent,
    "attr": parse_attr,
    "money": parse_money,
    "wage": parse_wage,
    "height": parse_height,
    "weight": parse_weight,
    "auto": parse_auto,
}


def normalize_row(pairs: list[tuple[str, str]]) -> dict:
    """Wandelt eine Zeile (Header, Wert)-Paare in ein normalisiertes dict."""
    out: dict = {}
    for header, value in pairs:
        if not header.strip():
            continue
        key, typ = resolve_header(header, value)
        parsed = PARSERS[typ](value)
        if typ == "text" and key == "name" and parsed:
            # FM hängt teils Zusätze an ("Max Muster - Verletzt")
            parsed = parsed.strip()
        base, i = key, 2
        while key in out and out[key] not in (None, parsed):
            key = f"{base}_{i}"
            i += 1
        if parsed is not None or key not in out:
            out[key] = parsed
    return out
