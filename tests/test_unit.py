"""Pure / near-pure logic: time windows, question choice, item winner, models, helpers."""
import datetime
import io
import types

import pytest
import requests

import auth
import chat
import question as question_module
from db import db
from items import get_most_voted_user, get_votes_per_user
from models import GroupModel, PasswordResetToken, QuestionModel, UserSecurity
from security import SocketRateLimiter, json_field_key
from tests import factories

H = datetime.timedelta


def avoid_midnight_edge():
    if factories.now().time() >= datetime.time(23, 58) or factories.now().time() <= datetime.time(0, 2):
        pytest.skip("too close to the UTC day boundary for a stable assertion")


# --------------------------------------------------- is_today_based_on_reset
class TestIsTodayBasedOnReset:
    @pytest.fixture
    def group(self):
        return types.SimpleNamespace(daily_reset_timestamp=datetime.time(0, 0))

    def at(self, date):
        return types.SimpleNamespace(date=date)

    def test_at_the_start_of_the_current_window(self, group):
        start = datetime.datetime.combine(factories.now().date(), datetime.time(0, 0), tzinfo=datetime.timezone.utc)
        assert question_module.is_today_based_on_reset(self.at(start), group) is True

    def test_one_second_before_the_window(self, group):
        start = datetime.datetime.combine(factories.now().date(), datetime.time(0, 0), tzinfo=datetime.timezone.utc)
        assert question_module.is_today_based_on_reset(self.at(start - H(seconds=1)), group) is False

    def test_naive_datetimes_are_treated_as_utc(self, group):
        naive = datetime.datetime.combine(factories.now().date(), datetime.time(0, 0))
        assert question_module.is_today_based_on_reset(self.at(naive), group) is True

    def test_nothing_is_not_today(self, group):
        assert question_module.is_today_based_on_reset(None, group) is False

    def test_before_the_reset_time_the_window_started_yesterday(self):
        avoid_midnight_edge()
        later = (factories.now() + H(hours=1)).time().replace(microsecond=0)
        if later < factories.now().time():
            pytest.skip("reset time wrapped past midnight")
        group = types.SimpleNamespace(daily_reset_timestamp=later)
        yesterday_start = datetime.datetime.combine(factories.now().date() - H(days=1), later, tzinfo=datetime.timezone.utc)
        assert question_module.is_today_based_on_reset(self.at(yesterday_start), group) is True


# -------------------------------------------------- does_exist_question_today
class TestQuestionToday:
    def test_no_question(self, world, ctx):
        with ctx():
            assert question_module.does_exist_question_today(db.session.get(GroupModel, world.group.id)) is False

    def test_question_in_current_window(self, world, ctx):
        with ctx():
            factories.make_question(world.group)
            assert question_module.does_exist_question_today(db.session.get(GroupModel, world.group.id)) is True

    def test_yesterdays_question_has_expired(self, world, ctx):
        with ctx():
            factories.make_question(world.group, days_ago=1)
            assert question_module.does_exist_question_today(db.session.get(GroupModel, world.group.id)) is False

    def test_reset_time_moved_later_extends_the_current_question(self, world, ctx):
        # Question created under a 00:00 reset yesterday; the admin then moves the reset to 23:59.
        avoid_midnight_edge()
        with ctx():
            factories.make_question(world.group, days_ago=1)
            group = db.session.get(GroupModel, world.group.id)
            group.daily_reset_timestamp = datetime.time(23, 59)
            db.session.commit()
            assert question_module.does_exist_question_today(group) is True

    def test_has_user_voted_is_tied_to_the_current_question(self, world, ctx):
        with ctx():
            old = factories.make_question(world.group, days_ago=1)
            factories.make_vote(old, world.member, [world.admin])
            group = db.session.get(GroupModel, world.group.id)
            user = db.session.get(auth.UserModel, world.member.id)
            assert question_module.does_exist_vote_today(group, user)[0] is False  # expired day: no vote "today"
            current = factories.make_question(world.group)
            voted, found = question_module.does_exist_vote_today(group, user)
            assert voted is False and found.id == current.id
            factories.make_vote(current, world.member, [world.admin])
            assert question_module.does_exist_vote_today(group, user)[0] is True


# ------------------------------------------------------ chat day windows
class TestQuestionWindow:
    def test_closed_window_ends_at_next_question(self, world, ctx):
        with ctx():
            first = factories.make_question(world.group, days_ago=5)
            second = factories.make_question(world.group, days_ago=4)
            group = db.session.get(GroupModel, world.group.id)
            start, end = chat.get_question_window(group, db.session.get(QuestionModel, first.id))
            assert (start, end) == (first.date, second.date)

    def test_gap_is_capped_at_24_hours(self, world, ctx):
        with ctx():
            first = factories.make_question(world.group, days_ago=5)
            factories.make_question(world.group, days_ago=1)
            group = db.session.get(GroupModel, world.group.id)
            _, end = chat.get_question_window(group, db.session.get(QuestionModel, first.id))
            assert end == first.date + H(hours=24)

    def test_open_window_has_no_end(self, world, ctx):
        with ctx():
            current = factories.make_question(world.group)
            group = db.session.get(GroupModel, world.group.id)
            assert chat.get_question_window(group, db.session.get(QuestionModel, current.id))[1] is None

    def test_expired_last_window_is_closed_after_24h(self, world, ctx):
        with ctx():
            last = factories.make_question(world.group, days_ago=3)
            group = db.session.get(GroupModel, world.group.id)
            assert chat.get_question_window(group, db.session.get(QuestionModel, last.id))[1] == last.date + H(hours=24)


# --------------------------------------------------------- choosing a question
class TestChooseQuestion:
    def test_prefers_the_least_asked_question(self, world, ctx):
        with ctx():
            factories.make_question(world.group, days_ago=3, question_id=1)
            factories.make_question(world.group, days_ago=2, question_id=1)
            factories.make_question(world.group, days_ago=1, question_id=2, theme="style")
            group = db.session.get(GroupModel, world.group.id)
            assert {question_module.chose_question(group)["question_id"] for _ in range(20)} == {2}

    def test_counts_per_question(self, world, ctx):
        with ctx():
            factories.make_question(world.group, days_ago=2, question_id=1)
            factories.make_question(world.group, days_ago=1, question_id=1)
            group = db.session.get(GroupModel, world.group.id)
            assert question_module.get_question_counts_by_id(group) == {1: 2}
            assert question_module.get_question_iteration_count(group, 1) == 2
            assert question_module.get_question_iteration_count(group, 2) == 0
            assert question_module.get_mean_iterations_question(group) == 2

    def test_mean_of_an_empty_group_is_one(self, world, ctx):
        with ctx():
            assert question_module.get_mean_iterations_question(db.session.get(GroupModel, world.group.id)) == 1

    def test_theme_filter(self):
        assert question_module.chose_random_question(["style"])["question_id"] == 2

    def test_no_matching_theme(self):
        with pytest.raises(StopIteration):
            question_module.chose_random_question(["nothing"])

    # TEMPORARY: remove with the RANKING filter in question.py.
    def test_ranking_questions_are_never_given(self, pool):
        pool.append({**pool[1], "question_id": 3, "type": "ranking"})
        pool.append({**pool[1], "question_id": 4, "type": "RANKING"})
        assert {question_module.chose_random_question(["style"])["question_id"] for _ in range(30)} == {2}

    # TEMPORARY: remove with the RANKING filter in question.py.
    def test_only_ranking_questions_left_raises(self, pool):
        pool[:] = [{**pool[1], "type": "ranking"}]
        with pytest.raises(StopIteration):
            question_module.chose_random_question(["style"])


# -------------------------------------------------------------------- items
class TestItems:
    def test_most_voted_user(self, world, ctx):
        with ctx():
            q = factories.make_question(world.group)
            factories.make_vote(q, world.admin, [world.member])
            factories.make_vote(q, world.member, [world.member])
            group = db.session.get(GroupModel, world.group.id)
            winner = get_most_voted_user(db.session.get(QuestionModel, q.id), group)
            assert winner["id"] == world.member.id

    def test_tie_has_no_winner(self, world, ctx):
        with ctx():
            q = factories.make_question(world.group)
            factories.make_vote(q, world.admin, [world.member])
            factories.make_vote(q, world.member, [world.admin])
            group = db.session.get(GroupModel, world.group.id)
            assert get_most_voted_user(db.session.get(QuestionModel, q.id), group) is None

    def test_no_votes_has_no_winner(self, world, ctx):
        with ctx():
            q = factories.make_question(world.group)
            group = db.session.get(GroupModel, world.group.id)
            assert get_most_voted_user(db.session.get(QuestionModel, q.id), group) is None

    def test_votes_per_user_sorted_descending_and_includes_zero(self, world, ctx):
        with ctx():
            q = factories.make_question(world.group, limit=0)
            factories.make_vote(q, world.admin, [world.member])
            factories.make_vote(q, world.member, [world.member, world.admin])
            group = db.session.get(GroupModel, world.group.id)
            result = get_votes_per_user(db.session.get(QuestionModel, q.id), group)
            assert [u["username"] for u in result["users"]] == ["member", "admin"]
            assert result["number_of_votes"] == [2, 1]


# ------------------------------------------------------------------- models
class TestUserSecurityModel:
    def device(self, **kwargs):
        return UserSecurity(user_id=1, device_id="d", device_name="n", ip_address="1.1.1.1", **kwargs)

    def test_generate_and_validate_code(self):
        device = self.device(authorized=True)
        code = device.generate_auth_code()
        assert len(code) == 6 and code.isdigit()
        assert device.authorized is False and device.login_attempts == 0
        assert device.is_code_valid(code) is True
        assert device.is_code_valid("not-it") is False

    def test_code_expires(self):
        device = self.device()
        code = device.generate_auth_code(ttl_minutes=-1)
        assert device.is_code_valid(code) is False

    def test_no_code_never_validates(self):
        assert self.device().is_code_valid("000000") is False

    def test_clear_code(self):
        device = self.device()
        device.generate_auth_code()
        device.login_attempts = 3
        device.clear_auth_code()
        assert (device.auth_code, device.auth_code_expiration, device.login_attempts) == (None, None, 0)

    @pytest.mark.parametrize("authorized,days,expected", [
        (False, 0, True), (True, 0, False), (True, 59, False), (True, 61, True),
    ])
    def test_needs_reauthorization(self, authorized, days, expected):
        device = self.device(authorized=authorized, last_login=factories.now() - H(days=days))
        assert device.needs_reauthorization(max_days=60) is expected


class TestPasswordResetTokenModel:
    def token(self, **kwargs):
        return PasswordResetToken(user_id=1, token_hash="h", **kwargs)

    def test_valid(self):
        assert self.token(expiration_date=factories.now() + H(minutes=5), used=False).is_valid() is True

    def test_used(self):
        assert self.token(expiration_date=factories.now() + H(minutes=5), used=True).is_valid() is False

    def test_expired(self):
        assert self.token(expiration_date=factories.now() - H(minutes=1), used=False).is_valid() is False

    def test_only_the_hash_is_stored(self):
        assert PasswordResetToken.hash_token("abc") != "abc" and len(PasswordResetToken.hash_token("abc")) == 64


# -------------------------------------------------------------------- helpers
class TestHelpers:
    @pytest.mark.parametrize("data,expected", [
        (b"\x89PNG\r\n\x1a\n....", True), (b"\xff\xd8\xff\xe0....", True), (b"GIF89a....", True),
        (b"GIF87a....", True), (b"<?php", False), (b"", False), (b"RIFF....WEBP", False),
    ])
    def test_image_signature(self, data, expected):
        stream = io.BytesIO(data)
        assert auth.has_image_signature(stream) is expected
        assert stream.tell() == 0  # stream is rewound for the actual save

    def test_socket_rate_limiter(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr("security.time.monotonic", lambda: clock[0])
        limiter = SocketRateLimiter(max_events=2, window_seconds=10)
        assert [limiter.allow("u1"), limiter.allow("u1"), limiter.allow("u1")] == [True, True, False]
        assert limiter.allow("u2") is True  # independent key
        clock[0] += 11
        assert limiter.allow("u1") is True  # window slid

    def test_json_field_key(self, app):
        key = json_field_key("email")
        with app.test_request_context("/", method="POST", json={"email": "  Bob@Example.com "}):
            assert key() == "email:bob@example.com"
        with app.test_request_context("/", method="POST", json={}):
            assert key().startswith("ip:")
        with app.test_request_context("/", method="POST", data="not json"):
            assert key().startswith("ip:")


class TestVerifyCaptcha:
    request = types.SimpleNamespace(remote_addr="127.0.0.1", headers={})

    def test_valid(self):
        assert auth.verify_captcha("tok", self.request) is None

    def test_missing_token(self):
        assert auth.verify_captcha(None, self.request)[1] == 400
        assert auth.verify_captcha("", self.request)[1] == 400

    def test_rejected(self, externals):
        externals.captcha_success = False
        assert auth.verify_captcha("tok", self.request)[1] == 400

    def test_unreachable(self, externals):
        externals.captcha_raises = requests.Timeout()
        assert auth.verify_captcha("tok", self.request)[1] == 503

    def test_non_json_answer(self, externals):
        externals.captcha_raises = ValueError("not json")
        assert auth.verify_captcha("tok", self.request)[1] == 503

    def test_no_secret_configured(self, monkeypatch):
        monkeypatch.setattr(auth, "TURNSTILE_SECRET_KEY", "")
        assert auth.verify_captcha("tok", self.request)[1] == 500
