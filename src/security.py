import time
from collections import defaultdict, deque

from flask import Flask, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user


def user_or_ip_key() -> str:
    """Rate-limit key: the user id when authenticated, otherwise the client IP."""
    if current_user and current_user.is_authenticated:
        return f"user:{current_user.id}"
    return f"ip:{get_remote_address()}"


def json_field_key(field: str):
    """Build a key function scoping a limit to a (lower-cased) field of the JSON body, e.g. the targeted account."""
    def key() -> str:
        data = request.get_json(silent=True) or {}
        value = str(data.get(field) or "").strip().lower()
        return f"{field}:{value}" if value else f"ip:{get_remote_address()}"
    return key


# get_remote_address() relies on request.remote_addr, which ProxyFix rewrites from the proxy's
# X-Forwarded-For (see app.py). Counters are in memory: single process only.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["600 per minute"],
    storage_uri="memory://",
    headers_enabled=True,
)


class SocketRateLimiter:
    """Tiny sliding-window limiter for Socket.IO events (Flask-Limiter only covers HTTP routes)."""

    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_events:
            return False
        hits.append(now)
        return True


def init_security(app: Flask) -> None:
    """Attach the rate limiter, its JSON 429 handler and the security headers to the app."""
    limiter.init_app(app)

    @app.errorhandler(429)
    def too_many_requests(e):
        return {"success": False, "message": "Too many requests. Please slow down and try again later."}, 429

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        if response.mimetype == 'application/json':
            response.headers.setdefault('Cache-Control', 'no-store')
        return response
