"""auth/security/blocks/: blocking a user, and the chat history a block hides (notifications: test_notifications.py)."""
import pytest

from db import db
from models import UserBlockModel, UserModel
from tests import factories

BLOCKS = "/api/auth/security/blocks/"


def block_url(user_id):
    return f"{BLOCKS}{user_id}"


# ---------------------------------------------------------------------- routes
class TestBlockRoutes:
    def test_block_then_list(self, login_as, world, ctx):
        client = login_as(world.admin)
        assert client.put(block_url(world.member.id)).status_code == 200
        assert client.get(BLOCKS).get_json()["content"] == {"blocked": [world.member.id], "blocked_by": []}
        content = login_as(world.member).get(BLOCKS).get_json()["content"]
        assert content == {"blocked": [], "blocked_by": [world.admin.id]}

    def test_both_users_are_told(self, login_as, world, externals):
        client = login_as(world.admin)
        client.put(block_url(world.member.id))
        client.put(block_url(world.member.id))  # already blocked: nothing changes, nobody is told
        client.delete(block_url(world.member.id))
        rooms = [(event["event"], event["to"]) for event in externals.events]
        pair = [("blocks_changed", f"user-{world.admin.id}"), ("blocks_changed", f"user-{world.member.id}")]
        assert rooms == pair * 2

    def test_blocking_twice_keeps_one_row(self, login_as, world, ctx):
        client = login_as(world.admin)
        assert client.put(block_url(world.member.id)).status_code == 200
        assert client.put(block_url(world.member.id)).status_code == 200
        with ctx():
            assert UserBlockModel.query.count() == 1

    def test_unblock(self, login_as, world, ctx):
        client = login_as(world.admin)
        client.put(block_url(world.member.id))
        assert client.delete(block_url(world.member.id)).status_code == 200
        with ctx():
            assert UserBlockModel.query.count() == 0
        assert client.get(BLOCKS).get_json()["content"] == {"blocked": [], "blocked_by": []}

    def test_unblock_someone_not_blocked(self, login_as, world):
        assert login_as(world.admin).delete(block_url(world.member.id)).status_code == 200

    def test_cannot_block_yourself(self, login_as, world, ctx):
        assert login_as(world.admin).put(block_url(world.admin.id)).status_code == 400
        with ctx():
            assert UserBlockModel.query.count() == 0

    def test_unknown_user(self, login_as, world):
        assert login_as(world.admin).put(block_url(99999)).status_code == 404

    def test_deleted_user(self, login_as, world, ctx):
        with ctx():
            db.session.get(UserModel, world.member.id).deleted = True
            db.session.commit()
        assert login_as(world.admin).put(block_url(world.member.id)).status_code == 404

    def test_requires_login(self, anon, world):
        assert anon.get(BLOCKS).status_code == 401
        assert anon.put(block_url(world.member.id)).status_code == 401
        assert anon.delete(block_url(world.member.id)).status_code == 401


# ------------------------------------------------------------------------ chat
class TestChatHistory:
    @pytest.fixture(autouse=True)
    def messages(self, world, ctx):
        with ctx():
            factories.make_question(world.group)
            factories.make_message(world.group, world.admin, "from admin")
            factories.make_message(world.group, world.member, "from member")

    def get(self, client, world):
        return client.get(f"/api/groups/{world.group.id}/messages/").get_json()["content"]

    def test_the_blocked_user_does_not_get_the_blockers_messages(self, login_as, world):
        login_as(world.admin).put(block_url(world.member.id))
        messages = self.get(login_as(world.member), world)
        assert [(m["content"], m.get("blocked_you", False)) for m in messages] == [("", True), ("from member", False)]

    def test_the_blocker_still_gets_everything(self, login_as, world):
        """The app masks the blocked user's messages, and can reveal them on tap."""
        client = login_as(world.admin)
        client.put(block_url(world.member.id))
        messages = self.get(client, world)
        assert [m["content"] for m in messages] == ["from admin", "from member"]
        assert not any("blocked_you" in m for m in messages)
