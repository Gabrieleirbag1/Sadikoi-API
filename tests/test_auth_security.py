"""auth/security/*: verify-device, devices, logout-devices, forgot/reset password, report-user."""
import datetime

import pytest

from db import db
from models import PasswordResetToken, ReportUserModel, UserModel, UserSecurity
from tests import factories

VERIFY = "/api/auth/security/verify-device/"
DEVICES = "/api/auth/security/devices/"
LOGOUT_DEVICES = "/api/auth/security/logout-devices/"
FORGOT = "/api/auth/security/forgot-password/"
RESET = "/api/auth/security/reset-password/"
REPORT = "/api/auth/security/report-user/"
LOGIN = "/api/auth/login/"
ACCOUNT = "/api/auth/account/"


# --------------------------------------------------------------- verify-device
class TestVerifyDevice:
    @pytest.fixture(autouse=True)
    def pending_device(self, ctx):
        with ctx():
            self.user = factories.make_user("alice", device_authorized=False)
            device = UserSecurity.query.filter_by(user_id=self.user.id).one()
            self.code = device.generate_auth_code()
            db.session.commit()

    def verify(self, client, code=None, **overrides):
        payload = {"user_info": "alice", "device_id": self.user.device_id, "code": code or self.code}
        payload.update(overrides)
        return client.post(VERIFY, json=payload)

    def test_correct_code_authorizes_device(self, anon, ctx):
        response = self.verify(anon)
        assert response.status_code == 200 and response.get_json()["success"] is True
        with ctx():
            device = UserSecurity.query.filter_by(user_id=self.user.id).one()
            assert device.authorized is True and device.auth_code is None

    def test_verified_device_can_log_in_without_captcha(self, anon, externals):
        assert self.verify(anon).status_code == 200
        response = anon.post(LOGIN, json={"username_or_email": "alice", "password": factories.PASSWORD,
                                          "device_id": self.user.device_id})
        assert response.status_code == 200
        assert externals.captcha_calls == []

    def test_by_user_id(self, anon):
        assert self.verify(anon, user_info=str(self.user.id)).status_code == 200

    def test_wrong_code_counts_attempts(self, anon, ctx):
        response = self.verify(anon, code="000000" if self.code != "000000" else "111111")
        assert response.status_code == 401
        assert "4 attempts remaining" in response.get_json()["message"]
        with ctx():
            assert UserSecurity.query.filter_by(user_id=self.user.id).one().login_attempts == 1

    def test_blocked_after_five_failures_even_with_good_code(self, anon):
        bad = "000000" if self.code != "000000" else "111111"
        for _ in range(5):
            assert self.verify(anon, code=bad).status_code == 401
        assert self.verify(anon).status_code == 429

    def test_expired_code(self, anon, ctx):
        with ctx():
            device = UserSecurity.query.filter_by(user_id=self.user.id).one()
            device.auth_code_expiration = factories.now() - datetime.timedelta(minutes=1)
            db.session.commit()
        assert self.verify(anon).status_code == 401

    def test_already_authorized_device(self, anon, ctx):
        with ctx():
            UserSecurity.query.filter_by(user_id=self.user.id).one().authorized = True
            db.session.commit()
        response = self.verify(anon, code="whatever")
        assert response.status_code == 200 and "already" in response.get_json()["message"]

    def test_unknown_user(self, anon):
        assert self.verify(anon, user_info="ghost").status_code == 404

    def test_unknown_device(self, anon):
        assert self.verify(anon, device_id="other-device").status_code == 404

    def test_missing_user_info(self, anon):
        response = anon.post(VERIFY, json={"device_id": self.user.device_id, "code": self.code})
        assert response.status_code == 400

    @pytest.mark.parametrize("user_info", [None, "", 123456789])
    def test_user_info_edge_values(self, anon, user_info):
        payload = {"user_info": user_info, "device_id": self.user.device_id, "code": self.code}
        assert anon.post(VERIFY, json=payload).status_code in (400, 404)

    @pytest.mark.parametrize("missing", ["device_id", "code"])
    def test_missing_fields(self, anon, missing):
        payload = {"user_info": "alice", "device_id": self.user.device_id, "code": self.code}
        payload.pop(missing)
        assert anon.post(VERIFY, json=payload).status_code == 400

    def test_code_of_another_user_is_useless(self, anon, ctx):
        with ctx():
            bob = factories.make_user("bob", device_authorized=False)
            bob_code = UserSecurity.query.filter_by(user_id=bob.id).one().generate_auth_code()
            db.session.commit()
        # bob's code against alice's device
        assert self.verify(anon, code=bob_code if bob_code != self.code else "999999").status_code == 401


# --------------------------------------------------------------------- devices
class TestDevices:
    @pytest.fixture(autouse=True)
    def alice_with_two_devices(self, ctx):
        with ctx():
            self.user = factories.make_user("alice")
            db.session.add(UserSecurity(user_id=self.user.id, device_id="phone", device_name="Phone",
                                        ip_address="10.0.0.1", authorized=True))
            bob = factories.make_user("bob")
            self.bob = bob
            db.session.commit()

    def test_list_devices(self, login_as):
        response = login_as(self.user).get(DEVICES)
        assert response.status_code == 200
        ids = {d["device_id"] for d in response.get_json()["content"]}
        assert ids == {self.user.device_id, "phone"}

    def test_list_devices_requires_login(self, anon):
        assert anon.get(DEVICES).status_code == 401

    def test_revoke_other_device(self, login_as, ctx):
        client = login_as(self.user)
        assert client.delete(DEVICES, json={"device_id": "phone"}).status_code == 200
        with ctx():
            assert UserSecurity.query.filter_by(user_id=self.user.id, device_id="phone").first() is None
        # current session is untouched
        assert client.get(DEVICES).status_code == 200

    def test_revoke_current_device_logs_out(self, login_as):
        client = login_as(self.user)
        assert client.delete(DEVICES, json={"device_id": self.user.device_id}).status_code == 200
        assert client.get(DEVICES).status_code == 401

    def test_revoke_unknown_device(self, login_as):
        assert login_as(self.user).delete(DEVICES, json={"device_id": "ghost"}).status_code == 404

    def test_revoke_requires_device_id(self, login_as):
        assert login_as(self.user).delete(DEVICES, json={}).status_code == 400

    def test_cannot_revoke_someone_elses_device(self, login_as, ctx):
        response = login_as(self.user).delete(DEVICES, json={"device_id": self.bob.device_id})
        assert response.status_code == 404
        with ctx():
            assert UserSecurity.query.filter_by(user_id=self.bob.id).count() == 1

    def test_logout_all_devices(self, login_as):
        client = login_as(self.user)
        assert client.get(LOGOUT_DEVICES).status_code == 200
        assert client.get(DEVICES).status_code == 401
        # a second session of the same user (same session_version) is invalidated too
        assert login_as(self.user).get(DEVICES).status_code == 401

    def test_logout_all_devices_requires_login(self, anon):
        assert anon.get(LOGOUT_DEVICES).status_code == 401


# --------------------------------------------------------------- forgot / reset
class TestForgotPassword:
    @pytest.fixture(autouse=True)
    def alice(self, ctx):
        with ctx():
            self.user = factories.make_user("alice")

    def forgot(self, client, email="alice@example.com", **extra):
        return client.post(FORGOT, json={"email": email, "captcha_token": "ok", **extra})

    def test_sends_link(self, anon, externals):
        response = self.forgot(anon)
        assert response.status_code == 200
        assert externals.emails[-1]["to"] == "alice@example.com"
        assert "/reset-password/" in externals.reset_links[-1]

    def test_unknown_email_gives_same_answer_and_sends_nothing(self, anon, externals):
        known = self.forgot(anon)
        unknown = self.forgot(anon, email="ghost@example.com")
        assert unknown.status_code == known.status_code == 200
        assert unknown.get_json() == known.get_json()
        assert len(externals.emails) == 1

    def test_deleted_user_gets_nothing(self, anon, externals, ctx):
        with ctx():
            factories.make_user("zombie", deleted=True)
        assert self.forgot(anon, email="zombie@example.com").status_code == 200
        assert externals.emails == []

    def test_cooldown_between_requests(self, anon, externals, ctx):
        self.forgot(anon)
        self.forgot(anon)
        assert len(externals.emails) == 1
        with ctx():
            assert PasswordResetToken.query.count() == 1

    def test_new_request_invalidates_previous_token(self, anon, externals, ctx):
        self.forgot(anon)
        with ctx():
            token = PasswordResetToken.query.one()
            token.created_at = factories.now() - datetime.timedelta(minutes=5)
            db.session.commit()
        self.forgot(anon)
        with ctx():
            tokens = PasswordResetToken.query.order_by(PasswordResetToken.id).all()
            assert [t.used for t in tokens] == [True, False]

    def test_email_required(self, anon):
        assert anon.post(FORGOT, json={"captcha_token": "ok"}).status_code == 400

    def test_captcha_required(self, anon, externals):
        response = anon.post(FORGOT, json={"email": "alice@example.com"})
        assert response.status_code == 400
        assert externals.emails == []

    def test_captcha_rejected(self, anon, externals):
        externals.captcha_success = False
        assert self.forgot(anon).status_code == 400
        assert externals.emails == []


class TestResetPassword:
    @pytest.fixture(autouse=True)
    def requested_reset(self, ctx, anon, externals):
        with ctx():
            self.user = factories.make_user("alice")
        anon.post(FORGOT, json={"email": "alice@example.com", "captcha_token": "ok"})
        self.token = externals.reset_links[-1].rsplit("/", 1)[1]

    def reset(self, client, token=None, password="N3wPassw0rd!", confirm=None):
        return client.post(RESET, json={"token": token or self.token, "password": password,
                                        "confirm_password": confirm or password})

    def test_reset_changes_password(self, anon):
        assert self.reset(anon).status_code == 200
        ok = anon.post(LOGIN, json={"username_or_email": "alice", "password": "N3wPassw0rd!",
                                    "device_id": self.user.device_id})
        assert ok.status_code == 200
        old = anon.post(LOGIN, json={"username_or_email": "alice", "password": factories.PASSWORD,
                                     "device_id": self.user.device_id})
        assert old.status_code == 401

    def test_token_is_single_use(self, anon):
        assert self.reset(anon).status_code == 200
        assert self.reset(anon).status_code == 400

    def test_existing_sessions_are_invalidated(self, anon, login_as):
        client = login_as(self.user)
        assert client.get(DEVICES).status_code == 200
        self.reset(anon)
        assert client.get(DEVICES).status_code == 401

    def test_expired_token(self, anon, ctx):
        with ctx():
            token = PasswordResetToken.query.one()
            token.expiration_date = factories.now() - datetime.timedelta(minutes=1)
            db.session.commit()
        assert self.reset(anon).status_code == 400

    def test_unknown_token(self, anon):
        assert self.reset(anon, token="nope").status_code == 400

    def test_password_mismatch(self, anon):
        assert self.reset(anon, password="a", confirm="b").status_code == 400

    @pytest.mark.parametrize("payload", [{"password": "x", "confirm_password": "x"}, {"token": "t"}, {}])
    def test_missing_fields(self, anon, payload):
        assert anon.post(RESET, json=payload).status_code == 400

    def test_deleted_user_cannot_reset(self, anon, ctx):
        with ctx():
            UserModel.query.get(self.user.id).deleted = True
            db.session.commit()
        assert self.reset(anon).status_code == 400


# ----------------------------------------------------------------- report-user
class TestReportUser:
    @pytest.fixture(autouse=True)
    def users(self, ctx):
        with ctx():
            self.alice = factories.make_user("alice")
            self.bob = factories.make_user("bob")

    def test_report_by_username(self, login_as, ctx):
        response = login_as(self.alice).post(REPORT, json={"reported_user_info": "bob", "reason": "spam"})
        assert response.status_code == 200
        with ctx():
            report = ReportUserModel.query.one()
            assert (report.reporter_id, report.reported_id, report.reason) == (self.alice.id, self.bob.id, "spam")

    def test_report_by_id_with_context(self, login_as, ctx):
        response = login_as(self.alice).post(REPORT, json={"reported_user_info": str(self.bob.id), "reason": "rude",
                                                           "group_id": 3, "message_id": 7})
        assert response.status_code == 200
        with ctx():
            report = ReportUserModel.query.one()
            assert (report.group_id, report.message_id) == (3, 7)

    def test_unknown_user(self, login_as):
        response = login_as(self.alice).post(REPORT, json={"reported_user_info": "ghost", "reason": "x"})
        assert response.status_code == 404

    def test_requires_login(self, anon):
        assert anon.post(REPORT, json={"reported_user_info": "bob"}).status_code == 401
