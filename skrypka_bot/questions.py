"""Questions the bot asks the chat: how the stool looked, and how the animal is doing."""

import re
from datetime import datetime, timedelta

from . import classify
from .profiles import Profile

STOOL_SCALE = {
    1: "жидкий",
    2: "слизистый",
    3: "кашица",
    4: "норма",
    5: "твёрдый",
}

STOOL_QUESTION = (
    "Какой был стул по шкале 1-5? Ответьте на это сообщение цифрой.\n"
    "1 — жидкий, водянистый, впитывается в наполнитель\n"
    "2 — слизистый, как пудинг, бесформенная лужица\n"
    "3 — кашица: мягкий, наполнитель налипает почти весь\n"
    "4 — норма: оформленный, плотный, но влажный, наполнитель налипает немного\n"
    "5 — твёрдый, сухой, наполнитель не налипает"
)

_SCORE_DIGIT_RE = re.compile(r"(?<![\d.,])([1-5])(?![\d.,])")

_BARE_SCORE_RE = re.compile(r"^\s*[1-5](?:\s*/\s*5)?\s*[.!]?\s*$")

STOOL_ANSWER_WINDOW = timedelta(minutes=30)

_SCORE_WORDS = (
    (1, re.compile(r"жидк|водянист|понос", re.IGNORECASE)),
    (2, re.compile(r"слиз|пудинг|лужиц", re.IGNORECASE)),
    (3, re.compile(r"кашиц|мягк", re.IGNORECASE)),
    (4, re.compile(r"норм|оформлен|колбас", re.IGNORECASE)),
    (5, re.compile(r"тв[её]рд|сух|камуш|камен", re.IGNORECASE)),
)

PIECES_QUESTION = {
    "Felix Soup": "Кусочки из супчика ели? Ответьте на это сообщение: нет, половину или все.",
    "Felix Sensations": "Кусочки из Sensations ели? Ответьте на это сообщение: нет, немного или все.",
}

PIECES_ANSWER_WINDOW = timedelta(minutes=30)

_BARE_PIECES_RE = re.compile(
    r"^\s*(?:нет|не ел[аи]?|половин[уа]|немного|чуть|часть|вс[её]|целиком|полностью)"
    r"(?:\s+(?:съел[аи]?|ел[аи]?))?\s*[.!]?\s*$",
    re.IGNORECASE,
)

PIECES_LABEL = {"none": "без кусочков", "some": "с частью кусочков", "all": "с кусочками"}

_PIECES_WORDS = (
    ("none", re.compile(r"^\s*(?:нет|0)\b|не ел|не стал|только (?:бульон|подлив|соус)", re.IGNORECASE)),
    ("some", re.compile(r"немного|половин|чуть|часть|не вс[её]\b|^\s*1\b", re.IGNORECASE)),
    ("all", re.compile(r"(?<!не )\bвс[её]\b|^\s*2\b|целиком|полностью|обычн", re.IGNORECASE)),
)

CHECKIN_MARKER = "[бот спросил, как дела]"

CHECKIN_START_HOUR = 9

CHECKIN_END_HOUR = 22

CHECKIN_QUIET = timedelta(hours=3)

CHECKIN_INTERVAL = timedelta(minutes=30)


def score_from_reply(text: str) -> int | None:
    """The scale point an answer to the stool question names, or None when it names none or several."""
    digits = set(_SCORE_DIGIT_RE.findall(text))
    if digits:
        return int(digits.pop()) if len(digits) == 1 else None
    named = {score for score, pattern in _SCORE_WORDS if pattern.search(text)}
    return named.pop() if len(named) == 1 else None


def pieces_from_reply(text: str) -> str | None:
    """How many pieces an answer to the pieces question names, or None when it names none or several."""
    named = {pieces for pieces, pattern in _PIECES_WORDS if pattern.search(text)}
    return named.pop() if len(named) == 1 else None


def is_bare_pieces(text: str) -> bool:
    """The whole message is an answer to the pieces question: "нет", "половину", "всё съела"."""
    return bool(_BARE_PIECES_RE.match(text))


def pieces_confirmation(pieces: str, kcal: float) -> str:
    return f"Записал: {PIECES_LABEL[pieces]}, {kcal:g} ккал."


def is_bare_score(text: str) -> bool:
    """A message that is nothing but a point of the scale, which answers the question even unreplied."""
    return bool(_BARE_SCORE_RE.match(text))


def needs_stool_score(row) -> bool:
    return row["stool_score"] is None and classify.toilet_kind(row["description"]) == "stool"


STOOL_LEGEND = " · ".join(f"{score} {word}" for score, word in STOOL_SCALE.items())


def stool_tone(score: int) -> str:
    """How far a score is from the formed stool of 4: ok, warn for 3 and 5, bad for 1 and 2."""
    return "ok" if score == 4 else "warn" if score in (3, 5) else "bad"


def stool_label(score: int) -> str:
    return f"стул {score}/5, {STOOL_SCALE[score]}"


def stool_confirmation(score: int) -> str:
    return f"Записал: {stool_label(score)}."


def checkin_text(profile: Profile) -> str:
    return f"Как {profile.name}? Что сейчас делает?"


def checkin_due(now: datetime, last_message_at: datetime | None) -> bool:
    if not CHECKIN_START_HOUR <= now.hour < CHECKIN_END_HOUR:
        return False
    return last_message_at is None or now - last_message_at >= CHECKIN_QUIET
