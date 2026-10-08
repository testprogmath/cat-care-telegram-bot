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

from . import charts, db, foods, meds, views, web_auth
from .profiles import Profile

WEEK_DAYS = 7
DEFAULT_PERIOD_DAYS = 30
TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
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
    section = request.url.path.split("/")[2] if current else ""
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {"viewer": person, "current": current, "animals": visible_animals(person),
         "section": "week" if section in ("day", "") else section.removesuffix(".png"),
         "weekday": views.weekday, "today": today(), "timedelta_days": lambda n: timedelta(days=n),
         **context},
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


def days_period(current: Animal, day_from: date | None, day_to: date | None, everything: bool,
                end: date | None) -> tuple[date, date]:
    if everything:
        last = today()
        return db.first_event_day(current.chat_id) or last, last
    if day_from is None and day_to is None:
        last = end or today()
        return last - timedelta(days=WEEK_DAYS - 1), last
    return period(day_from, day_to, current.chat_id, False)


@app.get("/{subject}/week", response_class=HTMLResponse)
def week(request: Request, person: Annotated[Viewer, Depends(viewer)],
         current: Annotated[Animal, Depends(animal)],
         day_from: Annotated[date | None, Query(alias="from")] = None,
         day_to: Annotated[date | None, Query(alias="to")] = None,
         all: bool = False, end: date | None = None):
    start, last = days_period(current, day_from, day_to, all, end)
    span = timedelta(days=(last - start).days + 1)
    trend_rows = views.day_rows(current.chat_id, current.subject, start - timedelta(days=views.TREND_WINDOW - 1), last)
    rows = [r for r in trend_rows if r.day >= start]
    mean = views.averages(rows)
    profile = current.profile
    marks = views.treatment_marks(db.medications_in_days(current.chat_id, date(2000, 1, 1), last))
    stool = views.last_stool(current.chat_id, today())
    return page(request, "week.html", person, current, start=start, end=last, rows=rows, mean=mean,
                kcal_share=mean and views.Share.of(mean.kcal_tube, mean.kcal_self, profile.kcal_goal),
                water_share=mean and views.Share3.of(
                    (mean.drank_ml, max(mean.drinking_ml - mean.drank_ml, 0), mean.from_food_ml),
                    profile.water_goal_ml),
                weight=views.weight_summary(current.chat_id, start, last, today()),
                trend=views.appetite_trend(trend_rows, start, last, profile.kcal_goal, marks),
                breaths=views.breathing(current.chat_id, start, last),
                breath_limit=views.SLEEP_BREATHS_LIMIT,
                stool=stool, stool_ago=stool and (today() - stool).days, stool_warn=views.STOOL_WARN_DAYS,
                stool_days=sum(1 for r in rows if r.stools), recorded_days=sum(1 for r in rows if r.recorded),
                vomiting=sum(r.vomiting for r in rows),
                chart=views.mini_chart(rows, profile.kcal_goal),
                previous=(start - span, start - timedelta(days=1)),
                following=(last + timedelta(days=1), last + span), is_current=last >= today())


@app.get("/{subject}/week.png")
def week_chart(current: Annotated[Animal, Depends(animal)],
               day_from: Annotated[date | None, Query(alias="from")] = None,
               day_to: Annotated[date | None, Query(alias="to")] = None,
               all: bool = False, end: date | None = None) -> Response:
    start, last = days_period(current, day_from, day_to, all, end)
    return Response(charts.render_days(current.chat_id, start, last, current.profile),
                    media_type="image/png")


@app.get("/{subject}/day/{day}", response_class=HTMLResponse)
def day_page(request: Request, day: date, person: Annotated[Viewer, Depends(viewer)],
             current: Annotated[Animal, Depends(animal)], show: str | None = None):
    rows = db.events_with_messages(current.chat_id, day, day)
    events, water = views.day_events(rows, show, current.profile.self_label)
    clock = views.day_clock(rows, day, current.profile.kcal_goal, current.profile.water_goal_ml,
                            datetime.now(timezone()))
    legend = views.clock_legend(clock, current.profile.self_label,
                                current.profile.pick("пила сама", "пил сам")) if clock else []
    return page(request, "day.html", person, current, day=day, events=events, water=water, clock=clock, legend=legend,
                totals=views.day_rows(current.chat_id, current.subject, day, day)[0], show=show, filters=views.FILTERS,
                previous=day - timedelta(days=1), following=day + timedelta(days=1))


@app.get("/{subject}/meds", response_class=HTMLResponse)
def meds_page(request: Request, person: Annotated[Viewer, Depends(viewer)],
              current: Annotated[Animal, Depends(animal)],
              day_from: Annotated[date | None, Query(alias="from")] = None,
              day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False):
    start, end = period(day_from, day_to, current.chat_id, all)
    ongoing, finished = views.courses(db.medications_in_days(current.chat_id, start, end), start, end)
    marks = views.treatment_marks(db.medications_in_days(current.chat_id, date(2000, 1, 1), end))
    comparisons = [c for c in (views.compare_around(current.chat_id, current.subject, m, today(),
                                                    current.profile.self_label)
                               for m in views.same_day_marks(marks) if start <= m.day <= end) if c][-4:]
    return page(request, "meds.html", person, current, start=start, end=end, ongoing=ongoing,
                finished=finished, span=meds._span, comparisons=list(reversed(comparisons)))


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
    return page(request, "foods.html", person, current, start=start, end=end,
                groups=views.food_groups(lines, end), tube=tube)


@app.get("/{subject}/refusals", response_class=HTMLResponse)
def refusals_page(request: Request, person: Annotated[Viewer, Depends(viewer)],
                  current: Annotated[Animal, Depends(animal)],
                  day_from: Annotated[date | None, Query(alias="from")] = None,
                  day_to: Annotated[date | None, Query(alias="to")] = None, all: bool = False):
    start, end = period(day_from, day_to, current.chat_id, all)
    top, days = views.refusal_summary(db.events_with_messages(current.chat_id, start, end))
    total = sum(len(d.items) for d in days)
    return page(request, "refusals.html", person, current, start=start, end=end, top=top, days=days,
                total=total, unnamed=sum(1 for d in days for i in d.items if foods.UNNAMED in i.tags))


@app.get("/static/style.css")
def stylesheet() -> Response:
    css = (Path(__file__).parent / "templates" / "style.css").read_text()
    return Response(css, media_type="text/css", headers={"Cache-Control": "max-age=3600"})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app.state.settings = web_auth.Settings.from_env()
    uvicorn.run(app, host=os.environ.get("WEB_HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8080")),
                proxy_headers=True, forwarded_allow_ips="*")
