"""Read-only web pages for the family: weeks, days, medications, foods and refusals.

Nothing here writes to the diary. The admin API, which can, stays on the loopback.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import care_export, charts, db, foods, meds, web_auth
from .profiles import Profile

WEEK_DAYS = 7
DEFAULT_PERIOD_DAYS = 30
TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
TYPE_LABELS = {
    "food": "еда",
    "water": "вода",
    "medication": "лекарство",
    "refusal": "отказ",
    "toilet": "туалет",
    "temperature": "температура",
    "state": "состояние",
    "other": "прочее",
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self'; style-src 'self'; "
                               "form-action 'self' https://oauth.telegram.org; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def settings() -> web_auth.Settings:
    return app.state.settings


def timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))


def today() -> date:
    return db.care_day(datetime.now(timezone()))


class SignInRequired(Exception):
    pass


@app.exception_handler(SignInRequired)
def sign_in(_request: Request, _error: SignInRequired) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


@dataclass(frozen=True)
class Viewer:
    uid: int
    name: str


@dataclass(frozen=True)
class Animal:
    chat_id: int
    profile: Profile

    @property
    def subject(self) -> str:
        return self.profile.subject_id


def viewer(request: Request) -> Viewer:
    session = web_auth.unsign(request.cookies.get(web_auth.SESSION_COOKIE), settings().session_secret)
    if session is None:
        raise SignInRequired
    return Viewer(uid=session["uid"], name=session["name"])


def visible_animals(person: Viewer) -> list[Animal]:
    return [
        Animal(chat_id, profile)
        for chat_id, profile in db.all_chats()
        if web_auth.is_member(settings(), chat_id, person.uid)
    ]


def animal(subject: str, person: Annotated[Viewer, Depends(viewer)]) -> Animal:
    for candidate in db.all_chats():
        chat_id, profile = candidate
        if profile.subject_id == subject and web_auth.is_member(settings(), chat_id, person.uid):
            return Animal(chat_id, profile)
    raise HTTPException(status_code=404)


def page(request: Request, template: str, person: Viewer, current: Animal | None, **context):
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {"viewer": person, "current": current, "animals": visible_animals(person), **context},
    )


def period(day_from: date | None, day_to: date | None, chat_id: int, everything: bool) -> tuple[date, date]:
    end = day_to or today()
    if everything:
        return db.first_event_day(chat_id) or end, end
    start = day_from or end - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if start > end:
        raise HTTPException(status_code=422, detail="the period starts after it ends")
    return start, end


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "login.html", {"viewer": None, "current": None, "animals": []})


@app.get("/auth/start")
def auth_start() -> RedirectResponse:
    url, cookie = web_auth.start_login(settings())
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(web_auth.LOGIN_COOKIE, cookie, max_age=web_auth.LOGIN_SECONDS,
                        path="/auth", httponly=True, secure=settings().base_url.startswith("https"),
                        samesite="lax")
    return response


@app.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return TEMPLATES.TemplateResponse(
            request, "login.html",
            {"viewer": None, "current": None, "animals": [], "problem": "Вход отменён или не удался."},
            status_code=400,
        )
    try:
        session = web_auth.finish_login(settings(), request.cookies.get(web_auth.LOGIN_COOKIE), state, code)
    except web_auth.AuthError as failure:
        logger.warning("Sign-in failed: %s", failure)
        return TEMPLATES.TemplateResponse(
            request, "login.html",
            {"viewer": None, "current": None, "animals": [], "problem": "Не получилось войти. Попробуйте ещё раз."},
            status_code=400,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(web_auth.SESSION_COOKIE,
                        web_auth.sign(session, settings().session_secret, web_auth.SESSION_SECONDS),
                        max_age=web_auth.SESSION_SECONDS, httponly=True,
                        secure=settings().base_url.startswith("https"), samesite="lax")
    response.delete_cookie(web_auth.LOGIN_COOKIE, path="/auth")
    return response


@app.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(web_auth.SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request, person: Annotated[Viewer, Depends(viewer)]):
    animals = visible_animals(person)
    if len(animals) == 1:
        return RedirectResponse(f"/{animals[0].subject}/week", status_code=303)
    return page(request, "home.html", person, None)


@dataclass
class DayRow:
    day: date
    kcal_self: float
    kcal_tube: float
    drinking_ml: float | None
    from_food_ml: float | None
    urinations: int | None
    stools: int | None
    vomiting: int
    refusals: int
    temperatures: list[float]

    @property
    def kcal(self) -> float:
        return self.kcal_self + self.kcal_tube


def week_rows(current: Animal, end: date) -> list[DayRow]:
    start = end - timedelta(days=WEEK_DAYS - 1)
    exported = {d.care_day: d for d in care_export.export(current.subject, start, end)}
    events = db.events_in_days(current.chat_id, start, end)
    rows = []
    for offset in range(WEEK_DAYS):
        day = start + timedelta(days=offset)
        food = [e for e in events if e["day"] == day.isoformat() and e["type"] == "food"]
        record = exported[day]
        rows.append(DayRow(
            day=day,
            kcal_self=sum(e["kcal"] or 0 for e in food if e["feeding"] != "tube"),
            kcal_tube=sum(e["kcal"] or 0 for e in food if e["feeding"] == "tube"),
            drinking_ml=record.water_drinking_ml,
            from_food_ml=record.water_from_food_ml,
            urinations=record.urinations_observed,
            stools=record.stools_observed,
            vomiting=len(record.vomiting_episodes),
            refusals=len(record.food_refusals),
            temperatures=[t.value_c for t in record.temperatures],
        ))
    return rows


@app.get("/{subject}/week", response_class=HTMLResponse)
def week(request: Request, person: Annotated[Viewer, Depends(viewer)],
         current: Annotated[Animal, Depends(animal)], end: date | None = None):
    end = end or today()
    return page(request, "week.html", person, current, end=end, rows=week_rows(current, end),
                previous=end - timedelta(days=WEEK_DAYS), following=end + timedelta(days=WEEK_DAYS),
                is_current=end >= today())


@app.get("/{subject}/week.png")
def week_chart(current: Annotated[Animal, Depends(animal)], end: date | None = None) -> Response:
    png = charts.render_week(current.chat_id, end or today(), current.profile)
    return Response(png, media_type="image/png")


@app.get("/{subject}/day/{day}", response_class=HTMLResponse)
def day_page(request: Request, day: date, person: Annotated[Viewer, Depends(viewer)],
             current: Annotated[Animal, Depends(animal)]):
    events = db.events_with_messages(current.chat_id, day, day)
    return page(request, "day.html", person, current, day=day, events=events, labels=TYPE_LABELS,
                previous=day - timedelta(days=1), following=day + timedelta(days=1))


@app.get("/{subject}/meds", response_class=HTMLResponse)
def meds_page(request: Request, person: Annotated[Viewer, Depends(viewer)],
              current: Annotated[Animal, Depends(animal)],
              day_from: Annotated[date | None, Query(alias="from")] = None,
              day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False):
    start, end = period(day_from, day_to, current.chat_id, all)
    courses = meds.courses(db.medications_in_days(current.chat_id, start, end))
    return page(request, "meds.html", person, current, start=start, end=end, courses=courses,
                label=meds._label, doses=meds._doses, span=meds._span)


@app.get("/{subject}/meds.png")
def meds_chart(current: Annotated[Animal, Depends(animal)],
               day_from: Annotated[date | None, Query(alias="from")] = None,
               day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False) -> Response:
    start, end = period(day_from, day_to, current.chat_id, all)
    rows = db.medications_in_days(current.chat_id, start, end)
    if not rows:
        raise HTTPException(status_code=404)
    return Response(charts.render_meds(rows, start, end, current.profile), media_type="image/png")


@app.get("/{subject}/foods", response_class=HTMLResponse)
def foods_page(request: Request, person: Annotated[Viewer, Depends(viewer)],
               current: Annotated[Animal, Depends(animal)],
               day_from: Annotated[date | None, Query(alias="from")] = None,
               day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False):
    start, end = period(day_from, day_to, current.chat_id, all)
    lines, tube = foods.report(db.events_in_days(current.chat_id, start, end))
    return page(request, "foods.html", person, current, start=start, end=end, lines=lines, tube=tube)


@app.get("/{subject}/refusals", response_class=HTMLResponse)
def refusals_page(request: Request, person: Annotated[Viewer, Depends(viewer)],
                  current: Annotated[Animal, Depends(animal)],
                  day_from: Annotated[date | None, Query(alias="from")] = None,
                  day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False):
    start, end = period(day_from, day_to, current.chat_id, all)
    refusals = [e for e in db.events_with_messages(current.chat_id, start, end) if e["type"] == "refusal"]
    return page(request, "refusals.html", person, current, start=start, end=end,
                refusals=list(reversed(refusals)), products=foods.refused_products)


@app.get("/static/style.css")
def stylesheet() -> Response:
    css = (Path(__file__).parent / "templates" / "style.css").read_text()
    return Response(css, media_type="text/css", headers={"Cache-Control": "max-age=3600"})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app.state.settings = web_auth.Settings.from_env()
    uvicorn.run(app, host=os.environ.get("WEB_HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8080")),
                proxy_headers=True, forwarded_allow_ips="*")
