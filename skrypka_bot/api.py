import json
import os
import secrets
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from . import db, profiles
from .parser import EventType

MIN_TOKEN_LENGTH = 32

_bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = os.environ.get("API_TOKEN", "")
    presented = credentials.credentials if credentials else ""
    if not expected or not secrets.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )


app = FastAPI(
    title="cat-care admin",
    dependencies=[Depends(require_token)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))


def today() -> date:
    return db.care_day(datetime.now(timezone()))


def in_care_zone(moment: datetime) -> datetime:
    zone = timezone()
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment.astimezone(zone)


class EventSummary(BaseModel):
    id: int
    occurred_at: str
    type: str
    description: str | None
    kcal: float | None
    water_ml: float | None
    amount_ml: float | None


class Event(EventSummary):
    chat_id: int
    message_id: int | None
    day: str
    subject: str | None
    name: str | None
    dose: str | None
    feeding: str | None
    temp_c: float | None
    liquid: bool | None
    water_fraction: float | None
    weight_kg: float | None = None
    breaths: float | None = None
    asleep: bool | None = None
    message_text: str | None


class EventPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType | None = None
    description: str | None = None
    kcal: float | None = None
    water_ml: float | None = None
    amount_ml: float | None = None
    water_fraction: float | None = None
    name: str | None = None
    dose: str | None = None
    liquid: bool | None = None
    feeding: str | None = None
    weight_kg: float | None = None
    breaths: float | None = None
    asleep: bool | None = None
    occurred_at: datetime | None = None


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    type: EventType
    occurred_at: datetime
    description: str
    name: str | None = None
    dose: str | None = None
    kcal: float | None = None
    water_ml: float | None = None
    amount_ml: float | None = None
    water_fraction: float | None = None
    liquid: bool | None = None
    feeding: str | None = None
    weight_kg: float | None = None
    breaths: float | None = None
    asleep: bool | None = None


class Edit(BaseModel):
    edited_at: str
    action: str
    before: dict
    after: dict | None


class Chat(BaseModel):
    chat_id: int
    title: str | None
    profile: str | None


class ChatPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str | None


def _not_found(event_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"event {event_id} not found")


@app.get("/events", response_model=list[EventSummary])
def list_events(
    subject: str | None = None,
    day: date | None = None,
    event_type: Annotated[str | None, Query(alias="type")] = None,
) -> list[EventSummary]:
    rows = db.list_events(day or today(), subject, event_type)
    return [EventSummary(**dict(row)) for row in rows]


@app.get("/events/{event_id}", response_model=Event)
def get_event(event_id: int) -> Event:
    row = db.event_by_id(event_id)
    if row is None:
        raise _not_found(event_id)
    return Event(**dict(row))


@app.post("/events", response_model=Event, status_code=201)
def create_event(event: EventCreate) -> Event:
    chat_id = db.chat_for_subject(event.subject)
    if chat_id is None:
        raise HTTPException(status_code=404, detail=f"no chat keeps the diary of {event.subject}")
    fields = event.model_dump(exclude={"subject"}, exclude_none=True)
    moment = in_care_zone(fields["occurred_at"])
    fields["occurred_at"] = moment.isoformat()
    fields["day"] = db.care_day(moment).isoformat()
    if "liquid" in fields:
        fields["liquid"] = 1 if fields["liquid"] else None
    if "asleep" in fields:
        fields["asleep"] = 1 if fields["asleep"] else 0
    row = db.create_event(chat_id, event.subject, fields, datetime.now(timezone()))
    return Event(**dict(row))


@app.patch("/events/{event_id}", response_model=Event)
def patch_event(event_id: int, patch: EventPatch) -> Event:
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to update")
    if "type" in changes and changes["type"] is None:
        raise HTTPException(status_code=422, detail="type cannot be null")
    if "liquid" in changes:
        changes["liquid"] = 1 if changes["liquid"] else None
    if "asleep" in changes and changes["asleep"] is not None:
        changes["asleep"] = 1 if changes["asleep"] else 0
    if "occurred_at" in changes:
        if changes["occurred_at"] is None:
            raise HTTPException(status_code=422, detail="occurred_at cannot be null")
        moment = in_care_zone(changes["occurred_at"])
        changes["occurred_at"] = moment.isoformat()
        changes["day"] = db.care_day(moment).isoformat()
    row = db.update_event(event_id, changes, datetime.now(timezone()))
    if row is None:
        raise _not_found(event_id)
    return Event(**dict(row))


@app.delete("/events/{event_id}", response_model=Event)
def delete_event(event_id: int, confirm: bool = False) -> Event:
    if not confirm:
        raise HTTPException(
            status_code=400, detail=f"add ?confirm=true to delete event {event_id}"
        )
    row = db.delete_event(event_id, datetime.now(timezone()))
    if row is None:
        raise _not_found(event_id)
    return Event(**dict(row))


@app.get("/events/{event_id}/edits", response_model=list[Edit])
def event_edits(event_id: int) -> list[Edit]:
    return [
        Edit(
            edited_at=row["edited_at"],
            action=row["action"],
            before=json.loads(row["before"]),
            after=None if row["after"] is None else json.loads(row["after"]),
        )
        for row in db.edits_for_event(event_id)
    ]


@app.get("/chats", response_model=list[Chat])
def list_chats() -> list[Chat]:
    return [Chat(**dict(row)) for row in db.chats()]


@app.patch("/chats/{chat_id}", response_model=Chat)
def patch_chat(chat_id: int, patch: ChatPatch) -> Chat:
    if db.chat(chat_id) is None:
        raise HTTPException(status_code=404, detail=f"chat {chat_id} not found")
    if patch.profile is not None and profiles.get(patch.profile) is None:
        raise HTTPException(status_code=422, detail=f"unknown profile {patch.profile}")
    try:
        db.set_profile(chat_id, patch.profile)
    except db.ProfileTaken:
        raise HTTPException(
            status_code=409, detail=f"another chat keeps the diary of {patch.profile}"
        ) from None
    return Chat(**dict(db.chat(chat_id)))


def main() -> None:
    token = os.environ.get("API_TOKEN", "")
    if len(token) < MIN_TOKEN_LENGTH:
        raise SystemExit(
            f"API_TOKEN must be set to at least {MIN_TOKEN_LENGTH} characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    db.init()
    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8080")),
    )
