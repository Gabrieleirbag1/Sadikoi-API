"""groups/*: CRUD, membership, roles and invitations."""
import datetime

import pytest

from db import db
from models import GroupInvitationModel, GroupModel, GroupUser
from tests import factories

GROUPS = "/api/groups/"


def url(group_id, *parts):
    return GROUPS + str(group_id) + "/" + "".join(f"{p}/" for p in parts)


def events(externals, name):
    return [e for e in externals.events if e["event"] == name]


def roles(ctx, group):
    with ctx():
        return {row.user_id: row.role for row in GroupUser.query.filter_by(group_id=group.id).all()}


# ---------------------------------------------------------------------- create
class TestCreateGroup:
    payload = {"name": "Friends", "description": "the gang", "themes": ["connerie"], "daily_reset_timestamp": "08:30"}

    def test_creator_becomes_admin(self, login_as, world, ctx):
        response = login_as(world.outsider).post(GROUPS, json=self.payload)
        assert response.status_code == 201
        content = response.get_json()["content"]
        assert content["name"] == "Friends"
        assert content["daily_reset_timestamp"] == "08:30"
        assert [(u["id"], u["role"]) for u in content["users"]] == [(world.outsider.id, "admin")]
        assert content["has_user_voted_today"] is False

    def test_default_reset_time(self, login_as, world):
        payload = {k: v for k, v in self.payload.items() if k != "daily_reset_timestamp"}
        response = login_as(world.outsider).post(GROUPS, json=payload)
        assert response.status_code == 201
        assert response.get_json()["content"]["daily_reset_timestamp"] == "15:00"

    @pytest.mark.xfail(strict=True, raises=TypeError,
                       reason="description is optional in the API but GroupModel's validator calls len(None)")
    def test_description_is_optional(self, login_as, world):
        payload = {k: v for k, v in self.payload.items() if k != "description"}
        assert login_as(world.outsider).post(GROUPS, json=payload).status_code == 201

    @pytest.mark.parametrize("change", [
        {"name": ""}, {"name": None}, {"themes": []}, {"themes": None}, {"themes": ["nope"]},
        {"themes": ["connerie", "nope"]}, {"daily_reset_timestamp": "25:99"}, {"daily_reset_timestamp": "noon"},
        {"name": "x" * 31}, {"description": "x" * 201},
    ])
    def test_invalid_payloads(self, login_as, world, change, ctx):
        response = login_as(world.outsider).post(GROUPS, json={**self.payload, **change})
        assert response.status_code == 400
        with ctx():
            assert GroupModel.query.filter_by(name="Friends").count() == 0

    def test_requires_login(self, anon):
        assert anon.post(GROUPS, json=self.payload).status_code == 401


# ------------------------------------------------------------------------ read
class TestGetGroup:
    def test_member_sees_group(self, login_as, world):
        response = login_as(world.member).get(url(world.group.id))
        assert response.status_code == 200
        content = response.get_json()["content"]
        assert {u["username"]: u["role"] for u in content["users"]} == {"admin": "admin", "member": "member"}
        assert content["themes"] == ["connerie", "style"]

    def test_non_member_forbidden(self, login_as, world):
        assert login_as(world.outsider).get(url(world.group.id)).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).get(url(9999)).status_code == 404

    def test_user_groups_lists_only_mine(self, login_as, world):
        names = [g["name"] for g in login_as(world.admin).get(GROUPS + "user/").get_json()["content"]]
        assert names == ["Team"]
        assert login_as(world.outsider).get(GROUPS + "user/").get_json()["content"] == []

    def test_has_user_voted_today_is_reported(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group)
            factories.make_vote(q, world.member, [world.admin])
        voter = login_as(world.member).get(url(world.group.id)).get_json()["content"]
        non_voter = login_as(world.admin).get(url(world.group.id)).get_json()["content"]
        assert voter["has_user_voted_today"] is True and voter["question"]["id"] == q.id
        assert non_voter["has_user_voted_today"] is False and non_voter["question"] is None


# ---------------------------------------------------------------------- update
class TestUpdateGroup:
    payload = {"name": "Renamed", "description": "new", "themes": ["style"], "daily_reset_timestamp": "21:15"}

    def test_admin_updates_and_members_are_notified(self, login_as, world, externals, ctx):
        response = login_as(world.admin).put(url(world.group.id), json=self.payload)
        assert response.status_code == 200
        with ctx():
            group = GroupModel.query.get(world.group.id)
            assert (group.name, group.description, group.themes) == ("Renamed", "new", ["style"])
            assert group.daily_reset_timestamp == datetime.time(21, 15)
        [event] = events(externals, "group_updated")
        assert event["to"] == str(world.group.id) and event["data"]["name"] == "Renamed"

    def test_name_and_description_are_optional_but_themes_are_required(self, login_as, world):
        response = login_as(world.admin).put(url(world.group.id), json={"themes": ["style"]})
        assert response.status_code == 200
        assert login_as(world.admin).put(url(world.group.id), json={"name": "only name"}).status_code == 400

    def test_member_forbidden(self, login_as, world, ctx):
        assert login_as(world.member).put(url(world.group.id), json=self.payload).status_code == 403
        with ctx():
            assert GroupModel.query.get(world.group.id).name == "Team"

    def test_non_member_forbidden(self, login_as, world):
        assert login_as(world.outsider).put(url(world.group.id), json=self.payload).status_code == 403

    def test_admin_of_another_group_forbidden(self, login_as, world):
        assert login_as(world.other).put(url(world.group.id), json=self.payload).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).put(url(9999), json=self.payload).status_code == 404

    @pytest.mark.parametrize("change", [{"themes": []}, {"themes": ["nope"]}, {"daily_reset_timestamp": "bad"}])
    def test_invalid_payload_changes_nothing(self, login_as, world, change, ctx):
        response = login_as(world.admin).put(url(world.group.id), json={**self.payload, **change})
        assert response.status_code == 400
        with ctx():
            assert GroupModel.query.get(world.group.id).name == "Team"


# ---------------------------------------------------------------------- delete
class TestDeleteGroup:
    def test_admin_deletes(self, login_as, world, externals, ctx):
        response = login_as(world.admin).delete(url(world.group.id))
        assert response.status_code == 200
        with ctx():
            assert GroupModel.query.get(world.group.id) is None
            assert GroupUser.query.filter_by(group_id=world.group.id).count() == 0
        assert events(externals, "group_deleted")[0]["data"] == {"group_id": world.group.id}

    def test_member_forbidden(self, login_as, world, ctx):
        assert login_as(world.member).delete(url(world.group.id)).status_code == 403
        with ctx():
            assert GroupModel.query.get(world.group.id) is not None

    def test_non_member_forbidden(self, login_as, world):
        assert login_as(world.outsider).delete(url(world.group.id)).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).delete(url(9999)).status_code == 404


# ---------------------------------------------------------------- members
class TestRemoveMember:
    def test_admin_removes_member(self, login_as, world, externals, ctx):
        response = login_as(world.admin).delete(url(world.group.id, world.member.id))
        assert response.status_code == 200
        assert roles(ctx, world.group) == {world.admin.id: "admin"}
        assert events(externals, "member_left")

    def test_remove_by_username(self, login_as, world, ctx):
        assert login_as(world.admin).delete(url(world.group.id, "member")).status_code == 200

    def test_member_can_leave(self, login_as, world, ctx):
        assert login_as(world.member).delete(url(world.group.id, world.member.id)).status_code == 200
        assert roles(ctx, world.group) == {world.admin.id: "admin"}

    def test_member_cannot_remove_others(self, login_as, world, ctx):
        with ctx():
            third = factories.make_user("third")
            db.session.add(GroupUser(user_id=third.id, group_id=world.group.id, role="member"))
            db.session.commit()
        response = login_as(world.member).delete(url(world.group.id, third.id))
        assert response.status_code == 403
        assert len(roles(ctx, world.group)) == 3

    def test_admin_leaving_hands_over_the_admin_role(self, login_as, world, ctx):
        assert login_as(world.admin).delete(url(world.group.id, world.admin.id)).status_code == 200
        assert roles(ctx, world.group) == {world.member.id: "admin"}

    def test_only_member_admin_cannot_leave(self, login_as, world, ctx):
        response = login_as(world.other).delete(url(world.other_group.id, world.other.id))
        assert response.status_code == 400
        assert roles(ctx, world.other_group) == {world.other.id: "admin"}

    def test_caller_not_in_group(self, login_as, world):
        assert login_as(world.outsider).delete(url(world.group.id, world.member.id)).status_code == 400

    def test_target_not_in_group(self, login_as, world):
        assert login_as(world.admin).delete(url(world.group.id, world.outsider.id)).status_code == 400

    def test_unknown_target(self, login_as, world):
        assert login_as(world.admin).delete(url(world.group.id, "ghost")).status_code == 404

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).delete(url(9999, world.member.id)).status_code == 404


class TestPromote:
    def promote(self, client, group, who):
        return client.post(url(group.id, "role"), json={"user_info": who})

    def test_admin_hands_over_admin_role(self, login_as, world, externals, ctx):
        response = self.promote(login_as(world.admin), world.group, "member")
        assert response.status_code == 200
        assert roles(ctx, world.group) == {world.admin.id: "member", world.member.id: "admin"}
        assert events(externals, "role_updated")

    def test_by_id(self, login_as, world, ctx):
        assert self.promote(login_as(world.admin), world.group, str(world.member.id)).status_code == 200

    def test_member_cannot_promote(self, login_as, world, ctx):
        assert self.promote(login_as(world.member), world.group, "member").status_code == 403
        assert roles(ctx, world.group)[world.member.id] == "member"

    def test_cannot_promote_yourself(self, login_as, world):
        assert self.promote(login_as(world.admin), world.group, "admin").status_code == 400

    def test_target_not_in_group(self, login_as, world):
        assert self.promote(login_as(world.admin), world.group, "outsider").status_code == 404

    def test_user_info_required(self, login_as, world):
        assert login_as(world.admin).post(url(world.group.id, "role"), json={}).status_code == 400

    def test_unknown_group(self, login_as, world):
        assert self.promote(login_as(world.admin), type("G", (), {"id": 9999}), "member").status_code == 404

    def test_outside_admin_cannot_promote(self, login_as, world):
        assert self.promote(login_as(world.other), world.group, "member").status_code == 403

    @pytest.mark.xfail(strict=True, raises=AttributeError,
                       reason="promote_user_group_role() dereferences get_user_object(...).id for an unknown user -> 500")
    def test_unknown_user(self, login_as, world):
        assert self.promote(login_as(world.admin), world.group, "ghost").status_code == 404


# ------------------------------------------------------------- invitations
class TestInvitations:
    def test_member_creates_invitation(self, login_as, world, ctx):
        response = login_as(world.member).get(url(world.group.id, "invitations"))
        assert response.status_code == 201
        token = response.get_json()["content"]
        with ctx():
            invitation = GroupInvitationModel.query.filter_by(token=token).one()
            assert invitation.group_id == world.group.id

    def test_existing_valid_invitation_is_reused(self, login_as, world, ctx):
        with ctx():
            token = factories.make_invitation(world.group)
        response = login_as(world.member).get(url(world.group.id, "invitations"))
        assert response.status_code == 200 and response.get_json()["content"] == token

    def test_expired_invitation_is_replaced(self, login_as, world, ctx):
        with ctx():
            old = factories.make_invitation(world.group, expired=True)
        response = login_as(world.member).get(url(world.group.id, "invitations"))
        assert response.status_code == 201 and response.get_json()["content"] != old

    @pytest.mark.xfail(strict=True, reason="once the first invitation row expired, every call creates a new token "
                                           "(filter_by(group_id).first() keeps returning the expired one)")
    def test_replacement_invitation_is_then_reused(self, login_as, world, ctx):
        with ctx():
            factories.make_invitation(world.group, expired=True)
        client = login_as(world.member)
        first = client.get(url(world.group.id, "invitations")).get_json()["content"]
        second = client.get(url(world.group.id, "invitations")).get_json()["content"]
        assert first == second

    def test_non_member_cannot_get_invitation(self, login_as, world):
        assert login_as(world.outsider).get(url(world.group.id, "invitations")).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).get(url(9999, "invitations")).status_code == 404

    def test_answer_invitation_joins_group(self, login_as, world, externals, ctx):
        with ctx():
            token = factories.make_invitation(world.group)
        response = login_as(world.outsider).post(f"{GROUPS}invitations/{token}/")
        assert response.status_code == 200
        assert roles(ctx, world.group)[world.outsider.id] == "member"
        assert events(externals, "member_joined")

    def test_already_member(self, login_as, world, ctx):
        with ctx():
            token = factories.make_invitation(world.group)
        assert login_as(world.member).post(f"{GROUPS}invitations/{token}/").status_code == 400

    def test_unknown_token(self, login_as, world):
        assert login_as(world.outsider).post(f"{GROUPS}invitations/nope/").status_code == 404

    def test_expired_token(self, login_as, world, ctx):
        with ctx():
            token = factories.make_invitation(world.group, expired=True)
        response = login_as(world.outsider).post(f"{GROUPS}invitations/{token}/")
        assert response.status_code == 400
        assert world.outsider.id not in roles(ctx, world.group)

    def test_invitation_is_reusable_by_several_users(self, login_as, world, ctx):
        with ctx():
            token = factories.make_invitation(world.group)
            second = factories.make_user("second")
        assert login_as(world.outsider).post(f"{GROUPS}invitations/{token}/").status_code == 200
        assert login_as(second).post(f"{GROUPS}invitations/{token}/").status_code == 200
