"""groups/<id>/messages/: reading a day's window, posting only to the current day, membership."""
import datetime

import pytest

from models import ChatMessageModel
from tests import factories

H = datetime.timedelta


def messages_url(group_id):
    return f"/api/groups/{group_id}/messages/"


def contents(response):
    return [m["content"] for m in response.get_json()["content"]]


@pytest.fixture
def days(world, ctx):
    """Yesterday's question + today's question, one message in each window."""
    with ctx():
        old_q = factories.make_question(world.group, days_ago=1)
        cur_q = factories.make_question(world.group, days_ago=0)
        factories.make_message(world.group, world.member, "yesterday-1", at=old_q.date + H(hours=1))
        factories.make_message(world.group, world.admin, "yesterday-2", at=old_q.date + H(hours=2))
        factories.make_message(world.group, world.member, "today-1", at=cur_q.date + H(minutes=1))
    return old_q, cur_q


# ------------------------------------------------------------------------ GET
class TestGetMessages:
    def test_defaults_to_the_current_day_in_chronological_order(self, login_as, world, days, ctx):
        with ctx():
            factories.make_message(world.group, world.admin, "today-2", at=days[1].date + H(minutes=5))
        response = login_as(world.member).get(messages_url(world.group.id))
        assert response.status_code == 200
        assert contents(response) == ["today-1", "today-2"]

    def test_message_shape(self, login_as, world, days):
        message = login_as(world.member).get(messages_url(world.group.id)).get_json()["content"][0]
        assert message["sender"]["username"] == "member"
        assert {"id", "content", "timestamp", "sender"} <= set(message)

    def test_previous_day_by_question_id(self, login_as, world, days):
        response = login_as(world.member).get(messages_url(world.group.id), query_string={"question_id": days[0].id})
        assert contents(response) == ["yesterday-1", "yesterday-2"]

    def test_current_day_by_question_id(self, login_as, world, days):
        response = login_as(world.member).get(messages_url(world.group.id), query_string={"question_id": days[1].id})
        assert contents(response) == ["today-1"]

    def test_unknown_question(self, login_as, world, days):
        response = login_as(world.member).get(messages_url(world.group.id), query_string={"question_id": 99999})
        assert response.status_code == 404

    def test_question_of_another_group_is_not_reachable(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group)
            foreign = factories.make_question(world.other_group)
        response = login_as(world.member).get(messages_url(world.group.id), query_string={"question_id": foreign.id})
        assert response.status_code == 404

    def test_messages_of_another_group_never_leak(self, login_as, world, days, ctx):
        with ctx():
            factories.make_message(world.other_group, world.other, "secret", at=days[1].date + H(minutes=2))
        assert "secret" not in contents(login_as(world.member).get(messages_url(world.group.id)))

    def test_expired_day_is_capped_at_24_hours(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group, days_ago=3)
            factories.make_message(world.group, world.member, "inside", at=q.date + H(hours=23))
            factories.make_message(world.group, world.member, "after", at=q.date + H(hours=30))
        assert contents(login_as(world.member).get(messages_url(world.group.id))) == ["inside"]

    def test_group_without_question_returns_everything(self, login_as, world, ctx):
        with ctx():
            factories.make_message(world.group, world.member, "a")
            factories.make_message(world.group, world.admin, "b", at=factories.now() + H(seconds=1))
        assert contents(login_as(world.member).get(messages_url(world.group.id))) == ["a", "b"]

    def test_non_member_forbidden(self, login_as, world, days):
        assert login_as(world.outsider).get(messages_url(world.group.id)).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.member).get(messages_url(9999)).status_code == 404

    def test_requires_login(self, anon, world):
        assert anon.get(messages_url(world.group.id)).status_code == 401


# ----------------------------------------------------------------------- POST
class TestSendMessage:
    @pytest.fixture
    def today(self, world, ctx):
        with ctx():
            return factories.make_question(world.group)

    def send(self, client, group_id, **json):
        return client.post(messages_url(group_id), json=json)

    def test_member_sends_and_group_is_notified(self, login_as, world, today, externals, ctx):
        response = self.send(login_as(world.member), world.group.id, content="hi", question_id=today.id)
        assert response.status_code == 201
        body = response.get_json()["content"]
        assert body["content"] == "hi" and body["sender"]["id"] == world.member.id
        [event] = [e for e in externals.events if e["event"] == "new_message"]
        assert event["to"] == str(world.group.id) and event["data"]["content"] == "hi"
        with ctx():
            assert ChatMessageModel.query.filter_by(group_id=world.group.id).count() == 1

    def test_sent_message_is_readable(self, login_as, world, today):
        client = login_as(world.member)
        self.send(client, world.group.id, content="ping")
        assert contents(client.get(messages_url(world.group.id))) == ["ping"]

    def test_question_id_is_optional_on_the_open_day(self, login_as, world, today):
        assert self.send(login_as(world.member), world.group.id, content="hi").status_code == 201

    def test_group_without_question_accepts_messages(self, login_as, world):
        assert self.send(login_as(world.member), world.group.id, content="first").status_code == 201

    @pytest.mark.parametrize("body", [{}, {"content": ""}, {"content": None}])
    def test_content_required(self, login_as, world, today, body):
        assert self.send(login_as(world.member), world.group.id, **body).status_code == 400

    def test_non_member_forbidden(self, login_as, world, today, ctx):
        assert self.send(login_as(world.outsider), world.group.id, content="hi").status_code == 403
        with ctx():
            assert ChatMessageModel.query.count() == 0

    def test_unknown_group(self, login_as, world):
        assert self.send(login_as(world.member), 9999, content="hi").status_code == 404

    def test_previous_day_forbidden_without_question_id(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, days_ago=2)
        assert self.send(login_as(world.member), world.group.id, content="late").status_code == 403

    def test_previous_day_forbidden_with_its_question_id(self, login_as, world, ctx):
        with ctx():
            old = factories.make_question(world.group, days_ago=2)
        response = self.send(login_as(world.member), world.group.id, content="late", question_id=old.id)
        assert response.status_code == 403

    def test_old_question_id_on_open_day_forbidden(self, login_as, world, today, ctx):
        with ctx():
            old = factories.make_question(world.group, days_ago=1)
        response = self.send(login_as(world.member), world.group.id, content="x", question_id=old.id)
        assert response.status_code == 403

    def test_question_id_of_another_group_forbidden(self, login_as, world, today, ctx):
        with ctx():
            foreign = factories.make_question(world.other_group)
        response = self.send(login_as(world.member), world.group.id, content="x", question_id=foreign.id)
        assert response.status_code == 403

    def test_requires_login(self, anon, world):
        assert self.send(anon, world.group.id, content="x").status_code == 401
