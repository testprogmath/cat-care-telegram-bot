import logging
import math
import os
from functools import lru_cache
from typing import Literal

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from . import texts
from .profiles import Profile

logger = logging.getLogger(__name__)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

SYSTEM_PROMPT_TEMPLATE = texts.prompt("system.md")
CONDENSE_PROMPT = texts.prompt("condense.md")


EventType = Literal[
    "medication", "water", "food", "refusal", "toilet", "state", "temperature", "weight",
    "breathing", "other",
]


class Event(BaseModel):
    type: EventType
    name: str | None = None
    dose: str | None = None
    water_ml: float | None = None
    kcal: float | None = None
    time: str | None = None
    date: str | None = None
    days_ago: int | None = None
    feeding: Literal["tube", "self"] | None = None
    amount_ml: float | None = None
    liquid: bool | None = None
    water_fraction: float | None = None
    temp_c: float | None = None
    weight_kg: float | None = None
    breaths_per_min: float | None = None
    asleep: bool | None = None
    stool_score: int | None = None
    description: str


class ParsedMessage(BaseModel):
    events: list[Event]


class ParseFailed(Exception):
    """Модель не ответила: сообщение нужно разобрать повторно позже."""

    def __init__(self, message: str, out_of_credit: bool = False):
        super().__init__(message)
        self.out_of_credit = out_of_credit


class ParseRefused(Exception):
    """Модель ответила, но без разбора: повтор не поможет, сообщение надо переписать."""


class CondensedStates(BaseModel):
    lines: list[str]


@lru_cache(maxsize=1)
def client() -> AsyncOpenAI:
    """The OpenAI client, built on first use.

    Built at import time it made every consumer of this package need an API key,
    including the read-only export, which never calls the model.
    """
    return AsyncOpenAI()


def drunk_ml(profile: Profile, seconds: float) -> float:
    return math.floor(seconds * profile.drinking_ml_per_second * 2 + 0.5) / 2


def system_prompt(profile: Profile) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        drinking_ml_per_second=profile.drinking_ml_per_second,
        drunk_in_10_seconds=drunk_ml(profile, 10),
        drunk_in_40_seconds=drunk_ml(profile, 40),
        subject=profile.subject,
        feeding_field=profile.tube.feeding_field if profile.tube else profile.feeding_field,
        feeding_products=profile.feeding_products,
        toilet_notes=profile.toilet_notes,
    )


async def parse_message(
    text: str,
    context: list[tuple[str, str]] | None,
    reply_to: str | None,
    report_shown: bool,
    profile: Profile,
) -> list[Event]:
    blocks = []
    if report_shown:
        blocks.append(
            "ВАЖНО: только что бот прислал в чат отчёт (сводку за сутки или недельный график), "
            "и чат обсуждает его цифры. Реплики про то, что кошка «какает», «ест сама», "
            "«стала лучше» — это комментарии к отчёту, а не наблюдения прямо сейчас."
        )
    if reply_to:
        blocks.append(f"Сообщение, на которое отвечают (события НЕ извлекать):\n{reply_to}")
    if context:
        ctx = "\n".join(
            f"[{sent_at[11:16]}] {msg}" for sent_at, msg in context if msg != reply_to
        )
        if ctx:
            blocks.append(f"Контекст (недавние сообщения, события НЕ извлекать):\n{ctx}")
    if blocks:
        blocks.append(f"Текущее сообщение (извлекать события только из него):\n{text}")
        user_content = "\n\n".join(blocks)
    else:
        user_content = text
    try:
        completion = await client().chat.completions.parse(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt(profile)},
                {"role": "user", "content": user_content},
            ],
            response_format=ParsedMessage,
        )
    except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
        logger.warning("Model gave no usable answer for %r: %s", text, exc)
        raise ParseRefused(str(exc)) from exc
    except openai.APIError as exc:
        logger.exception("Failed to parse message: %r", text)
        raise ParseFailed(str(exc), out_of_credit=exc.code == "insufficient_quota") from exc
    message = completion.choices[0].message
    if message.parsed is None:
        logger.warning("Model refused to parse %r: %s", text, message.refusal)
        raise ParseRefused(message.refusal or "no structured answer")
    return message.parsed.events


async def condense_states(items: list[tuple[str, str, str]]) -> list[str] | None:
    timeline = "\n".join(
        f"{time} [событие] {description}" if tag == "context" else f"{time} — {description}"
        for time, tag, description in items
    )
    try:
        completion = await client().chat.completions.parse(
            model=MODEL,
            messages=[
                {"role": "system", "content": CONDENSE_PROMPT},
                {"role": "user", "content": timeline},
            ],
            response_format=CondensedStates,
        )
    except Exception:
        logger.exception("Failed to condense state timeline")
        return None
    parsed = completion.choices[0].message.parsed
    return parsed.lines if parsed and parsed.lines else None
