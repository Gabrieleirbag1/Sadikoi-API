"""questions/<group>/<question>/feedback/: like or dislike a question once its votes are shown."""
import pytest

from models import QuestionFeedbackModel
from tests import factories


def feedback_url(group_id, question_id):
    return f"/api/questions/{group_id}/{question_id}/feedback/"


@pytest.fixture
def today(world, ctx):
    with ctx():
        return factories.make_question(world.group)


@pytest.fixture
def voted(world, today, ctx):
    """Today's question, voted on by the admin."""
    with ctx():
        factories.make_vote(today, world.admin, [world.member])
    return today


class TestRateQuestion:
    @pytest.mark.parametrize("liked", [True, False])
    def test_rate_after_voting(self, login_as, world, voted, ctx, liked):
        response = login_as(world.admin).post(feedback_url(world.group.id, voted.id), json={"liked": liked})
        assert response.status_code == 201
        with ctx():
            feedback = QuestionFeedbackModel.query.one()
            assert (feedback.user_id, feedback.question_id, feedback.liked) == (world.admin.id, voted.id, liked)

    def test_only_once(self, login_as, world, voted, ctx):
        client = login_as(world.admin)
        assert client.post(feedback_url(world.group.id, voted.id), json={"liked": True}).status_code == 201
        assert client.post(feedback_url(world.group.id, voted.id), json={"liked": False}).status_code == 409
        with ctx():
            assert QuestionFeedbackModel.query.one().liked is True

    def test_once_per_member(self, login_as, world, voted, ctx):
        with ctx():
            factories.make_vote(voted, world.member, [world.admin])
        login_as(world.admin).post(feedback_url(world.group.id, voted.id), json={"liked": True})
        assert login_as(world.member).post(feedback_url(world.group.id, voted.id), json={"liked": False}).status_code == 201
        with ctx():
            assert QuestionFeedbackModel.query.count() == 2

    def test_current_question_needs_a_vote_first(self, login_as, world, today, ctx):
        response = login_as(world.admin).post(feedback_url(world.group.id, today.id), json={"liked": True})
        assert response.status_code == 400
        with ctx():
            assert QuestionFeedbackModel.query.count() == 0

    def test_past_question_without_voting(self, login_as, world, ctx):
        with ctx():
            past = factories.make_question(world.group, days_ago=2)
            factories.make_question(world.group)
        assert login_as(world.admin).post(feedback_url(world.group.id, past.id), json={"liked": False}).status_code == 201

    @pytest.mark.parametrize("body", [{}, {"liked": None}, {"liked": "yes"}, {"liked": 1}])
    def test_liked_must_be_a_boolean(self, login_as, world, voted, body):
        assert login_as(world.admin).post(feedback_url(world.group.id, voted.id), json=body).status_code == 400

    def test_question_of_another_group(self, login_as, world, ctx):
        with ctx():
            other_question = factories.make_question(world.other_group, days_ago=1)
        response = login_as(world.admin).post(feedback_url(world.group.id, other_question.id), json={"liked": True})
        assert response.status_code == 404

    def test_unknown_question(self, login_as, world):
        assert login_as(world.admin).post(feedback_url(world.group.id, 999), json={"liked": True}).status_code == 404

    def test_non_member_forbidden(self, login_as, world, voted, ctx):
        response = login_as(world.outsider).post(feedback_url(world.group.id, voted.id), json={"liked": True})
        assert response.status_code == 403
        with ctx():
            assert QuestionFeedbackModel.query.count() == 0

    def test_requires_login(self, anon, world, voted):
        assert anon.post(feedback_url(world.group.id, voted.id), json={"liked": True}).status_code == 401


class TestMyFeedback:
    def test_unrated_question(self, login_as, world, voted):
        content = login_as(world.admin).get(f"/api/questions/{world.group.id}/").get_json()["content"]
        assert content["my_feedback"] is None

    @pytest.mark.parametrize("liked", [True, False])
    def test_current_question(self, login_as, world, voted, liked):
        client = login_as(world.admin)
        client.post(feedback_url(world.group.id, voted.id), json={"liked": liked})
        assert client.get(f"/api/questions/{world.group.id}/").get_json()["content"]["my_feedback"] is liked

    def test_only_the_users_own_feedback(self, login_as, world, voted, ctx):
        with ctx():
            factories.make_question_feedback(voted, world.member, liked=False)
        content = login_as(world.admin).get(f"/api/questions/{world.group.id}/").get_json()["content"]
        assert content["my_feedback"] is None

    def test_history(self, login_as, world, voted, ctx):
        with ctx():
            factories.make_question_feedback(voted, world.admin, liked=True)
        date = voted.date
        [question] = login_as(world.admin).get(
            f"/api/questions/{world.group.id}/{date.month}/{date.year}/").get_json()["content"]
        assert question["my_feedback"] is True
