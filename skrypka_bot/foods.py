import re
import sqlite3
from dataclasses import dataclass
from datetime import date

UNNAMED_DRY = "сухой корм, без названия"
UNNAMED_WET = "жидкий корм, без названия"
UNNAMED_SNACK = "снек, без названия"
UNNAMED = "корм не назван"

_PURINA = r"purina|пурина|путина"
_PRODUCTS: list[tuple[str, str, str | None]] = [
    ("Felix Sauce", r"felix|феликс", r"sauce|соус|gravy|подлив"),
    ("Felix Soup", r"felix|феликс", None),
    ("Gourmet soup", r"gourmet|гурме", None),
    ("Purina One salmon", _PURINA, r"zalm|лосос|залм|salmon"),
    ("Purina One chicken", _PURINA, r"кур|chicken"),
    ("Purina One beef", _PURINA, None),
    ("Hill's i/d, dry", r"hill|хилс|\bi/d\b|айди", None),
    ("Monge", r"monge|монж", None),
    ("Vitakraft", r"vitakraft|витакрафт|drink|дринк|liquid snack", None),
    ("Schesir", r"schesir|шезир", None),
    ("GranataPet", r"granata|granaat", None),
    ("Specific", r"specific", None),
    ("Trovet", r"trovet", None),
    ("Churu", r"churu|чуру", None),
    ("RC Sensible, dry", r"sensible", None),
    ("RC Recovery Liquid", r"recovery", None),
    ("RC Kitten", r"kitten|котят|котяч", None),
    ("RC Gastrointestinal", r"gastro", None),
    ("RC Sensory Smell", r"smell|смэлл|смелл", None),
    ("RC Sensory Taste", r"taste|тейст", None),
    ("RC Sensory Feel", r"\bfeel\b", None),
    ("RC Sensory", r"sensory|сенсори", None),
    ("RC Sensitivity Control", r"sensitiv|сенситив", None),
    ("RC Sterilised", r"sterili|стерилиз", None),
    ("RC Urinary", r"urinary|уринари", None),
    ("RC Renal", r"renal|ренал", None),
]


def product(text: str, liquid: bool | None = None, named: bool = True) -> str:
    """One canonical product for a recorded food or refusal name.

    liquid is known for a feeding and unknown (None) for a refusal. A text that is not a
    product name, such as a free-form description, falls back to UNNAMED when nothing matches.
    """
    t = text.lower()
    if ("digestive" in t or "дайджест" in t) and not re.search(r"hill|хилс|i/d", t):
        wet = liquid if liquid is not None else bool(re.search(r"royal canin|роял|жидк", t))
        return "RC Digestive Care, wet" if wet else "Hill's i/d, dry"
    for name, pattern, refine in _PRODUCTS:
        if re.search(pattern, t) and (refine is None or re.search(refine, t)):
            return name
    if re.search(r"сухар|сухой|сухого", t):
        return UNNAMED_DRY
    if re.search(r"жидк|\bжк\b|влажн", t):
        return UNNAMED_WET
    if re.search(r"снек|снэк|snack", t):
        return UNNAMED_SNACK
    return text.strip() if named and text.strip() else UNNAMED


def refused_products(row: sqlite3.Row) -> list[str]:
    name = row["name"]
    if not name:
        return [product(row["description"] or "", named=False)]
    return [product(part) for part in name.split(",") if part.strip()]


@dataclass
class FoodLine:
    product: str
    eaten: int = 0
    kcal: float = 0.0
    last_eaten: date | None = None
    refused: int = 0
    last_refused: date | None = None

    @property
    def last_seen(self) -> date:
        return max(d for d in (self.last_eaten, self.last_refused) if d is not None)


@dataclass
class TubeLine:
    feeds: int = 0
    kcal: float = 0.0


def report(rows: list[sqlite3.Row]) -> tuple[list[FoodLine], TubeLine]:
    lines: dict[str, FoodLine] = {}
    tube = TubeLine()
    for row in rows:
        day = date.fromisoformat(row["day"])
        if row["type"] == "food":
            if row["feeding"] == "tube":
                tube.feeds += 1
                tube.kcal += row["kcal"] or 0
                continue
            key = product(row["name"] or row["description"] or "", bool(row["liquid"]), bool(row["name"]))
            line = lines.setdefault(key, FoodLine(key))
            line.eaten += 1
            line.kcal += row["kcal"] or 0
            line.last_eaten = max(filter(None, (line.last_eaten, day)))
        elif row["type"] == "refusal":
            for key in refused_products(row):
                line = lines.setdefault(key, FoodLine(key))
                line.refused += 1
                line.last_refused = max(filter(None, (line.last_refused, day)))
    ordered = sorted(lines.values(), key=lambda line: (line.last_seen, line.eaten), reverse=True)
    return ordered, tube
