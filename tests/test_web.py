"""The family web pages: who gets in, who sees which animal, and what the pages show."""

import gzip
import io
import json
import sqlite3
import time
import urllib.error
import urllib.parse
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from skrypka_bot import db, foods, web, web_auth

BERLIN = ZoneInfo("Europe/Berlin")
SECRET = b"s" * 40
CLIENT_ID = "8646461339"
MEMBER = 111
STRANGER = 222


@pytest.fixture
def settings(monkeypatch):
    value = web_auth.Settings(
        client_id=CLIENT_ID, client_secret="client-secret", base_url="https://cats.example",
        session_secret=SECRET, bot_token="bot-token",
    )
    web.app.state.settings = value
    web_auth._membership.clear()
    return value


@pytest.fixture
def members(monkeypatch, chat):
    """Telegram's answer to getChatMember: MEMBER is in the test chat, nobody else is."""
    calls = []

    def answer(url, timeout):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        calls.append(query)
        status = "member" if int(query["user_id"][0]) == MEMBER else "left"
        return io.BytesIO(json.dumps({"ok": True, "result": {"status": status}}).encode())

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", answer)
    return calls


def client(user_id=None) -> TestClient:
    test_client = TestClient(web.app, base_url="https://cats.example")
    if user_id is not None:
        test_client.cookies.set(web_auth.SESSION_COOKIE,
                                web_auth.sign({"uid": user_id, "name": "Тест"}, SECRET, 3600))
    return test_client


def record(chat_id, hour, day=date(2026, 10, 6), text=None, **fields):
    event = dict(type="food", name=None, dose=None, water_ml=None, kcal=None, feeding="self",
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="запись")
    event.update(fields)
    sent = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
    record.n = getattr(record, "n", 0) + 1
    db.save_message(chat_id, record.n, "owner", sent, text or f"сообщение {record.n}",
                    [SimpleNamespace(**event)])


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(web, "today", lambda: date(2026, 10, 6))


def test_a_signed_value_survives_and_a_changed_one_does_not():
    value = web_auth.sign({"uid": 5}, SECRET, 60, now=1000)
    assert web_auth.unsign(value, SECRET, now=1030)["uid"] == 5
    body, mac = value.split(".")
    assert web_auth.unsign(f"{body}x.{mac}", SECRET, now=1030) is None
    assert web_auth.unsign(value, b"other" * 10, now=1030) is None
    assert web_auth.unsign(value, SECRET, now=1061) is None


def test_every_page_sends_a_stranger_to_the_login(settings, chat):
    for path in ("/", "/chipunya/week", "/chipunya/day/2026-10-06", "/chipunya/meds",
                 "/chipunya/foods", "/chipunya/refusals", "/chipunya/week.png"):
        response = client().get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/login"), path


def test_signed_in_but_not_in_the_chat_sees_no_animal(settings, members, today):
    assert client(STRANGER).get("/chipunya/week").status_code == 404
    assert client(STRANGER).get("/chipunya/week.png").status_code == 404
    page = client(STRANGER).get("/")
    assert "не состоите ни в одном чате" in page.text


def test_a_member_of_one_animals_chat_cannot_open_the_other_animal(settings, monkeypatch, today, chat):
    skripa_chat = -2
    db.set_profile(skripa_chat, "skripa")
    chats_of = {MEMBER: {chat, skripa_chat}, STRANGER: {skripa_chat}}

    def answer(url, timeout):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        joined = int(query["chat_id"][0]) in chats_of[int(query["user_id"][0])]
        return io.BytesIO(json.dumps({"ok": True, "result": {"status": "member" if joined else "left"}}).encode())

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", answer)
    for path in ("/chipunya/week", "/chipunya/day/2026-10-06", "/chipunya/meds",
                 "/chipunya/foods", "/chipunya/refusals", "/chipunya/week.png", "/chipunya/meds.png"):
        assert client(STRANGER).get(path).status_code == 404, path
    assert client(STRANGER).get("/", follow_redirects=False).headers["location"] == "/skripa/week"
    page = client(STRANGER).get("/skripa/week")
    assert page.status_code == 200
    assert 'href="/chipunya/' not in page.text
    assert 'href="/chipunya/week"' in client(MEMBER).get("/skripa/week").text


def test_a_member_lands_on_the_week_with_the_day_figures(settings, members, today, chat):
    record(chat, 9, kcal=40.0, feeding="tube")
    record(chat, 10, kcal=12.0)
    record(chat, 11, type="toilet", feeding=None, description="пописал")
    response = client(MEMBER).get("/", follow_redirects=False)
    assert response.headers["location"] == "/chipunya/week"
    page = client(MEMBER).get("/chipunya/week")
    row = page.text.split('href="/chipunya/day/2026-10-06">Вт 06.10</a></td>')[1].split("</tr>")[0]
    cells = [cell.strip() for cell in row.replace("<strong>", "").replace("</strong>", "").split("<td>")[1:]]
    assert [cell.removesuffix("</td>").strip() for cell in cells][:7] == ["12", "40", "52", "–", "0", "1", "–"]


def test_any_period_lists_each_day_and_averages_only_the_recorded_ones(settings, members, today, chat):
    record(chat, 9, day=date(2026, 9, 20), kcal=100.0)
    record(chat, 9, day=date(2026, 9, 22), kcal=60.0, feeding="tube")
    page = client(MEMBER).get("/chipunya/week?from=2026-09-20&to=2026-09-24").text
    assert page.count('class="when"') == 5
    assert page.count('</a></td>') == 5
    mean = page.split('<tr class="mean">')[1].split("</tr>")[0]
    cells = [c.split("</td>")[0].replace("<strong>", "").replace("</strong>", "").strip()
             for c in mean.split("<td>")[1:]]
    assert cells[:4] == ["В среднем", "50", "30", "80"]
    assert "за 2 дн. с записями" in page
    assert 'href="?from=2026-09-15&amp;to=2026-09-19">' in page and "<span>15.09–19.09</span>" in page
    assert 'href="?from=2026-09-25&amp;to=2026-09-29">' in page and "<span>25.09–29.09</span>" in page


def test_the_period_chart_draws_a_long_range(settings, members, today, chat):
    png = client(MEMBER).get("/chipunya/week.png?from=2026-08-28&to=2026-10-06").content
    assert png.startswith(b"\x89PNG")


def test_membership_is_asked_once_and_then_cached(settings, members, today):
    client(MEMBER).get("/chipunya/week")
    client(MEMBER).get("/chipunya/foods")
    assert len(members) == 1


def test_someone_who_never_joined_is_not_a_member(settings, monkeypatch):
    def unknown_user(url, timeout):
        raise urllib.error.HTTPError(url, 400, "Bad Request: user not found", None, None)

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", unknown_user)
    assert web_auth.is_member(settings, -1, 999) is False


def test_a_network_failure_is_not_remembered_as_no_access(settings, monkeypatch):
    def offline(url, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", offline)
    with pytest.raises(urllib.error.URLError):
        web_auth.is_member(settings, -1, MEMBER)
    assert (-1, MEMBER) not in web_auth._membership


def test_the_day_shows_each_event_and_the_chat_message_only_when_it_adds_something(settings, members, chat):
    record(chat, 10, name="felix sauce", kcal=10.0, amount_ml=40.0, description="выпил весь пакетик")
    record(chat, 21, type="medication", feeding=None, name="серения", dose="6 мг", description="дала",
           text="дала 22мл воды и лекарства:\n4мг ондансетрона\n6мг серении")
    page = client(MEMBER).get("/chipunya/day/2026-10-06").text
    assert '<span class="title">Felix Sauce, 40 мл</span>' in page and "10 ккал" in page
    assert page.count("сообщение в чате") == 1
    assert "4мг ондансетрона" in page


def test_the_day_draws_the_hours_with_a_title_on_each_mark(settings, members, chat):
    record(chat, 10, name="felix sauce", kcal=10.0, amount_ml=40.0, description="выпил весь пакетик")
    page = client(MEMBER).get("/chipunya/day/2026-10-06").text
    assert '<svg class="clock"' in page
    assert "<title>10:00 выпил весь пакетик, 10 ккал</title>" in page


def test_the_food_report_puts_eating_and_refusing_side_by_side(settings, members, today, chat):
    record(chat, 9, name="felix sauce", kcal=10.0, liquid=True)
    record(chat, 10, type="refusal", feeding=None, name="royal canin urinary s/o", description="не стал")
    record(chat, 11, kcal=30.0, feeding="tube", name="royal canin recovery liquid")
    page = client(MEMBER).get("/chipunya/foods").text
    assert "Через зонд: 1 кормлений, 30 ккал" in page
    assert '<span class="title">Felix Sauce</span>' in page
    only_refused = page.split('class="food only-refused"')[1].split("</li>")[0]
    assert '<span class="title">RC Urinary</span>' in only_refused
    assert "Не ест вовсе" in page


def test_pages_render_for_a_member(settings, members, today, chat):
    record(chat, 9, type="medication", feeding=None, name="бупренорфин", dose="0.06 мг (0.2 мл)")
    record(chat, 10, type="refusal", feeding=None, name="hills i/d", description="отказался от сухариков хилс")
    member = client(MEMBER)
    assert "бупренорфин" in member.get("/chipunya/meds").text
    assert member.get("/chipunya/meds.png").content.startswith(b"\x89PNG")
    assert member.get("/chipunya/week.png").content.startswith(b"\x89PNG")
    assert "Hill&#39;s i/d, dry" in member.get("/chipunya/refusals").text
    assert member.get("/chipunya/meds?from=2026-10-07&to=2026-10-01").status_code == 422


def test_pages_carry_a_strict_content_security_policy(settings):
    headers = client().get("/login").headers
    assert headers["content-security-policy"].startswith("default-src 'self'")
    assert headers["referrer-policy"] == "no-referrer"


def test_the_read_only_connection_cannot_write(chat, monkeypatch):
    monkeypatch.setenv("DB_READ_ONLY", "1")
    with pytest.raises(sqlite3.OperationalError), db._connect() as conn:
        conn.execute("DELETE FROM events")
    assert db.all_chats()


@pytest.fixture
def telegram_key(monkeypatch):
    """Telegram's JWKS, served gzip-compressed without being asked, as the real host does."""
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = {**jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True),
           "kid": "test-es256", "alg": "ES256", "use": "sig"}
    body = gzip.compress(json.dumps({"keys": [jwk]}).encode())

    def serve(url, timeout):
        assert url == web_auth.JWKS_URL
        return io.BytesIO(body)

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", serve)
    monkeypatch.setitem(web_auth._jwks, "keys", [])
    return private


def id_token(private, expected_nonce, **overrides):
    claims = {"iss": web_auth.ISSUER, "aud": CLIENT_ID, "sub": "x", "iat": int(time.time()),
              "exp": int(time.time()) + 600, "id": MEMBER, "name": "Анна", "nonce": expected_nonce}
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, private, algorithm="ES256",
                      headers={"kid": "test-es256"})


def login(settings, monkeypatch, make_token):
    start = client().get("/auth/start", follow_redirects=False)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(start.headers["location"]).query)
    attempt = web_auth.unsign(start.cookies[web_auth.LOGIN_COOKIE], SECRET)
    exchanged = {}

    def exchange(_settings, code, verifier):
        exchanged.update(code=code, verifier=verifier)
        return make_token(attempt["nonce"])

    monkeypatch.setattr(web_auth, "_exchange", exchange)
    callback = client()
    callback.cookies.set(web_auth.LOGIN_COOKIE, start.cookies[web_auth.LOGIN_COOKIE], path="/auth")
    response = callback.get(f"/auth/callback?code=abc&state={query['state'][0]}", follow_redirects=False)
    return response, query, attempt, exchanged


def test_a_telegram_login_signs_the_member_in(settings, monkeypatch, telegram_key):
    response, query, attempt, exchanged = login(settings, monkeypatch,
                                                lambda nonce: id_token(telegram_key, nonce))
    assert query["scope"] == ["openid profile"] and query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://cats.example/auth/callback"]
    assert exchanged == {"code": "abc", "verifier": attempt["verifier"]}
    assert response.status_code == 303 and response.headers["location"] == "/"
    session = web_auth.unsign(response.cookies[web_auth.SESSION_COOKIE], SECRET)
    assert (session["uid"], session["name"]) == (MEMBER, "Анна")


def test_a_user_id_sent_as_a_string_is_accepted(settings, monkeypatch, telegram_key):
    response, *_ = login(settings, monkeypatch,
                         lambda nonce: id_token(telegram_key, nonce, id=str(MEMBER)))
    session = web_auth.unsign(response.cookies[web_auth.SESSION_COOKIE], SECRET)
    assert session["uid"] == MEMBER


def test_a_missing_user_id_names_the_claims_that_came(settings, monkeypatch, telegram_key, caplog):
    response, *_ = login(settings, monkeypatch, lambda nonce: id_token(telegram_key, nonce, id=None))
    assert response.status_code == 400
    assert "claims present: ['aud', 'exp', 'iat', 'iss', 'name', 'nonce', 'sub']" in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "someone-else"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 10},
     {"id": None}, {"nonce": "replayed"}],
)
def test_a_token_that_does_not_check_out_is_refused(settings, monkeypatch, telegram_key, overrides):
    response, *_ = login(settings, monkeypatch, lambda nonce: id_token(telegram_key, nonce, **overrides))
    assert response.status_code == 400
    assert web_auth.SESSION_COOKIE not in response.cookies


def test_a_refused_code_is_reported_not_crashed_on(settings, monkeypatch, caplog):
    def refused(url, timeout):
        return io.BytesIO(json.dumps({"error": "invalid_grant"}).encode())

    monkeypatch.setattr(web_auth.urllib.request, "urlopen", refused)
    start = client().get("/auth/start", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(start.headers["location"]).query)["state"][0]
    callback = client()
    callback.cookies.set(web_auth.LOGIN_COOKIE, start.cookies[web_auth.LOGIN_COOKIE], path="/auth")
    response = callback.get(f"/auth/callback?code=used&state={state}", follow_redirects=False)
    assert response.status_code == 400
    assert "token endpoint refused the code: invalid_grant" in caplog.text


def test_an_unknown_key_id_is_refused(settings, telegram_key):
    token = jwt.encode({"id": 1}, telegram_key, algorithm="ES256", headers={"kid": "rotated-away"})
    with pytest.raises(web_auth.AuthError, match="no Telegram signing key"):
        web_auth.verify_id_token(settings, token, "nonce")


def test_a_callback_without_its_login_attempt_is_refused(settings):
    response = client().get("/auth/callback?code=abc&state=forged", follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("text", "liquid", "expected"),
    [("purina one zalm", False, "Purina One salmon"), ("purina one", False, "Purina One beef"),
     ("felix sauce", True, "Felix Sauce"), ("felix soup", True, "Felix Soup"),
     ("felix sensations sauces eend/wortel", True, "Felix Sensations"),
     ("royal canin digestive care", True, "RC Digestive Care, wet"),
     ("royal canin digestive care", False, "Hill's i/d, dry"),
     ("monge salmon kitten", True, "Monge"), ("royal canin kitten", True, "RC Kitten"),
     ("сухарики", False, foods.UNNAMED_DRY)],
)
def test_food_names_collapse_to_one_product(text, liquid, expected):
    assert foods.product(text, liquid) == expected


def test_a_description_that_names_nothing_is_an_unnamed_food():
    assert foods.product("немного поела (сама)", False, named=False) == foods.UNNAMED
