import base64
import hashlib
import hmac
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.errors import AppError

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def create_token(subject: str, purpose: str = "access", minutes: int | None = None) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or s.access_token_minutes)
    return jwt.encode({"sub": subject, "typ": purpose, "exp": exp}, s.secret_key, algorithm="HS256")


def decode_token(token: str, purpose: str = "access") -> str:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise AppError("INVALID_TOKEN", "Invalid or expired token.", 401)
    if data.get("typ") != purpose:
        raise AppError("INVALID_TOKEN", "Invalid token type.", 401)
    return data["sub"]


class RateLimiter:
    """Small in-memory sliding-window limiter (use Redis or a gateway for multi-process deployments)."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: int = 60) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise AppError("RATE_LIMITED", "Too many requests. Please try again shortly.", 429)
        q.append(now)

    def reset(self) -> None:
        self.hits.clear()


rate_limiter = RateLimiter()
