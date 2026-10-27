import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from . import classify, figures

UNNAMED_DRY = "сухой, неизвестно какой"
UNNAMED_WET = "жидкий, неизвестно какой"
UNNAMED_SNACK = "снек, неизвестно какой"
UNNAMED = "неизвестно"

_PURINA = r"purina|пурина|путина"
_PRODUCTS: list[tuple[str, str, str | None]] = [
    ("Felix Sensations", r"felix|феликс", r"sensation|сенсейшн|сенсэйшн"),
    ("Felix Heerlijke Reepjes", r"reepjes|streepjes|heerlijke", None),
    ("Felix Sauce", r"felix|феликс", r"sauce|соус|gravy|подлив"),
    ("Felix Soup", r"felix|феликс", None),
    ("Gourmet soup", r"gourmet|гурме", None),
    ("Purina One Junior, wet", _PURINA, r"junior|kitten|юниор|котят"),
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
    ("RC Indoor, dry", r"indoor|индор", None),
    ("RC Hair & Skin", r"hair\s*&?\s*skin|skin\s*&?\s*hair|хэир", None),
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


def is_meal(row: sqlite3.Row) -> bool:
    """Food with calories in it, unlike a soup drunk without its pieces or a sauce."""
    if row["type"] != "food":
        return False
    if row["pieces"]:
        return row["pieces"] != "none"
    if product(row["name"] or row["description"] or "", True) == "Felix Sauce":
        return False
    return not classify.is_broth_only(row["description"])


GRAVY_PER_GRAM = {"Felix Heerlijke Reepjes": (0.30, 0.9), "Felix Sensations": (0.40, 0.88)}


def fill_gravy(event) -> None:
    """Calories for gravy of a product whose gravy has an estimate, when the model left them out."""
    if event.kcal or not event.amount_ml:
        return
    rates = GRAVY_PER_GRAM.get(product(f"{event.name or ''} {event.description or ''}", True))
    if rates:
        kcal_per_g, water_fraction = rates
        event.kcal = round(event.amount_ml * kcal_per_g, 1)
        event.water_fraction = water_fraction


PIECES = ("none", "some", "all")

_SOUP_PER_GRAM = {"none": (0.425, 0.95), "some": (0.464, 0.95), "all": (0.479, 0.875)}

_SENSATIONS_SHARE = {"none": 0.0, "some": 0.10, "all": 0.294}


def pieces_product(row) -> str | None:
    """Felix Soup or Felix Sensations, the foods whose figures depend on how many pieces were eaten."""
    if not row["liquid"]:
        return None
    found = product(f"{row['name'] or ''} {row['description'] or ''}", True)
    return found if found in ("Felix Soup", "Felix Sensations") else None


def with_pieces(food: str, grams: float, pieces: str) -> tuple[float, float]:
    """Calories and water fraction of so many grams of the food, eaten with none, some or all of its pieces."""
    if food == "Felix Soup":
        per_gram, water_fraction = _SOUP_PER_GRAM[pieces]
    else:
        share = _SENSATIONS_SHARE[pieces]
        per_gram, water_fraction = 0.40 + 1.32 * share, round(0.88 - 0.13 * share, 3)
    return round(grams * per_gram, 1), water_fraction


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
            if figures.is_given(row):
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
