"""POST auth/register/, auth/login/, auth/google/, auth/logout/, auth/account/ (POST, PUT), DELETE auth/account/<id>."""
import datetime
import io

import pytest

import auth
from models import UserModel, UserSecurity
from tests import factories

REGISTER = "/api/auth/register/"
LOGIN = "/api/auth/login/"
GOOGLE = "/api/auth/google/"
LOGOUT = "/api/auth/logout/"
ACCOUNT = "/api/auth/account/"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def register_payload(**overrides):
    payload = {"username": "newbie", "email": "newbie@example.com", "password": "Passw0rd!",
               "confirm_password": "Passw0rd!", "device_id": "dev-new", "device_name": "pytest",
               "login": False, "language": "fr-FR", "captcha_token": "ok"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ register
class TestRegister:
    def test_register_json_without_login(self, anon, ctx):
        response = anon.post(REGISTER, json=register_payload())
        assert response.status_code == 201
        body = response.get_json()
        assert body["success"] is True
        assert body["content"]["username"] == "newbie"
        assert "password" not in body["content"]
        with ctx():
            user = UserModel.query.filter_by(username="newbie").one()
            assert user.language == "fr"  # "fr-FR" is reduced to the primary subtag
            assert user.password != "Passw0rd!"

    def test_register_form_data(self, anon):
        payload = register_payload(login="false")
        response = anon.post(REGISTER, data=payload, content_type="multipart/form-data")
        assert response.status_code == 201

    def test_register_with_valid_profile_picture(self, anon, ctx):
        payload = register_payload(profile_picture=(io.BytesIO(PNG), "me.png"))
        response = anon.post(REGISTER, data=payload, content_type="multipart/form-data")
        assert response.status_code == 201
        with ctx():
            assert UserModel.query.filter_by(username="newbie").one().profile_picture.endswith(".png")

    def test_register_ignores_fake_image(self, anon, ctx):
        payload = register_payload(profile_picture=(io.BytesIO(b"<?php echo 1; ?>"), "shell.png"))
        response = anon.post(REGISTER, data=payload, content_type="multipart/form-data")
        assert response.status_code == 201
        with ctx():
            assert UserModel.query.filter_by(username="newbie").one().profile_picture is None

    def test_register_ignores_disallowed_extension(self, anon, ctx):
        payload = register_payload(profile_picture=(io.BytesIO(PNG), "me.exe"))
        response = anon.post(REGISTER, data=payload, content_type="multipart/form-data")
        assert response.status_code == 201
        with ctx():
            assert UserModel.query.filter_by(username="newbie").one().profile_picture is None

    def test_password_mismatch(self, anon):
        response = anon.post(REGISTER, json=register_payload(confirm_password="nope"))
        assert response.status_code == 400

    @pytest.mark.parametrize("missing", ["username", "email", "password"])
    def test_missing_required_field(self, anon, missing):
        payload = register_payload()
        payload[missing] = ""
        if missing == "password":
            payload["confirm_password"] = ""
        assert anon.post(REGISTER, json=payload).status_code == 400

    def test_username_too_long(self, anon):
        response = anon.post(REGISTER, json=register_payload(username="x" * 41))
        assert response.status_code == 400

    def test_email_too_long(self, anon):
        response = anon.post(REGISTER, json=register_payload(email="x" * 70 + "@example.com"))
        assert response.status_code == 400

    def test_duplicate_email(self, anon, ctx):
        with ctx():
            factories.make_user("taken", email="newbie@example.com")
        assert anon.post(REGISTER, json=register_payload()).status_code in (400, 409)

    def test_duplicate_username(self, anon, ctx):
        with ctx():
            factories.make_user("newbie", email="other@example.com")
        assert anon.post(REGISTER, json=register_payload()).status_code in (400, 409)

    def test_duplicate_email_is_case_exact_and_creates_nothing(self, anon, ctx):
        with ctx():
            factories.make_user("taken", email="newbie@example.com")
        response = anon.post(REGISTER, json=register_payload())
        assert response.status_code == 409 and "Email" in response.get_json()["message"]
        with ctx():
            assert UserModel.query.count() == 1

    def test_username_of_a_deleted_account_stays_reserved(self, anon, ctx):
        with ctx():
            factories.make_user("newbie", email="gone@example.com", deleted=True)
        assert anon.post(REGISTER, json=register_payload()).status_code == 409

    def test_login_true_without_device_id_creates_account_only(self, anon):
        response = anon.post(REGISTER, json=register_payload(login=True, device_id=None))
        assert response.status_code == 201
        assert "Could not login" in response.get_json()["message"]

    def test_login_true_new_device_requires_verification(self, anon, externals, ctx):
        response = anon.post(REGISTER, json=register_payload(login=True))
        assert response.status_code == 203
        assert response.get_json()["requires_verification"] is True
        assert len(externals.emails) == 1 and len(externals.emails[0]["code"]) == 6
        with ctx():
            device = UserSecurity.query.filter_by(device_id="dev-new").one()
            assert device.authorized is False

    def test_captcha_required(self, anon):
        payload = register_payload()
        payload.pop("captcha_token")
        response = anon.post(REGISTER, json=payload)
        assert response.status_code == 400
        assert "Captcha" in response.get_json()["message"]

    def test_captcha_rejected_creates_nothing(self, anon, externals, ctx):
        externals.captcha_success = False
        assert anon.post(REGISTER, json=register_payload()).status_code == 400
        with ctx():
            assert UserModel.query.count() == 0


# --------------------------------------------------------------------- login
class TestLogin:
    def login(self, client, username="alice", password=factories.PASSWORD, **extra):
        payload = {"username_or_email": username, "password": password, "device_id": "dev-alice",
                   "device_name": "pytest", "remember": False, **extra}
        return client.post(LOGIN, json=payload)

    @pytest.fixture(autouse=True)
    def alice(self, ctx):
        with ctx():
            self.user = factories.make_user("alice")

    def test_login_by_username_from_known_device_needs_no_captcha(self, anon, externals):
        response = self.login(anon)
        assert response.status_code == 200
        assert response.get_json()["content"]["username"] == "alice"
        assert externals.captcha_calls == []

    def test_login_by_email(self, anon):
        assert self.login(anon, username="alice@example.com").status_code == 200

    def test_session_is_usable_after_login(self, anon):
        assert self.login(anon).status_code == 200
        response = anon.post(ACCOUNT, json={"device_id": "dev-alice"})
        assert response.status_code == 200
        assert response.get_json()["content"]["username"] == "alice"

    def test_wrong_password(self, anon):
        assert self.login(anon, password="wrong").status_code == 401

    def test_unknown_user(self, anon):
        # With a captcha the credentials are checked: 401. Without one an unknown account is
        # indistinguishable from a known one on a new device: captcha required (no enumeration).
        assert self.login(anon, username="ghost", captcha_token="ok").status_code == 401
        assert self.login(anon, username="ghost").status_code == 400

    def test_deleted_user_cannot_login(self, anon, ctx):
        with ctx():
            factories.make_user("zombie", deleted=True)
        response = anon.post(LOGIN, json={"username_or_email": "zombie", "password": factories.PASSWORD,
                                          "device_id": "dev-zombie", "captcha_token": "ok"})
        assert response.status_code == 401

    @pytest.mark.parametrize("payload", [{"username_or_email": "alice"}, {"password": factories.PASSWORD}, {}])
    def test_missing_fields(self, anon, payload):
        assert anon.post(LOGIN, json={**payload, "captcha_token": "ok"}).status_code == 400

    def test_unknown_device_without_captcha_is_refused(self, anon):
        response = self.login(anon, device_id="brand-new")
        assert response.status_code == 400
        assert "Captcha" in response.get_json()["message"]

    def test_new_device_with_captcha_gets_a_code(self, anon, externals, ctx):
        response = self.login(anon, device_id="brand-new", captcha_token="ok")
        assert response.status_code == 203
        assert externals.emails[-1]["to"] == "alice@example.com"
        with ctx():
            assert UserSecurity.query.filter_by(device_id="brand-new").one().authorized is False

    def test_missing_device_id(self, anon):
        response = anon.post(LOGIN, json={"username_or_email": "alice", "password": factories.PASSWORD,
                                          "captcha_token": "ok"})
        assert response.status_code == 400

    def test_stale_device_requires_reauthorization(self, anon, ctx, externals):
        with ctx():
            device = UserSecurity.query.filter_by(device_id="dev-alice").one()
            device.last_login = factories.now() - datetime.timedelta(days=61)
            from db import db
            db.session.commit()
        response = self.login(anon, captcha_token="ok")
        assert response.status_code == 203
        assert externals.emails

    def test_unauthorized_known_device_with_captcha_gets_a_code(self, anon, ctx, externals):
        with ctx():
            factories.make_user("bob", device_authorized=False)
        response = anon.post(LOGIN, json={"username_or_email": "bob", "password": factories.PASSWORD,
                                          "device_id": "dev-bob", "captcha_token": "ok"})
        assert response.status_code == 203

    def test_wrong_password_does_not_leak_through_captcha_exemption(self, anon):
        # Known authorized device + wrong password: still a plain 401.
        assert self.login(anon, password="nope").status_code == 401

    def test_captcha_failure_blocks_before_password_check(self, anon, externals):
        externals.captcha_success = False
        response = self.login(anon, device_id="brand-new", captcha_token="bad")
        assert response.status_code == 400

    def test_cloudflare_unreachable_fails_closed(self, anon, externals):
        import requests
        externals.captcha_raises = requests.ConnectionError("down")
        response = self.login(anon, device_id="brand-new", captcha_token="ok")
        assert response.status_code == 503

    def test_missing_server_secret_fails_closed(self, anon, monkeypatch):
        monkeypatch.setattr(auth, "TURNSTILE_SECRET_KEY", None)
        response = self.login(anon, device_id="brand-new", captcha_token="ok")
        assert response.status_code == 500

    def test_captcha_is_checked_against_cloudflare_with_secret_and_ip(self, anon, externals):
        self.login(anon, device_id="brand-new", captcha_token="tok-123")
        call = externals.captcha_calls[0]
        assert call["url"] == auth.TURNSTILE_VERIFY_URL
        assert call["data"]["secret"] == "test-secret" and call["data"]["response"] == "tok-123"
        assert call["data"]["remoteip"] == "127.0.0.1"


# -------------------------------------------------------------------- google
class TestGoogle:
    @pytest.fixture(autouse=True)
    def google_config(self, monkeypatch):
        monkeypatch.setattr(auth, "GOOGLE_CLIENT_BROWSER_ID", "client-id")
        monkeypatch.setattr(auth, "GOOGLE_CLIENT_MOBILE_ID", None)

    def fake_verify(self, monkeypatch, info=None, error=None, expected_audiences=("client-id",)):
        def verify(token, request, audiences):
            if error:
                raise error
            assert list(audiences) == list(expected_audiences)
            return info
        monkeypatch.setattr(auth.id_token, "verify_oauth2_token", verify)

    def test_missing_server_config(self, anon, monkeypatch):
        monkeypatch.setattr(auth, "GOOGLE_CLIENT_BROWSER_ID", None)
        assert anon.post(GOOGLE, json={"token": "t"}).status_code == 500

    def test_mobile_client_id_is_also_accepted(self, anon, monkeypatch):
        monkeypatch.setattr(auth, "GOOGLE_CLIENT_MOBILE_ID", "mobile-id")
        self.fake_verify(monkeypatch, {"email": "gina@gmail.com", "name": "Gina"}, expected_audiences=("client-id", "mobile-id"))
        assert anon.post(GOOGLE, json={"token": "t", "device_id": "g-dev"}).status_code == 200

    def test_missing_token(self, anon):
        assert anon.post(GOOGLE, json={}).status_code == 400

    def test_invalid_token(self, anon, monkeypatch):
        self.fake_verify(monkeypatch, error=ValueError("bad"))
        assert anon.post(GOOGLE, json={"token": "t", "device_id": "d"}).status_code == 401

    def test_creates_account_and_logs_in(self, anon, monkeypatch, ctx):
        self.fake_verify(monkeypatch, {"email": "gina@gmail.com", "name": "Gina", "locale": "fr-FR"})
        response = anon.post(GOOGLE, json={"token": "t", "device_id": "g-dev", "device_name": "pytest"})
        assert response.status_code == 200
        with ctx():
            user = UserModel.query.filter_by(email="gina@gmail.com").one()
            assert user.username == "Gina" and user.language == "fr"
            assert UserSecurity.query.filter_by(user_id=user.id, device_id="g-dev").one().authorized is True
        assert anon.post(ACCOUNT, json={"device_id": "g-dev"}).status_code == 200

    def test_name_collision_gets_a_unique_username(self, anon, monkeypatch, ctx):
        with ctx():
            factories.make_user("Gina", email="someone-else@example.com")
        self.fake_verify(monkeypatch, {"email": "gina@gmail.com", "name": "Gina"})
        assert anon.post(GOOGLE, json={"token": "t", "device_id": "g-dev"}).status_code == 200
        with ctx():
            user = UserModel.query.filter_by(email="gina@gmail.com").one()
            assert user.username != "Gina" and user.username.startswith("Gina_")

    def test_existing_account(self, anon, monkeypatch, ctx):
        with ctx():
            factories.make_user("gina", email="gina@gmail.com")
        self.fake_verify(monkeypatch, {"email": "gina@gmail.com", "name": "Whatever"})
        assert anon.post(GOOGLE, json={"token": "t", "device_id": "g-dev"}).status_code == 200
        with ctx():
            assert UserModel.query.count() == 1


# ------------------------------------------------------------ account / logout
class TestAccount:
    @pytest.fixture(autouse=True)
    def alice(self, ctx):
        with ctx():
            self.user = factories.make_user("alice")

    def test_get_user(self, login_as):
        response = login_as(self.user).post(ACCOUNT, json={"device_id": self.user.device_id})
        assert response.status_code == 200
        assert response.get_json()["content"]["email"] == "alice@example.com"

    def test_get_user_requires_device_id(self, login_as):
        assert login_as(self.user).post(ACCOUNT, json={}).status_code == 400

    def test_get_user_unknown_device(self, login_as):
        assert login_as(self.user).post(ACCOUNT, json={"device_id": "nope"}).status_code == 404

    def test_get_user_unauthorized_device(self, login_as, ctx):
        with ctx():
            from db import db
            UserSecurity.query.filter_by(user_id=self.user.id).one().authorized = False
            db.session.commit()
        # the session guard already rejects an unauthorized current device
        assert login_as(self.user).post(ACCOUNT, json={"device_id": self.user.device_id}).status_code == 401

    def test_get_user_requires_login(self, anon):
        assert anon.post(ACCOUNT, json={"device_id": "x"}).status_code == 401

    def test_update_profile_fields(self, login_as, ctx):
        response = login_as(self.user).put(ACCOUNT, json={"username": "alice2", "email": "a2@example.com",
                                                          "language": "fr-FR"})
        assert response.status_code == 200
        with ctx():
            user = UserModel.query.get(self.user.id)
            assert (user.username, user.email, user.language) == ("alice2", "a2@example.com", "fr")

    def test_update_password_logs_everyone_out(self, login_as, ctx):
        client = login_as(self.user)
        response = client.put(ACCOUNT, json={"password": "N3wPassw0rd!", "confirm_password": "N3wPassw0rd!"})
        assert response.status_code == 200
        # session_version bumped + devices prohibited -> the same session is refused afterwards
        assert client.post(ACCOUNT, json={"device_id": self.user.device_id}).status_code == 401
        with ctx():
            assert UserSecurity.query.filter_by(user_id=self.user.id).one().authorized is False

    def test_update_password_mismatch(self, login_as):
        response = login_as(self.user).put(ACCOUNT, json={"password": "a", "confirm_password": "b"})
        assert response.status_code == 400

    def test_update_username_too_long(self, login_as):
        assert login_as(self.user).put(ACCOUNT, json={"username": "x" * 41}).status_code == 400

    def test_delete_own_account(self, login_as, anon, ctx):
        client = login_as(self.user)
        assert client.delete(f"{ACCOUNT}{self.user.id}").status_code == 200
        with ctx():
            assert UserModel.query.get(self.user.id).deleted is True
        assert client.post(ACCOUNT, json={"device_id": self.user.device_id}).status_code == 401
        response = anon.post(LOGIN, json={"username_or_email": "alice", "password": factories.PASSWORD,
                                          "device_id": self.user.device_id, "captcha_token": "ok"})
        assert response.status_code == 401

    def test_delete_other_account_forbidden(self, login_as, ctx):
        with ctx():
            bob = factories.make_user("bob")
        assert login_as(self.user).delete(f"{ACCOUNT}{bob.id}").status_code == 403
        with ctx():
            assert UserModel.query.get(bob.id).deleted is False

    def test_delete_unknown_account(self, login_as):
        assert login_as(self.user).delete(f"{ACCOUNT}999999").status_code == 404

    def test_logout(self, login_as):
        client = login_as(self.user)
        response = client.post(LOGOUT, json={"device_id": self.user.device_id})
        assert response.status_code == 200
        assert client.post(ACCOUNT, json={"device_id": self.user.device_id}).status_code == 401

    def test_logout_forget_device(self, login_as, ctx):
        response = login_as(self.user).post(LOGOUT, json={"device_id": self.user.device_id, "forget_device": True})
        assert response.status_code == 200
        with ctx():
            assert UserSecurity.query.filter_by(user_id=self.user.id).one().authorized is False

    def test_logout_requires_login(self, anon):
        assert anon.post(LOGOUT, json={}).status_code == 401
