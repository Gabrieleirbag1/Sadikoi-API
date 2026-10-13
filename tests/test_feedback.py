"""feedback/bug-reports/ and feedback/suggestions/."""
import datetime

import pytest

from db import db
from models import BugReportModel, SuggestionModel
from tests import factories

BUGS = "/api/feedback/bug-reports/"
SUGGESTIONS = "/api/feedback/suggestions/"


@pytest.fixture
def alice(ctx):
    with ctx():
        return factories.make_user("alice")


class TestBugReports:
    body = {"title": "Crash", "description": "It crashes when I vote", "device_name": "Pixel"}

    def test_create(self, login_as, alice, ctx):
        response = login_as(alice).post(BUGS, json=self.body)
        assert response.status_code == 201
        with ctx():
            report = BugReportModel.query.one()
            assert (report.user_id, report.title, report.device_name) == (alice.id, "Crash", "Pixel")

    def test_device_name_defaults(self, login_as, alice, ctx):
        login_as(alice).post(BUGS, json={"title": "t", "description": "d"})
        with ctx():
            assert BugReportModel.query.one().device_name == "Unknown Device"

    @pytest.mark.parametrize("missing", ["title", "description"])
    def test_required_fields(self, login_as, alice, missing):
        body = {k: v for k, v in self.body.items() if k != missing}
        assert login_as(alice).post(BUGS, json=body).status_code == 400

    def test_spam_protection(self, login_as, alice, ctx):
        client = login_as(alice)
        assert client.post(BUGS, json=self.body).status_code == 201
        assert client.post(BUGS, json=self.body).status_code == 429
        with ctx():
            assert BugReportModel.query.count() == 1

    def test_allowed_again_after_the_cooldown(self, login_as, alice, ctx):
        client = login_as(alice)
        client.post(BUGS, json=self.body)
        with ctx():
            BugReportModel.query.one().timestamp = factories.now() - datetime.timedelta(seconds=61)
            db.session.commit()
        assert client.post(BUGS, json=self.body).status_code == 201

    def test_cooldown_is_per_user(self, login_as, alice, ctx):
        with ctx():
            bob = factories.make_user("bob")
        login_as(alice).post(BUGS, json=self.body)
        assert login_as(bob).post(BUGS, json=self.body).status_code == 201

    def test_requires_login(self, anon):
        assert anon.post(BUGS, json=self.body).status_code == 401


class TestSuggestions:
    body = {"theme": "connerie", "question": "Who would survive a zombie apocalypse?"}

    def test_create(self, login_as, alice, ctx):
        assert login_as(alice).post(SUGGESTIONS, json=self.body).status_code == 201
        with ctx():
            suggestion = SuggestionModel.query.one()
            assert (suggestion.user_id, suggestion.theme) == (alice.id, "connerie")

    @pytest.mark.parametrize("missing", ["theme", "question"])
    def test_required_fields(self, login_as, alice, missing):
        body = {k: v for k, v in self.body.items() if k != missing}
        assert login_as(alice).post(SUGGESTIONS, json=body).status_code == 400

    def test_spam_protection(self, login_as, alice):
        client = login_as(alice)
        assert client.post(SUGGESTIONS, json=self.body).status_code == 201
        assert client.post(SUGGESTIONS, json=self.body).status_code == 429

    def test_allowed_again_after_the_cooldown(self, login_as, alice, ctx):
        client = login_as(alice)
        client.post(SUGGESTIONS, json=self.body)
        with ctx():
            SuggestionModel.query.one().timestamp = factories.now() - datetime.timedelta(seconds=21)
            db.session.commit()
        assert client.post(SUGGESTIONS, json=self.body).status_code == 201

    def test_requires_login(self, anon):
        assert anon.post(SUGGESTIONS, json=self.body).status_code == 401
