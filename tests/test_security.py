"""Rate limiting, proxy-aware client IP, security headers, CORS, body size."""
import io

import pytest

import auth
from tests import factories

LOGIN = "/api/auth/login/"
FORGOT = "/api/auth/security/forgot-password/"
REGISTER = "/api/auth/register/"
VERIFY = "/api/auth/security/verify-device/"
REPORT = "/api/auth/security/report-user/"
ALLOWED_ORIGIN = "https://sadikoi.missclick.net"


def bad_login(client, username="alice", **headers):
    return client.post(LOGIN, json={"username_or_email": username, "password": "x", "device_id": "d",
                                    "captcha_token": "ok"}, headers=headers)


# ------------------------------------------------------------------ rate limit
@pytest.mark.ratelimit
class TestRateLimits:
    def test_login_is_limited_per_account(self, anon):
        codes = [bad_login(anon).status_code for _ in range(7)]
        assert codes[:5] == [401] * 5
        assert codes[5:] == [429, 429]

    def test_account_limit_does_not_block_other_accounts(self, anon):
        for _ in range(6):
            bad_login(anon, "alice")
        assert bad_login(anon, "bob").status_code == 401

    def test_login_is_limited_per_ip(self, anon):
        codes = [bad_login(anon, f"user{i}").status_code for i in range(12)]
        assert codes[:10] == [401] * 10
        assert codes[10:] == [429, 429]

    def test_429_is_json_with_retry_after(self, anon):
        for _ in range(5):
            bad_login(anon)
        response = bad_login(anon)
        assert response.status_code == 429
        assert response.get_json()["success"] is False
        assert int(response.headers["Retry-After"]) > 0

    def test_spoofed_forwarded_for_does_not_reset_the_counter(self, anon):
        for _ in range(5):
            bad_login(anon)
        # Apache appends the real peer last; entries a client prepends are ignored (ProxyFix x_for=1).
        response = bad_login(anon, **{"X-Forwarded-For": "1.2.3.4, 127.0.0.1"})
        assert response.status_code == 429

    def test_other_real_client_ip_has_its_own_budget(self, anon):
        for i in range(10):
            bad_login(anon, f"user{i}")
        assert bad_login(anon, "fresh").status_code == 429
        # a different peer address, as appended by the reverse proxy
        assert bad_login(anon, "fresh", **{"X-Forwarded-For": "203.0.113.9"}).status_code == 401

    def test_forgot_password_three_per_hour(self, anon):
        codes = [anon.post(FORGOT, json={"email": f"u{i}@example.com", "captcha_token": "ok"}).status_code
                 for i in range(4)]
        assert codes == [200, 200, 200, 429]

    def test_forgot_password_is_limited_per_email(self, anon):
        codes = [anon.post(FORGOT, json={"email": "same@example.com", "captcha_token": "ok"},
                           headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(4)]
        assert codes == [200, 200, 200, 429]

    def test_register_five_per_hour(self, anon):
        codes = [anon.post(REGISTER, json={"username": f"u{i}", "email": f"u{i}@example.com", "password": "p",
                                           "confirm_password": "p", "captcha_token": "ok"}).status_code
                 for i in range(6)]
        assert codes[:5] == [201] * 5 and codes[5] == 429

    def test_verify_device_is_limited(self, anon):
        codes = [anon.post(VERIFY, json={"user_info": f"ghost{i}", "device_id": "d", "code": "1"}).status_code
                 for i in range(12)]
        assert codes[:10] == [404] * 10 and codes[10] == 429

    def test_authenticated_limits_are_per_user(self, login_as, ctx):
        with ctx():
            alice, bob = factories.make_user("alice"), factories.make_user("bob")
        payload = {"reported_user_info": "bob", "reason": "x"}
        alice_codes = [login_as(alice).post(REPORT, json=payload).status_code for _ in range(6)]
        assert alice_codes[:5] == [200] * 5 and alice_codes[5] == 429
        payload_bob = {"reported_user_info": "alice", "reason": "x"}
        assert login_as(bob).post(REPORT, json=payload_bob).status_code == 200

    def test_messages_30_per_minute(self, login_as, world, ctx):
        client = login_as(world.member)
        codes = [client.post(f"/api/groups/{world.group.id}/messages/", json={"content": str(i)}).status_code
                 for i in range(31)]
        assert codes[:30] == [201] * 30 and codes[30] == 429


def test_limits_are_inactive_in_the_default_test_configuration(anon):
    assert all(bad_login(anon).status_code == 401 for _ in range(12))


# --------------------------------------------------------------------- headers
class TestSecurityHeaders:
    def test_headers_on_json_responses(self, anon):
        response = anon.get("/api/groups/user/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "max-age=" in response.headers["Strict-Transport-Security"]
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Cache-Control"] == "no-store"

    def test_headers_on_errors_and_404(self, anon):
        response = anon.get("/api/does-not-exist/")
        assert response.status_code in (401, 404)
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_headers_on_authenticated_responses(self, login_as, world):
        response = login_as(world.admin).get("/api/groups/user/")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"


# ------------------------------------------------------------------------ CORS
class TestCors:
    def test_allowed_origin_gets_credentials(self, anon):
        response = anon.get("/api/groups/user/", headers={"Origin": ALLOWED_ORIGIN})
        assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
        assert response.headers["Access-Control-Allow-Credentials"] == "true"

    def test_local_dev_origin(self, anon):
        response = anon.get("/api/groups/user/", headers={"Origin": "http://localhost:4200"})
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:4200"

    @pytest.mark.parametrize("origin", ["https://evil.example", "http://sadikoi.missclick.net.evil.example", "null"])
    def test_other_origins_get_no_cors_headers(self, anon, origin):
        response = anon.get("/api/groups/user/", headers={"Origin": origin})
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_preflight_from_evil_origin(self, anon):
        response = anon.options(LOGIN, headers={"Origin": "https://evil.example",
                                                "Access-Control-Request-Method": "POST"})
        assert "Access-Control-Allow-Origin" not in response.headers


# ------------------------------------------------------------- request size
def test_oversized_body_is_rejected(anon):
    response = anon.post(REGISTER, data={"username": "x", "profile_picture": (io.BytesIO(b"0" * (6 * 1000 * 1000)), "big.png")},
                         content_type="multipart/form-data")
    assert response.status_code == 413


# ------------------------------------------------------------- client ip helper
class FakeRequest:
    def __init__(self, remote_addr, headers=None):
        self.remote_addr = remote_addr
        self.headers = headers or {}


def test_client_ip_ignores_forwarded_for_header():
    request = FakeRequest("10.1.1.1", {"X-Forwarded-For": "6.6.6.6"})
    assert auth.get_client_ip(request) == "10.1.1.1"


def test_client_ip_without_address():
    assert auth.get_client_ip(FakeRequest(None)) == "unknown"
