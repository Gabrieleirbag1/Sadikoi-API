import json
import types

import pytest

import app as app_module
import auth
from db import db
from security import limiter
from sockets import socketio
from utils import question_pool

from tests import factories

# Deterministic question pool, whatever data/questions.json currently holds.
TEST_POOL = [
    {"question_id": 1, "content": {"fr": "Qui est le plus drôle ?", "en": "Who is the funniest?"},
     "theme": {"id": "connerie", "fr": "connerie", "en": "stupidity"},
     "enableSelfVote": True, "enableMultipleVoting": False, "voteNumberLimit": 1, "canWrite": False,
     "item_name": {"id": "bonnet_honte", "fr": "Bonnet", "en": "Cap"}},
    {"question_id": 2, "content": {"fr": "Écris une blague", "en": "Write a joke"},
     "theme": {"id": "style", "fr": "style", "en": "style"},
     "enableSelfVote": True, "enableMultipleVoting": False, "voteNumberLimit": 0, "canWrite": True,
     "item_name": {"id": "couronne", "fr": "Couronne", "en": "Crown"}},
]


HIT_ROUTES: set[tuple[str, str]] = set()


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sadikoi")
    app_module.configure_app("pytest-unused")
    flask_app = app_module.app
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp / 'test.db'}",
        UPLOAD_FOLDER=str(tmp / "uploads"),
    )
    app_module.create_app()

    @flask_app.after_request
    def record_route(response):
        from flask import request
        if request.url_rule is not None:
            HIT_ROUTES.add((request.method, request.url_rule.rule))
        return response

    return flask_app


@pytest.fixture(autouse=True)
def database(app):
    """Fresh empty schema for every test; factories are used inside `app.app_context()`."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    original = list(question_pool)
    question_pool[:] = json.loads(json.dumps(TEST_POOL))
    yield question_pool
    question_pool[:] = original


@pytest.fixture(autouse=True)
def externals(monkeypatch):
    """Neutralise email, captcha and Socket.IO; expose what was sent through `externals`."""
    ext = types.SimpleNamespace(emails=[], reset_links=[], captcha_success=True, captcha_calls=[],
                                captcha_raises=None, events=[], real_emit=socketio.emit)

    def fake_auth_code_email(user, device, code, language="en"):
        ext.emails.append({"to": user.email, "code": code, "device_id": device.device_id})

    def fake_reset_email(user, url, language="en"):
        ext.emails.append({"to": user.email, "url": url})
        ext.reset_links.append(url)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, data=None, timeout=None, **kwargs):
        ext.captcha_calls.append({"url": url, "data": data})
        if ext.captcha_raises:
            raise ext.captcha_raises
        return FakeResponse({"success": ext.captcha_success, "error-codes": [] if ext.captcha_success else ["invalid-input-response"]})

    def fake_emit(event, data=None, **kwargs):
        ext.events.append({"event": event, "data": data, **kwargs})

    monkeypatch.setattr(auth, "send_auth_code_email", fake_auth_code_email)
    monkeypatch.setattr(auth, "send_password_reset_email", fake_reset_email)
    monkeypatch.setattr(auth, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(auth.requests, "post", fake_post)
    monkeypatch.setattr(socketio, "emit", fake_emit)
    return ext


@pytest.fixture(autouse=True)
def rate_limiting(request):
    """Disabled by default; tests marked `@pytest.mark.ratelimit` get the real limiter with clean counters."""
    enabled = request.node.get_closest_marker("ratelimit") is not None
    previous = limiter.enabled
    limiter.enabled = enabled
    if enabled:
        limiter.reset()
    yield
    limiter.enabled = previous


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.fixture
def login_as(app):
    """Return a client authenticated as `user` (session + authorized device already in place)."""
    def _login(user: factories.U, *, session_version: int = 0, device_id: str | None = None):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
            sess["session_version"] = session_version
            sess["device_id"] = device_id or user.device_id
        return client
    return _login


@pytest.fixture
def ctx(app):
    """`with ctx():` -> an app context for direct DB access (factories, assertions)."""
    return app.app_context


@pytest.fixture
def world(app):
    """A ready-made scenario: admin + member in `group`, `outsider` in no group, `other` in another group."""
    with app.app_context():
        admin = factories.make_user("admin")
        member = factories.make_user("member")
        outsider = factories.make_user("outsider")
        other = factories.make_user("other")
        group = factories.make_group(admin, [member])
        other_group = factories.make_group(other, name="Other")
    return types.SimpleNamespace(admin=admin, member=member, outsider=outsider, other=other,
                                 group=group, other_group=other_group)


def pytest_configure(config):
    config.addinivalue_line("markers", "ratelimit: run the test with the real rate limiter enabled")
