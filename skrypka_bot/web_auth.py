"""Sign-in with Telegram (OpenID Connect) and who may see which animal.

Anyone who can sign in with Telegram reaches the login page. Only a member of an animal's
chat sees that animal: membership is asked of Telegram and cached for a few minutes, so
removing someone from the chat takes their access away without a code change.
"""

import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import jwt

ISSUER = "https://oauth.telegram.org"
AUTHORIZE_URL = f"{ISSUER}/auth"
TOKEN_URL = f"{ISSUER}/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
SIGNING_ALGORITHMS = ["RS256", "ES256", "EdDSA", "ES256K"]

SESSION_COOKIE = "session"
LOGIN_COOKIE = "login"
SESSION_SECONDS = 30 * 24 * 3600
LOGIN_SECONDS = 10 * 60
MEMBERSHIP_SECONDS = 10 * 60
JWKS_SECONDS = 3600
MIN_SECRET_LENGTH = 32
MEMBER_STATUSES = {"creator", "administrator", "member"}

_jwks: dict[str, object] = {"at": 0.0, "keys": []}
_membership: dict[tuple[int, int], tuple[float, bool]] = {}


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    base_url: str
    session_secret: bytes
    bot_token: str

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("WEB_SESSION_SECRET", "")
        if len(secret) < MIN_SECRET_LENGTH:
            raise SystemExit(
                f"WEB_SESSION_SECRET must be set to at least {MIN_SECRET_LENGTH} characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        missing = [
            name
            for name in ("TELEGRAM_OPENID_CLIENT_ID", "TELEGRAM_OPENID_CLIENT_SECRET",
                         "WEB_BASE_URL", "TELEGRAM_BOT_TOKEN")
            if not os.environ.get(name)
        ]
        if missing:
            raise SystemExit(f"care-web needs {', '.join(missing)}")
        return cls(
            client_id=os.environ["TELEGRAM_OPENID_CLIENT_ID"],
            client_secret=os.environ["TELEGRAM_OPENID_CLIENT_SECRET"],
            base_url=os.environ["WEB_BASE_URL"].rstrip("/"),
            session_secret=secret.encode(),
            bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: bytes, lifetime: int, now: float | None = None) -> str:
    body = _b64(json.dumps({**payload, "exp": int((now or time.time()) + lifetime)}).encode())
    mac = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def unsign(value: str | None, secret: bytes, now: float | None = None) -> dict | None:
    if not value or value.count(".") != 1:
        return None
    body, mac = value.split(".")
    expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    if payload.get("exp", 0) < (now or time.time()):
        return None
    return payload


def start_login(settings: Settings) -> tuple[str, str]:
    """The Telegram authorization URL, and the signed cookie that remembers this attempt."""
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode({
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    cookie = sign({"state": state, "nonce": nonce, "verifier": verifier},
                  settings.session_secret, LOGIN_SECONDS)
    return f"{AUTHORIZE_URL}?{query}", cookie


def _read_json(response) -> dict:
    """Telegram's OAuth host sends gzip whether or not the client asked for it."""
    body = response.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body)


def _signing_keys(refresh: bool = False) -> list[jwt.PyJWK]:
    if refresh or not _jwks["keys"] or time.time() - _jwks["at"] > JWKS_SECONDS:
        with urllib.request.urlopen(JWKS_URL, timeout=10) as response:
            _jwks["keys"] = jwt.PyJWKSet.from_dict(_read_json(response)).keys
        _jwks["at"] = time.time()
    return _jwks["keys"]


def _signing_key(id_token: str) -> jwt.PyJWK:
    kid = jwt.get_unverified_header(id_token).get("kid")
    for refresh in (False, True):
        keys = _signing_keys(refresh)
        matching = [key for key in keys if key.key_id == kid] if kid else keys[:1]
        if matching:
            return matching[0]
    raise AuthError(f"no Telegram signing key with kid {kid!r}")


def _exchange(settings: Settings, code: str, verifier: str) -> str:
    credentials = base64.b64encode(f"{settings.client_id}:{settings.client_secret}".encode()).decode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.client_id,
            "code_verifier": verifier,
        }).encode(),
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = _read_json(response)
    if "error" in payload:
        raise AuthError(f"token endpoint refused the code: {payload['error']}")
    return payload["id_token"]


def verify_id_token(settings: Settings, id_token: str, nonce: str) -> dict:
    key = _signing_key(id_token)
    claims = jwt.decode(
        id_token,
        key.key,
        algorithms=SIGNING_ALGORITHMS,
        audience=settings.client_id,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    if claims.get("nonce") not in (None, nonce):
        raise AuthError("nonce does not match")
    if not isinstance(claims.get("id"), int):
        raise AuthError("no Telegram user id in the token")
    return claims


def finish_login(settings: Settings, login_cookie: str | None, state: str, code: str) -> dict:
    """Check the callback against the attempt, and return the session payload."""
    attempt = unsign(login_cookie, settings.session_secret)
    if attempt is None or not hmac.compare_digest(attempt["state"], state):
        raise AuthError("login attempt expired or did not start here")
    try:
        id_token = _exchange(settings, code, attempt["verifier"])
        claims = verify_id_token(settings, id_token, attempt["nonce"])
    except (OSError, KeyError, ValueError, jwt.PyJWTError) as error:
        raise AuthError(f"Telegram did not confirm the login: {type(error).__name__}: {error}") from error
    return {"uid": claims["id"], "name": claims.get("name") or claims.get("preferred_username") or ""}


def is_member(settings: Settings, chat_id: int, user_id: int, now: float | None = None) -> bool:
    now = now or time.time()
    cached = _membership.get((chat_id, user_id))
    if cached and now - cached[0] < MEMBERSHIP_SECONDS:
        return cached[1]
    url = (f"https://api.telegram.org/bot{settings.bot_token}/getChatMember?"
           + urllib.parse.urlencode({"chat_id": chat_id, "user_id": user_id}))
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            member = json.load(response)["result"]
    except urllib.error.HTTPError as error:
        if error.code != 400:
            raise
        member = {"status": "left"}
    allowed = member["status"] in MEMBER_STATUSES or (
        member["status"] == "restricted" and member.get("is_member", False)
    )
    _membership[(chat_id, user_id)] = (now, allowed)
    return allowed
