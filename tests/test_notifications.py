"""Push notifications: settings, devices, and who receives the message / new question / vote reminder."""
import datetime

import pytest

import notifications
from db import db
from models import GroupModel, GroupUser, PushTokenModel, UserModel
from tests import factories

H = datetime.timedelta
SETTINGS = "/api/notifications/settings/"
# Saved before the `externals` fixture replaces it with a recorder.
REAL_DELIVER = notifications.deliver
DEVICES = "/api/notifications/devices/"


def mute(client, group, muted=True):
    return client.put(SETTINGS, json={"groups": [{"id": group.id, "muted": muted}]})


def add_token(user, token=None, device_id=None):
    db.session.add(PushTokenModel(user_id=user.id, token=token or f"token-{user.username}",
                                  device_id=device_id or user.device_id))
    db.session.commit()


def tokens_of(pushes):
    return sorted(token for token, _ in pushes)


@pytest.fixture
def phones(world, ctx):
    """Every user of `world` has a phone registered."""
    with ctx():
        for user in (world.admin, world.member, world.outsider, world.other):
            add_token(user)


# ------------------------------------------------------------------- settings
class TestSettings:
    def test_defaults(self, login_as, world):
        content = login_as(world.member).get(SETTINGS).get_json()["content"]
        assert content == {"messages": True, "questions": True, "vote_reminder": True,
                           "groups": [{"id": world.group.id, "name": "Team", "muted": False}]}

    def test_update(self, login_as, world, ctx):
        response = login_as(world.member).put(SETTINGS, json={"messages": False, "vote_reminder": False})
        assert response.status_code == 200
        assert response.get_json()["content"]["messages"] is False
        with ctx():
            user = db.session.get(UserModel, world.member.id)
            assert (user.notify_messages, user.notify_questions, user.notify_vote_reminder) == (False, True, False)

    @pytest.mark.parametrize("payload", [{}, {"messages": "no"}, {"unknown": True}])
    def test_invalid_update(self, login_as, world, payload):
        assert login_as(world.member).put(SETTINGS, json=payload).status_code == 400

    def test_everything_in_one_request(self, login_as, world, ctx):
        payload = {"messages": False, "questions": False, "vote_reminder": True,
                   "groups": [{"id": world.group.id, "muted": True}]}
        response = login_as(world.member).put(SETTINGS, json=payload)
        assert response.status_code == 200
        content = response.get_json()["content"]
        assert (content["messages"], content["questions"], content["vote_reminder"]) == (False, False, True)
        assert content["groups"] == [{"id": world.group.id, "name": "Team", "muted": True}]
        with ctx():
            assert GroupUser.query.filter_by(user_id=world.member.id, group_id=world.group.id).one().notifications_muted

    def test_mute_and_unmute_a_group(self, login_as, world, ctx):
        assert mute(login_as(world.member), world.group).status_code == 200
        assert login_as(world.member).get(SETTINGS).get_json()["content"]["groups"][0]["muted"] is True
        mute(login_as(world.member), world.group, False)
        assert login_as(world.member).get(SETTINGS).get_json()["content"]["groups"][0]["muted"] is False

    def test_mute_requires_membership_and_saves_nothing(self, login_as, world, ctx):
        payload = {"messages": False, "groups": [{"id": world.group.id, "muted": True},
                                                 {"id": world.other_group.id, "muted": True}]}
        assert login_as(world.member).put(SETTINGS, json=payload).status_code == 403
        with ctx():
            assert db.session.get(UserModel, world.member.id).notify_messages is True
            assert not GroupUser.query.filter_by(user_id=world.member.id, group_id=world.group.id).one().notifications_muted

    @pytest.mark.parametrize("groups", ["x", [{"id": 1}], [{"id": "1", "muted": True}], [{"id": 1, "muted": "yes"}], [1]])
    def test_invalid_groups(self, login_as, world, groups):
        assert login_as(world.member).put(SETTINGS, json={"groups": groups}).status_code == 400


# -------------------------------------------------------------------- devices
class TestDevices:
    def test_register(self, login_as, world, ctx):
        response = login_as(world.member).post(DEVICES, json={"token": "abc", "device_id": "phone-1"})
        assert response.status_code == 201
        with ctx():
            token = PushTokenModel.query.one()
            assert (token.user_id, token.device_id, token.platform) == (world.member.id, "phone-1", "android")

    def test_a_token_moves_to_the_last_user(self, login_as, world, ctx):
        login_as(world.member).post(DEVICES, json={"token": "abc"})
        login_as(world.admin).post(DEVICES, json={"token": "abc"})
        with ctx():
            assert [t.user_id for t in PushTokenModel.query.all()] == [world.admin.id]

    def test_a_renewed_token_replaces_the_old_one(self, login_as, world, ctx):
        client = login_as(world.member)
        client.post(DEVICES, json={"token": "old", "device_id": "phone-1"})
        client.post(DEVICES, json={"token": "new", "device_id": "phone-1"})
        with ctx():
            assert [t.token for t in PushTokenModel.query.all()] == ["new"]

    @pytest.mark.parametrize("payload", [{}, {"token": ""}, {"token": "x" * 256}, {"token": "a", "platform": "web"},
                                         {"token": "a", "device_id": 5}])
    def test_invalid_register(self, login_as, world, payload):
        assert login_as(world.member).post(DEVICES, json=payload).status_code == 400

    def test_unregister_only_own_token(self, login_as, world, ctx):
        with ctx():
            add_token(world.member, "mine")
            add_token(world.admin, "theirs")
        assert login_as(world.member).delete(DEVICES, json={"token": "theirs"}).status_code == 200
        assert login_as(world.member).delete(DEVICES, json={"token": "mine"}).status_code == 200
        with ctx():
            assert [t.token for t in PushTokenModel.query.all()] == ["theirs"]

    def test_unregister_requires_a_token(self, login_as, world):
        assert login_as(world.member).delete(DEVICES, json={}).status_code == 400

    def test_logout_forgets_this_phone(self, login_as, world, ctx):
        with ctx():
            add_token(world.member, "this-phone", device_id="phone-1")
            add_token(world.member, "other-phone", device_id="phone-2")
        login_as(world.member).post("/api/auth/logout/", json={"device_id": "phone-1"})
        with ctx():
            assert [t.token for t in PushTokenModel.query.all()] == ["other-phone"]


# ------------------------------------------------------------------- messages
class TestMessageNotifications:
    def send(self, login_as, user, group, content="hello"):
        return login_as(user).post(f"/api/groups/{group.id}/messages/", json={"content": content})

    def test_other_members_are_notified(self, login_as, world, phones, externals):
        assert self.send(login_as, world.member, world.group).status_code == 201
        assert tokens_of(externals.pushes) == ["token-admin"]
        message = externals.pushes[0][1]
        assert message["notification"] == {"title": "Team", "body": "member: hello"}
        assert message["data"] == {"route": f"/group/{world.group.id}"}
        assert message["android"]["notification"] == {"channel_id": "messages", "tag": f"chat-{world.group.id}"}

    def test_in_the_recipient_language(self, login_as, world, phones, externals, ctx):
        with ctx():
            db.session.get(UserModel, world.admin.id).language = "fr"
            db.session.commit()
        self.send(login_as, world.member, world.group)
        assert externals.pushes[0][1]["notification"]["body"] == "member : hello"

    def test_gif_and_long_messages(self, login_as, world, phones, externals):
        self.send(login_as, world.member, world.group, "https://static.klipy.com/a.gif")
        self.send(login_as, world.member, world.group, "x" * 400)
        assert externals.pushes[0][1]["notification"]["body"] == "member sent a GIF"
        assert len(externals.pushes[1][1]["notification"]["body"]) == len("member: ") + 150

    def test_muted_group_or_setting_off(self, login_as, world, phones, externals):
        mute(login_as(world.admin), world.group)
        self.send(login_as, world.member, world.group)
        mute(login_as(world.admin), world.group, False)
        login_as(world.admin).put(SETTINGS, json={"messages": False})
        self.send(login_as, world.member, world.group)
        assert externals.pushes == []

    def test_every_phone_of_a_recipient(self, login_as, world, phones, externals, ctx):
        with ctx():
            add_token(world.admin, "admin-tablet", device_id="tablet")
        self.send(login_as, world.member, world.group)
        assert tokens_of(externals.pushes) == ["admin-tablet", "token-admin"]


# ------------------------------------------------------------- new questions
class TestQuestionNotifications:
    def run(self, ctx, now):
        with ctx():
            notifications.notify_new_questions(now)

    def test_first_run_only_initialises(self, world, phones, externals, ctx):
        self.run(ctx, factories.now())
        assert externals.pushes == []

    def test_once_per_new_day(self, world, phones, externals, ctx):
        now = factories.now()
        self.run(ctx, now - H(days=1))          # initialises on yesterday's day
        self.run(ctx, now)                      # a new day started: notify
        self.run(ctx, now + H(minutes=1))       # same day: nothing more
        assert tokens_of(externals.pushes) == ["token-admin", "token-member", "token-other"]
        team = [m for t, m in externals.pushes if t == "token-member"][0]
        assert team["notification"] == {"title": "Team", "body": "New question of the day!"}
        assert team["android"]["notification"]["channel_id"] == "questions"

    def test_respects_settings(self, login_as, world, phones, externals, ctx):
        login_as(world.member).put(SETTINGS, json={"questions": False})
        mute(login_as(world.other), world.other_group)
        now = factories.now()
        self.run(ctx, now - H(days=1))
        self.run(ctx, now)
        assert tokens_of(externals.pushes) == ["token-admin"]


# -------------------------------------------------------------- vote reminder
class TestVoteReminders:
    def window_start(self, ctx, group):
        with ctx():
            return factories.latest_reset(group.id)

    def run(self, ctx, now):
        with ctx():
            notifications.notify_vote_reminders(now)

    def test_only_in_the_last_hour_and_once(self, world, phones, externals, ctx):
        start = self.window_start(ctx, world.group)
        self.run(ctx, start + H(hours=1))                 # initialises
        self.run(ctx, start + H(hours=22, minutes=59))    # not yet
        assert externals.pushes == []
        self.run(ctx, start + H(hours=23))                # last hour: remind
        self.run(ctx, start + H(hours=23, minutes=30))    # once
        team = [t for t, m in externals.pushes if m["data"]["route"] == f"/group/{world.group.id}"]
        assert sorted(team) == ["token-admin", "token-member"]
        message = externals.pushes[0][1]
        assert message["notification"]["body"] == "1 hour left to vote!"
        assert message["android"]["notification"]["channel_id"] == "reminders"

    def test_voters_are_not_reminded(self, world, phones, externals, ctx):
        start = self.window_start(ctx, world.group)
        with ctx():
            question = factories.make_question(world.group)
            factories.make_vote(question, world.member, [world.admin])
        self.run(ctx, start + H(hours=1))
        self.run(ctx, start + H(hours=23))
        team = [t for t, m in externals.pushes if m["data"]["route"] == f"/group/{world.group.id}"]
        assert team == ["token-admin"]

    def test_a_vote_on_yesterdays_question_does_not_count(self, world, phones, externals, ctx):
        start = self.window_start(ctx, world.group)
        with ctx():
            old = factories.make_question(world.group, days_ago=1)
            factories.make_vote(old, world.member, [world.admin])
        self.run(ctx, start + H(hours=1))
        self.run(ctx, start + H(hours=23))
        team = [t for t, m in externals.pushes if m["data"]["route"] == f"/group/{world.group.id}"]
        assert sorted(team) == ["token-admin", "token-member"]

    def test_first_seen_in_the_last_hour_waits_for_the_next_day(self, world, phones, externals, ctx):
        start = self.window_start(ctx, world.group)
        self.run(ctx, start + H(hours=23, minutes=10))
        self.run(ctx, start + H(hours=23, minutes=20))
        assert externals.pushes == []

    def test_respects_settings(self, login_as, world, phones, externals, ctx):
        login_as(world.member).put(SETTINGS, json={"vote_reminder": False})
        start = self.window_start(ctx, world.group)
        self.run(ctx, start + H(hours=1))
        self.run(ctx, start + H(hours=23))
        team = [t for t, m in externals.pushes if m["data"]["route"] == f"/group/{world.group.id}"]
        assert team == ["token-admin"]


# -------------------------------------------------------------------- sending
class TestSending:
    def test_nothing_is_sent_without_the_firebase_key(self, monkeypatch, app, tmp_path):
        started = []
        monkeypatch.setattr(notifications, "fcm", notifications.FcmClient(str(tmp_path / "missing.json")))
        monkeypatch.setattr(notifications.socketio, "start_background_task", lambda *args: started.append(args))
        with app.app_context():
            REAL_DELIVER([("token", {})])
        assert started == []

    def test_sending_runs_in_the_background(self, monkeypatch, app, tmp_path):
        started = []
        key = tmp_path / "key.json"
        key.write_text("{}")
        monkeypatch.setattr(notifications, "fcm", notifications.FcmClient(str(key)))
        monkeypatch.setattr(notifications.socketio, "start_background_task", lambda *args: started.append(args))
        with app.app_context():
            REAL_DELIVER([("token", {})])
        assert started and started[0][2] == [("token", {})]

    def test_unregistered_tokens_are_deleted(self, app, world, ctx, monkeypatch):
        with ctx():
            add_token(world.member, "dead")
            add_token(world.admin, "alive")

        class FakeFcm:
            def send(self, token, message):
                return "unregistered" if token == "dead" else "ok"

        monkeypatch.setattr(notifications, "fcm", FakeFcm())
        notifications._send_all(app, [("dead", {}), ("alive", {})])
        with ctx():
            assert [t.token for t in PushTokenModel.query.all()] == ["alive"]

    def test_a_failure_does_not_stop_the_others(self, app, world, ctx, monkeypatch):
        sent = []

        class FlakyFcm:
            def send(self, token, message):
                if token == "first":
                    raise ConnectionError("network down")
                sent.append(token)
                return "ok"

        monkeypatch.setattr(notifications, "fcm", FlakyFcm())
        notifications._send_all(app, [("first", {}), ("second", {})])
        assert sent == ["second"]

    @pytest.mark.parametrize("status,text,expected", [
        (200, "{}", "ok"),
        (404, "not found", "unregistered"),
        (400, '{"error": {"details": [{"errorCode": "UNREGISTERED"}]}}', "unregistered"),
        (500, "server error", "error"),
    ])
    def test_fcm_answers(self, monkeypatch, tmp_path, status, text, expected):
        client = notifications.FcmClient(str(tmp_path / "key.json"))
        monkeypatch.setattr(client, "_access_token", lambda: ("access", "sadikoi-project"))
        calls = []

        class Response:
            status_code = status

        Response.text = text

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json})
            return Response()

        monkeypatch.setattr(notifications.requests, "post", fake_post)
        assert client.send("phone-token", {"data": {"route": "/"}}) == expected
        assert calls[0]["url"] == "https://fcm.googleapis.com/v1/projects/sadikoi-project/messages:send"
        assert calls[0]["headers"] == {"Authorization": "Bearer access"}
        assert calls[0]["json"] == {"message": {"token": "phone-token", "data": {"route": "/"}}}
