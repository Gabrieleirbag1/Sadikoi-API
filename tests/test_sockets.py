"""Socket.IO events: authentication on connect, room membership, live notifications."""
import pytest

import app as app_module
from security import SocketRateLimiter
from sockets import socketio


@pytest.fixture(autouse=True)
def real_emit(monkeypatch, externals):
    """Let the real Socket.IO emit run so rooms can be observed."""
    monkeypatch.setattr(socketio, "emit", externals.real_emit)


@pytest.fixture
def connect(app, login_as):
    clients = []

    def _connect(user):
        http = login_as(user)
        sio = socketio.test_client(app, flask_test_client=http)
        clients.append(sio)
        return sio, http

    yield _connect
    for sio in clients:
        if sio.is_connected():
            sio.disconnect()


def names(sio):
    return [event["name"] for event in sio.get_received()]


def test_anonymous_connection_is_refused(app):
    sio = socketio.test_client(app)
    assert sio.is_connected() is False


def test_authenticated_connection(connect, world):
    sio, _ = connect(world.member)
    assert sio.is_connected() is True


def test_member_receives_messages_of_joined_group(connect, world, login_as):
    sio, _ = connect(world.member)
    sio.emit("join_group", {"groupId": world.group.id})
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "hi"})
    received = sio.get_received()
    assert [e["name"] for e in received] == ["new_message"]
    assert received[0]["args"][0]["content"] == "hi"


def test_not_joined_means_no_events(connect, world, login_as):
    sio, _ = connect(world.member)
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "hi"})
    assert names(sio) == []


def test_non_member_cannot_join_a_group_room(connect, world, login_as):
    sio, _ = connect(world.outsider)
    sio.emit("join_group", {"groupId": world.group.id})
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "secret"})
    assert names(sio) == []


def test_events_are_scoped_to_their_group(connect, world, login_as):
    sio, _ = connect(world.other)
    sio.emit("join_group", {"groupId": world.other_group.id})
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "elsewhere"})
    assert names(sio) == []


def test_leave_group_stops_events(connect, world, login_as):
    sio, _ = connect(world.member)
    sio.emit("join_group", {"groupId": world.group.id})
    sio.emit("leave_group", {"groupId": world.group.id})
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "hi"})
    assert names(sio) == []


def test_votes_are_broadcast_to_the_room(connect, world, login_as, ctx):
    from tests import factories
    with ctx():
        factories.make_question(world.group)
    sio, _ = connect(world.admin)
    sio.emit("join_group", {"groupId": world.group.id})
    login_as(world.member).post(f"/api/questions/{world.group.id}/vote/", json={"votedUsers": [world.admin.id]})
    assert names(sio) == ["new_vote"]


def test_join_is_rate_limited(connect, world, monkeypatch, ctx, login_as):
    from tests import factories
    monkeypatch.setattr(app_module, "socket_join_limiter", SocketRateLimiter(max_events=1, window_seconds=60))
    with ctx():
        second = factories.make_group(world.member, name="Second")
    sio, _ = connect(world.member)
    sio.emit("join_group", {"groupId": world.group.id})
    sio.emit("join_group", {"groupId": second.id})  # over budget: silently ignored
    login_as(world.member).post(f"/api/groups/{second.id}/messages/", json={"content": "x"})
    assert names(sio) == []
    login_as(world.admin).post(f"/api/groups/{world.group.id}/messages/", json={"content": "y"})
    assert names(sio) == ["new_message"]
