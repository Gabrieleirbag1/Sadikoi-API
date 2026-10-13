"""The before_request guard: which routes are public, and every way a session can be refused."""
import pytest

from db import db
from models import UserModel, UserSecurity
from tests import factories

PROTECTED = "/api/groups/user/"


@pytest.fixture
def alice(ctx):
    with ctx():
        return factories.make_user("alice")


def test_no_session_is_unauthorized(anon):
    response = anon.get(PROTECTED)
    assert response.status_code == 401
    assert response.get_json()["success"] is False


def test_valid_session_passes(login_as, alice):
    assert login_as(alice).get(PROTECTED).status_code == 200


def test_stale_session_version_is_forced_out(login_as, alice, ctx):
    with ctx():
        UserModel.query.get(alice.id).session_version = 5
        db.session.commit()
    client = login_as(alice, session_version=4)
    response = client.get(PROTECTED)
    assert response.status_code == 401 and "invalidated" in response.get_json()["message"]
    # and the session was cleared: even a request that would now be fine stays refused
    assert client.get(PROTECTED).status_code == 401


def test_current_session_version_passes(login_as, alice, ctx):
    with ctx():
        UserModel.query.get(alice.id).session_version = 5
        db.session.commit()
    assert login_as(alice, session_version=5).get(PROTECTED).status_code == 200


def test_deleted_user_is_forced_out(login_as, alice, ctx):
    with ctx():
        UserModel.query.get(alice.id).deleted = True
        db.session.commit()
    assert login_as(alice).get(PROTECTED).status_code == 401


def test_unauthorized_device_is_forced_out(login_as, alice, ctx):
    with ctx():
        UserSecurity.query.filter_by(user_id=alice.id).one().authorized = False
        db.session.commit()
    response = login_as(alice).get(PROTECTED)
    assert response.status_code == 401 and "Device revoked" in response.get_json()["message"]


def test_unknown_device_in_session_is_forced_out(login_as, alice):
    assert login_as(alice, device_id="not-a-device").get(PROTECTED).status_code == 401


def test_session_without_device_is_forced_out(app, alice):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(alice.id)
        sess["session_version"] = 0
    assert client.get(PROTECTED).status_code == 401


@pytest.mark.parametrize("method,path", [
    ("post", "/api/auth/login/"),
    ("post", "/api/auth/register/"),
    ("post", "/api/auth/google/"),
    ("post", "/api/auth/security/forgot-password/"),
    ("post", "/api/auth/security/reset-password/"),
])
def test_public_routes_do_not_require_a_session(anon, method, path):
    # They reach their handler (any answer except the guard's 401 "Unauthorized access")
    response = getattr(anon, method)(path, json={})
    assert response.status_code != 401


def test_verify_device_is_public(anon):
    response = anon.post("/api/auth/security/verify-device/", json={"user_info": "ghost", "device_id": "d", "code": "1"})
    assert response.status_code == 404


@pytest.mark.parametrize("method,path", [
    ("post", "/api/auth/logout/"),
    ("post", "/api/auth/account/"),
    ("put", "/api/auth/account/"),
    ("delete", "/api/auth/account/1"),
    ("get", "/api/auth/security/devices/"),
    ("delete", "/api/auth/security/devices/"),
    ("get", "/api/auth/security/logout-devices/"),
    ("post", "/api/auth/security/report-user/"),
    ("post", "/api/groups/"),
    ("get", "/api/groups/1/"),
    ("put", "/api/groups/1/"),
    ("delete", "/api/groups/1/"),
    ("get", "/api/groups/user/"),
    ("post", "/api/groups/1/role/"),
    ("get", "/api/groups/1/invitations/"),
    ("post", "/api/groups/invitations/abc/"),
    ("delete", "/api/groups/1/2/"),
    ("get", "/api/groups/1/messages/"),
    ("post", "/api/groups/1/messages/"),
    ("get", "/api/questions/1/"),
    ("get", "/api/questions/1/1/2026/"),
    ("post", "/api/questions/1/vote/"),
    ("post", "/api/feedback/bug-reports/"),
    ("post", "/api/feedback/suggestions/"),
])
def test_every_other_route_requires_a_session(anon, method, path):
    response = getattr(anon, method)(path, json={})
    assert response.status_code == 401


def test_options_preflight_is_not_blocked(anon):
    response = anon.options(PROTECTED, headers={"Origin": "http://localhost:4200",
                                                "Access-Control-Request-Method": "GET"})
    assert response.status_code in (200, 204)


def test_profile_pictures_are_public(anon, app):
    import os
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with open(os.path.join(app.config["UPLOAD_FOLDER"], "pic.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    response = anon.get("/api/auth/profile-picture/pic.png")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_profile_picture_missing_is_404(anon):
    assert anon.get("/api/auth/profile-picture/nope.png").status_code == 404


def test_profile_picture_path_traversal_is_blocked(anon):
    assert anon.get("/api/auth/profile-picture/..%2F..%2Fconfig.py").status_code in (404, 400)
