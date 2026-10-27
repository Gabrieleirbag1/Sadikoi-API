"""questions/<group>/ (daily question), questions/<group>/<month>/<year>/ (history) and .../vote/."""
import datetime

import pytest

from db import db
from models import ItemModel, QuestionModel, QuestionVote, QuestionVoteTarget
from builder import get_user_items_in_group
from tests import factories

H = datetime.timedelta


def q_url(group_id, *parts):
    return f"/api/questions/{group_id}/" + "".join(f"{p}/" for p in parts)


def question_count(ctx, group):
    with ctx():
        return QuestionModel.query.filter_by(group_id=group.id).count()


# ------------------------------------------------------------- daily question
class TestGetQuestion:
    @pytest.fixture
    def group(self, world, ctx):
        with ctx():
            return factories.make_group(world.admin, [world.member], themes=["connerie"], name="Funny")

    def test_first_call_generates_todays_question_once(self, login_as, world, group, externals, ctx):
        response = login_as(world.admin).get(q_url(group.id))
        assert response.status_code == 200
        content = response.get_json()["content"]
        assert content["question_id"] == 1 and content["content"] == "Who is the funniest?"
        assert content["votes"] is None
        assert question_count(ctx, group) == 1
        [event] = [e for e in externals.events if e["event"] == "new_question"]
        assert event["to"] == str(group.id) and event["data"] == {"group_id": group.id}
        # a second call (and another member) get the same question, nothing new is generated
        again = login_as(world.member).get(q_url(group.id)).get_json()["content"]
        assert again["id"] == content["id"]
        assert question_count(ctx, group) == 1

    def test_only_themes_of_the_group_are_used(self, login_as, world, ctx):
        with ctx():
            group = factories.make_group(world.admin, themes=["style"], name="Stylish")
        content = login_as(world.admin).get(q_url(group.id)).get_json()["content"]
        assert content["question_id"] == 2 and content["canWrite"] is True

    def test_no_question_for_the_group_themes(self, login_as, world, ctx):
        with ctx():
            group = factories.make_group(world.admin, themes=["unknown-theme"], name="Empty")
        assert login_as(world.admin).get(q_url(group.id)).status_code == 404

    def test_question_is_localized_to_the_user(self, login_as, world, ctx):
        with ctx():
            french = factories.make_user("french", language="fr")
            group = factories.make_group(world.admin, [french], themes=["connerie"], name="FR")
        content = login_as(french).get(q_url(group.id)).get_json()["content"]
        assert content["content"] == "Qui est le plus drôle ?"

    def test_expired_question_is_replaced(self, login_as, world, group, ctx):
        with ctx():
            old = factories.make_question(group, days_ago=1)
        content = login_as(world.admin).get(q_url(group.id)).get_json()["content"]
        assert content["id"] != old.id
        assert question_count(ctx, group) == 2

    def test_votes_hidden_until_the_user_voted(self, login_as, world, group, ctx):
        with ctx():
            q = factories.make_question(group)
            factories.make_vote(q, world.member, [world.admin])
        assert login_as(world.admin).get(q_url(group.id)).get_json()["content"]["votes"] is None
        votes = login_as(world.member).get(q_url(group.id)).get_json()["content"]["votes"]
        assert [v["voterUser"]["username"] for v in votes] == ["member"]
        assert [t["username"] for t in votes[0]["targets"]] == ["admin"]

    def test_written_answers_are_exposed_after_voting(self, login_as, world, ctx):
        with ctx():
            group = factories.make_group(world.admin, [world.member], themes=["style"], name="Write")
            q = factories.make_question(group, question_id=2, can_write=True)
            factories.make_vote(q, world.member, written_answer="a joke")
        votes = login_as(world.member).get(q_url(group.id)).get_json()["content"]["votes"]
        assert votes[0]["writtenAnswer"] == "a joke" and votes[0]["targets"] == []

    def test_new_day_grants_the_item_to_yesterdays_winner(self, login_as, world, group, ctx):
        with ctx():
            old = factories.make_question(group, days_ago=1)
            factories.make_vote(old, world.admin, [world.member])
            factories.make_vote(old, world.member, [world.member])
        assert login_as(world.admin).get(q_url(group.id)).status_code == 200
        with ctx():
            [item] = ItemModel.query.filter_by(group_id=group.id).all()
            assert (item.user_id, item.item_name) == (world.member.id, "bonnet_honte")

    def test_item_depends_only_on_the_day_before_today_not_on_older_days(self, login_as, world, group, ctx):
        with ctx():
            two_days_ago = factories.make_question(group, days_ago=2)
            factories.make_vote(two_days_ago, world.admin, [world.admin])    # older winner: admin
            yesterday = factories.make_question(group, days_ago=1)
            factories.make_vote(yesterday, world.admin, [world.member])       # yesterday's winner: member
        assert login_as(world.admin).get(q_url(group.id)).status_code == 200
        with ctx():
            [item] = ItemModel.query.filter_by(group_id=group.id).all()
            assert item.user_id == world.member.id
            assert item.acquired_at.replace(tzinfo=None) == yesterday.date.replace(tzinfo=None)

    def test_votes_on_todays_question_do_not_change_items(self, login_as, world, group, ctx):
        client = login_as(world.admin)
        with ctx():
            old = factories.make_question(group, days_ago=1)
            factories.make_vote(old, world.admin, [world.member])
        client.get(q_url(group.id))                                           # generates today's question + item
        login_as(world.member).post(q_url(group.id, "vote"), json={"votedUsers": [world.admin.id]})
        client.get(q_url(group.id))                                           # today's question already exists
        with ctx():
            [item] = ItemModel.query.filter_by(group_id=group.id).all()
            assert item.user_id == world.member.id                            # still yesterday's winner, no new item

    def test_no_item_when_yesterday_ended_in_a_tie(self, login_as, world, group, ctx):
        with ctx():
            old = factories.make_question(group, days_ago=1)
            factories.make_vote(old, world.admin, [world.member])
            factories.make_vote(old, world.member, [world.admin])
        login_as(world.admin).get(q_url(group.id))
        with ctx():
            assert ItemModel.query.count() == 0

    def test_answer_question_never_grants_an_item(self, login_as, world, group, ctx):
        with ctx():
            old = factories.make_question(group, days_ago=1, question_id=2, can_write=True, item_name="cape_puissante")
            factories.make_vote(old, world.admin, written_answer="a joke")
            factories.make_vote(old, world.member, written_answer="another joke")
        login_as(world.admin).get(q_url(group.id))
        with ctx():
            assert ItemModel.query.count() == 0

    def test_answer_question_never_grants_an_item_to_a_solo_player(self, login_as, world, ctx):
        with ctx():
            solo = factories.make_group(world.admin, themes=["connerie"], name="Solo")
            old = factories.make_question(solo, days_ago=1, question_id=2, can_write=True, item_name="cape_puissante")
            factories.make_vote(old, world.admin, written_answer="a joke")
        login_as(world.admin).get(q_url(solo.id))
        with ctx():
            assert ItemModel.query.filter_by(group_id=solo.id).count() == 0

    def test_answer_question_keeps_the_current_holder_streak(self, login_as, world, ctx):
        with ctx():
            solo = factories.make_group(world.admin, themes=["connerie"], name="Solo")
            won = factories.make_question(solo, days_ago=3, item_name="cape_puissante")
            db.session.add(ItemModel(user_id=world.admin.id, group_id=solo.id, item_name="cape_puissante",
                                     acquired_at=won.date))
            db.session.commit()
            old = factories.make_question(solo, days_ago=1, question_id=2, can_write=True, item_name="cape_puissante")
            factories.make_vote(old, world.admin, written_answer="a joke")
        login_as(world.admin).get(q_url(solo.id))
        with ctx():
            [item] = ItemModel.query.filter_by(group_id=solo.id).all()
            assert item.inactive_since is None
            today = QuestionModel.query.filter_by(group_id=solo.id).order_by(QuestionModel.date.desc()).first()
            [(held, streak)] = get_user_items_in_group(world.admin.id, solo.id, today.date)
            assert held.id == item.id and streak == 3

    def test_solo_player_without_votes_gets_no_item(self, login_as, world, ctx):
        with ctx():
            solo = factories.make_group(world.admin, themes=["connerie"], name="Solo")
            factories.make_question(solo, days_ago=1)
        login_as(world.admin).get(q_url(solo.id))
        with ctx():
            assert ItemModel.query.filter_by(group_id=solo.id).count() == 0

    def test_items_are_computed_from_the_groups_own_previous_question(self, login_as, world, group, ctx):
        with ctx():
            old = factories.make_question(group, days_ago=1)
            factories.make_vote(old, world.admin, [world.member])
            # another group's question sits between yesterday's and today's one
            midday = factories.latest_reset(group.id) - H(hours=12)
            db.session.add(QuestionModel(question_id=1, date=midday, theme="connerie", item_name="bonnet_honte",
                                         group_id=world.other_group.id))
            db.session.commit()
        login_as(world.admin).get(q_url(group.id))
        with ctx():
            assert ItemModel.query.filter_by(group_id=group.id, user_id=world.member.id).count() == 1

    def test_non_member_forbidden_and_nothing_generated(self, login_as, world, group, externals, ctx):
        assert login_as(world.outsider).get(q_url(group.id)).status_code == 403
        assert question_count(ctx, group) == 0
        assert not [e for e in externals.events if e["event"] == "new_question"]

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).get(q_url(9999)).status_code == 404

    def test_requires_login(self, anon, world):
        assert anon.get(q_url(world.group.id)).status_code == 401


# ------------------------------------------------------------------- history
class TestQuestionsByDate:
    def month_url(self, group, when):
        return q_url(group.id, when.month, when.year)

    def test_past_question_with_votes_is_listed(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group, days_ago=3)
            factories.make_vote(q, world.admin, [world.member])
        response = login_as(world.member).get(self.month_url(world.group, q.date))
        assert response.status_code == 200
        [item] = [x for x in response.get_json()["content"] if x["id"] == q.id]
        assert [v["voterUser"]["username"] for v in item["votes"]] == ["admin"]

    def test_past_question_without_votes_is_skipped(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group, days_ago=3)
        content = login_as(world.member).get(self.month_url(world.group, q.date)).get_json()["content"]
        assert all(x["id"] != q.id for x in content)

    def test_todays_votes_hidden_until_the_user_voted(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group)
            factories.make_vote(q, world.admin, [world.member])
        before = login_as(world.member).get(self.month_url(world.group, q.date)).get_json()["content"]
        assert [x["votes"] for x in before if x["id"] == q.id] == [[]]
        with ctx():
            factories.make_vote(q, world.member, [world.admin])
        after = login_as(world.member).get(self.month_url(world.group, q.date)).get_json()["content"]
        assert len([x for x in after if x["id"] == q.id][0]["votes"]) == 2

    def test_other_months_are_excluded(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group, days_ago=3)
            factories.make_vote(q, world.admin, [world.member])
        other_month = q.date - H(days=40)
        assert login_as(world.member).get(self.month_url(world.group, other_month)).get_json()["content"] == []

    def test_non_member_forbidden(self, login_as, world, ctx):
        with ctx():
            q = factories.make_question(world.group, days_ago=3)
            factories.make_vote(q, world.admin, [world.member])
        assert login_as(world.outsider).get(self.month_url(world.group, q.date)).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert login_as(world.admin).get(q_url(9999, 1, 2026)).status_code == 404


# ---------------------------------------------------------------------- vote
class TestVote:
    @pytest.fixture
    def today(self, world, ctx):
        with ctx():
            return factories.make_question(world.group)

    def vote(self, client, group, **body):
        return client.post(q_url(group.id, "vote"), json=body)

    def test_vote_by_user_id(self, login_as, world, today, externals, ctx):
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id])
        assert response.status_code == 200
        [vote] = response.get_json()["content"]
        assert vote["voterUser"]["id"] == world.member.id
        assert [t["id"] for t in vote["targets"]] == [world.admin.id]
        [event] = [e for e in externals.events if e["event"] == "new_vote"]
        assert event["to"] == str(world.group.id) and event["data"]["question_id"] == today.id
        with ctx():
            assert QuestionVote.query.count() == 1
            assert QuestionVoteTarget.query.one().votedUser_id == world.admin.id

    def test_vote_by_username(self, login_as, world, today):
        assert self.vote(login_as(world.member), world.group, votedUsers=["admin"]).status_code == 200

    def test_vote_with_matching_question_id(self, login_as, world, today):
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id], question_id=today.id)
        assert response.status_code == 200

    def test_cannot_vote_twice(self, login_as, world, today, ctx):
        client = login_as(world.member)
        assert self.vote(client, world.group, votedUsers=[world.admin.id]).status_code == 200
        assert self.vote(client, world.group, votedUsers=[world.member.id]).status_code == 400
        with ctx():
            assert QuestionVote.query.count() == 1

    def test_vote_is_visible_afterwards(self, login_as, world, today):
        client = login_as(world.member)
        self.vote(client, world.group, votedUsers=[world.admin.id])
        votes = client.get(q_url(world.group.id)).get_json()["content"]["votes"]
        assert len(votes) == 1

    @pytest.mark.parametrize("body", [
        {}, {"votedUsers": []}, {"votedUsers": "admin"}, {"votedUsers": [1, "admin"]}, {"votedUsers": None},
    ])
    def test_invalid_targets(self, login_as, world, today, body):
        assert self.vote(login_as(world.member), world.group, **body).status_code == 400

    def test_unknown_username(self, login_as, world, today):
        assert self.vote(login_as(world.member), world.group, votedUsers=["ghost"]).status_code == 404

    def test_partially_unknown_usernames(self, login_as, world, today):
        response = self.vote(login_as(world.member), world.group, votedUsers=["admin", "ghost"])
        assert response.status_code == 404

    def test_target_outside_the_group(self, login_as, world, today, ctx):
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.outsider.id])
        assert response.status_code == 400
        with ctx():
            assert QuestionVote.query.count() == 0

    def test_target_outside_the_group_by_username(self, login_as, world, today):
        assert self.vote(login_as(world.member), world.group, votedUsers=["outsider"]).status_code == 400

    def test_self_vote_allowed_by_default(self, login_as, world, today):
        assert self.vote(login_as(world.member), world.group, votedUsers=[world.member.id]).status_code == 200

    def test_self_vote_can_be_disabled(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, self_vote=False)
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.member.id])
        assert response.status_code == 400

    def test_vote_number_limit(self, login_as, world, today):
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id, world.member.id])
        assert response.status_code == 400

    def test_vote_number_limit_zero_means_unlimited(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, limit=0)
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id, world.member.id])
        assert response.status_code == 200

    def test_duplicate_targets_when_multiple_voting_flag_is_set(self, login_as, world, ctx):
        # Characterisation of the current rule: duplicated targets are refused when enableMultipleVoting is on.
        with ctx():
            factories.make_question(world.group, limit=0, multiple=True)
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id, world.admin.id])
        assert response.status_code == 400

    def test_written_answer(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, question_id=2, can_write=True)
        response = self.vote(login_as(world.member), world.group, writtenAnswer="my answer")
        assert response.status_code == 200
        assert response.get_json()["content"][0]["writtenAnswer"] == "my answer"

    def test_written_answer_required_when_question_is_writable(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, question_id=2, can_write=True)
        assert self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id]).status_code == 400

    def test_expired_question_cannot_be_voted(self, login_as, world, ctx):
        with ctx():
            factories.make_question(world.group, days_ago=2)
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id])
        assert response.status_code == 400 and "no longer open" in response.get_json()["message"]

    def test_stale_question_id_is_refused(self, login_as, world, today, ctx):
        with ctx():
            old = factories.make_question(world.group, days_ago=1)
        response = self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id], question_id=old.id)
        assert response.status_code == 400

    def test_group_without_question(self, login_as, world):
        assert self.vote(login_as(world.member), world.group, votedUsers=[world.admin.id]).status_code == 404

    def test_non_member_cannot_vote(self, login_as, world, today, ctx):
        response = self.vote(login_as(world.outsider), world.group, votedUsers=[world.admin.id])
        assert response.status_code == 403
        with ctx():
            assert QuestionVote.query.count() == 0

    def test_member_of_another_group_cannot_vote(self, login_as, world, today):
        assert self.vote(login_as(world.other), world.group, votedUsers=[world.admin.id]).status_code == 403

    def test_unknown_group(self, login_as, world):
        assert self.vote(login_as(world.member), type("G", (), {"id": 9999}), votedUsers=[1]).status_code == 404

    def test_requires_login(self, anon, world):
        assert self.vote(anon, world.group, votedUsers=[1]).status_code == 401
