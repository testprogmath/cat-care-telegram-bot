import os
from dataclasses import dataclass

from . import texts


@dataclass(frozen=True)
class Bands:
    unit: str
    target_low: float
    target_high: float
    alarm: float
    severe: float
    critical: float
    critical_note: str
    streak_days: int = 1


@dataclass(frozen=True)
class Tube:
    water_portion_ml: float
    max_feed_ml: float
    feeding_field: str


@dataclass(frozen=True)
class Profile:
    """One animal: how to parse for it, what to aim for, and what to call it outside.

    `key` is internal. It names the profile in configuration, in `chats.profile` and on
    the command line, and renaming it is an ordinary refactor.

    `subject_id` is not. It is the stable identifier this animal has in external data
    contracts, it is stored on every event, and downstream systems key their own records
    on it. Once CareDay records have been consumed anywhere, changing a subject_id is a
    migration on both sides, never a rename. The two may hold the same string; that is a
    coincidence of today's naming and not a rule.
    """

    key: str
    subject_id: str
    name: str
    name_en: str
    title_markers: tuple[str, ...]
    aliases: tuple[str, ...]
    self_label: str
    verb_received: str
    subject: str
    feeding_field: str
    feeding_products: str
    toilet_notes: str
    water_goal_ml: float
    kcal_goal: float
    kcal_bands: Bands | None = None
    water_bands: Bands | None = None
    tube: Tube | None = None
    drinking_ml_per_second: float = 0.45

    def pick(self, she: str, he: str) -> str:
        """The word that agrees with this animal: Скрипа is a she, Чипуня a he."""
        return she if self.self_label == "сама" else he


def _goal(key: str, field: str, default: float) -> float:
    return float(os.environ.get(f"{key.upper()}_{field}") or default)


_ROYAL_CANIN_SENSORY = texts.prompt("products/royal-canin-sensory.md")


_PURINA_ONE = texts.prompt("products/purina-one.md")


SKRIPA = Profile(
    key="skripa",
    subject_id="skripa",
    name="Скрипа",
    name_en="Skripa",
    title_markers=("скрип", "скрып"),
    aliases=("скрипа", "скрипка", "скрыпка"),
    self_label="сама",
    verb_received="получила",
    subject=texts.prompt("skripa/subject.md"),
    feeding_field=texts.prompt("skripa/feeding.md"),
    feeding_products=texts.prompt(
        "skripa/products.md", royal_canin_sensory=_ROYAL_CANIN_SENSORY, purina_one=_PURINA_ONE
    ),
    toilet_notes=texts.prompt("skripa/toilet.md"),
    water_goal_ml=_goal("skripa", "WATER_GOAL_ML", 340),
    drinking_ml_per_second=0.275,
    tube=Tube(
        water_portion_ml=25.0,
        max_feed_ml=float(os.environ.get("TUBE_MAX_SINGLE_ML") or 100),
        feeding_field=texts.prompt("skripa/feeding-tube.md"),
    ),
    kcal_goal=_goal("skripa", "KCAL_GOAL", 250),
    kcal_bands=Bands(
        unit="ккал",
        target_low=250,
        target_high=250,
        alarm=200,
        severe=150,
        critical=110,
        critical_note="веский аргумент за трубку",
        streak_days=2,
    ),
    water_bands=Bands(
        unit="мл",
        target_low=320,
        target_high=370,
        alarm=250,
        severe=200,
        critical=150,
        critical_note="не ждать следующего дня",
    ),
)


CHIPUNYA = Profile(
    key="chipunya",
    subject_id="chipunya",
    name="Чипуня",
    name_en="Chipunya",
    title_markers=("чипун", "чип"),
    aliases=("чипуня", "чип", "чипун"),
    self_label="сам",
    verb_received="получил",
    subject=texts.prompt("chipunya/subject.md"),
    feeding_field=texts.prompt("chipunya/feeding.md"),
    feeding_products=texts.prompt(
        "chipunya/products.md", royal_canin_sensory=_ROYAL_CANIN_SENSORY, purina_one=_PURINA_ONE
    ),
    toilet_notes="",
    water_goal_ml=_goal("chipunya", "WATER_GOAL_ML", 340),
    kcal_goal=_goal("chipunya", "KCAL_GOAL", 295),
)


PROFILES = {profile.key: profile for profile in (SKRIPA, CHIPUNYA)}


def get(key: str | None) -> Profile | None:
    return PROFILES.get(key or "")


def guess(title: str | None, taken: frozenset[str] = frozenset()) -> str | None:
    low = (title or "").lower()
    for profile in PROFILES.values():
        if profile.key not in taken and any(marker in low for marker in profile.title_markers):
            return profile.key
    return None


def resolve(name: str) -> Profile | None:
    low = name.strip().lower()
    for profile in PROFILES.values():
        if low == profile.key or low in profile.aliases:
            return profile
    return None


def names() -> str:
    return ", ".join(profile.name for profile in PROFILES.values())
