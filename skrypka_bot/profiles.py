import os
import re
from dataclasses import dataclass, replace

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
    name_genitive: str
    name_en: str
    title_markers: tuple[str, ...]
    aliases: tuple[str, ...]
    mention: re.Pattern[str]
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

    def with_goals(self, kcal: float | None = None, water_ml: float | None = None) -> Profile:
        """This animal with the goals a chat set; a band whose target is the goal moves with it."""
        changed = self
        if kcal is not None:
            changed = replace(changed, kcal_goal=kcal,
                              kcal_bands=_retarget(changed.kcal_bands, changed.kcal_goal, kcal))
        if water_ml is not None:
            changed = replace(changed, water_goal_ml=water_ml,
                              water_bands=_retarget(changed.water_bands, changed.water_goal_ml, water_ml))
        return changed

    def pick(self, she: str, he: str) -> str:
        """The word that agrees with this animal: Скрипа is a she, Чипуня a he."""
        return she if self.self_label == "сама" else he


def _retarget(bands: Bands | None, goal: float, new_goal: float) -> Bands | None:
    if bands is None or not bands.target_low == bands.target_high == goal:
        return bands
    return replace(bands, target_low=new_goal, target_high=new_goal)


def _goal(key: str, field: str, default: float) -> float:
    return float(os.environ.get(f"{key.upper()}_{field}") or default)


_ROYAL_CANIN_SENSORY = texts.prompt("products/royal-canin-sensory.md")


_PURINA_ONE = texts.prompt("products/purina-one.md")


_ROYAL_CANIN_LIGHT_WEIGHT = texts.prompt("products/royal-canin-light-weight.md")


_ROYAL_CANIN_INSTINCTIVE = texts.prompt("products/royal-canin-instinctive.md")


_SKRIPA_KCAL_GOAL = _goal("skripa", "KCAL_GOAL", 225)


SKRIPA = Profile(
    key="skripa",
    subject_id="skripa",
    name="Скрипа",
    name_genitive="Скрипы",
    name_en="Skripa",
    title_markers=("скрип", "скрып"),
    aliases=("скрипа", "скрипка", "скрыпка"),
    mention=re.compile(r"\bскр[иы]пк?[аеуыо]\w*", re.IGNORECASE),
    self_label="сама",
    verb_received="получила",
    subject=texts.prompt("skripa/subject.md"),
    feeding_field=texts.prompt("skripa/feeding.md"),
    feeding_products=texts.prompt(
        "skripa/products.md", royal_canin_sensory=_ROYAL_CANIN_SENSORY,
        royal_canin_light_weight=_ROYAL_CANIN_LIGHT_WEIGHT,
        royal_canin_instinctive=_ROYAL_CANIN_INSTINCTIVE, purina_one=_PURINA_ONE
    ),
    toilet_notes=texts.prompt("skripa/toilet.md"),
    water_goal_ml=_goal("skripa", "WATER_GOAL_ML", 340),
    drinking_ml_per_second=0.19,
    tube=Tube(
        water_portion_ml=25.0,
        max_feed_ml=float(os.environ.get("TUBE_MAX_SINGLE_ML") or 100),
        feeding_field=texts.prompt("skripa/feeding-tube.md"),
    ),
    kcal_goal=_SKRIPA_KCAL_GOAL,
    kcal_bands=Bands(
        unit="ккал",
        target_low=_SKRIPA_KCAL_GOAL,
        target_high=_SKRIPA_KCAL_GOAL,
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
    name_genitive="Чипуни",
    name_en="Chipunya",
    title_markers=("чипун", "чип"),
    aliases=("чипуня", "чип", "чипун"),
    mention=re.compile(r"\bчипун\w*", re.IGNORECASE),
    self_label="сам",
    verb_received="получил",
    subject=texts.prompt("chipunya/subject.md"),
    feeding_field=texts.prompt("chipunya/feeding.md"),
    feeding_products=texts.prompt(
        "chipunya/products.md", royal_canin_sensory=_ROYAL_CANIN_SENSORY,
        royal_canin_light_weight=_ROYAL_CANIN_LIGHT_WEIGHT,
        royal_canin_instinctive=_ROYAL_CANIN_INSTINCTIVE, purina_one=_PURINA_ONE
    ),
    toilet_notes="",
    water_goal_ml=_goal("chipunya", "WATER_GOAL_ML", 340),
    kcal_goal=_goal("chipunya", "KCAL_GOAL", 270),
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


def named_instead(profile: Profile, text: str) -> Profile | None:
    """Another animal the text names, when it does not name this one."""
    if profile.mention.search(text):
        return None
    return next(
        (other for other in PROFILES.values() if other.key != profile.key and other.mention.search(text)),
        None,
    )


def names() -> str:
    return ", ".join(profile.name for profile in PROFILES.values())
