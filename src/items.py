from lite_logging.lite_logging import log

from models import ItemModel, QuestionModel, QuestionModel, QuestionVote, GroupModel
from builder import build_item_model, build_item_model, build_user_response
from db import add_to_db, update_from_db

def assign_items():
    """Assign items to the user with the most votes for the last question in the group. If there is a tie or no votes, no item will be assigned."""
    last_question = QuestionModel.query.order_by(QuestionModel.date.desc()).offset(1).first()
    if not last_question:
        return
    most_voted_user = get_most_voted_user(last_question, last_question.group)
    if not most_voted_user:
        return
    
    if not set_item_inactive(last_question.group, last_question.item_name)[0].get("success"):
        log(f"Error deleting item_name from user {most_voted_user.id} in group {last_question.group.id}", level="ERROR")
        return

    new_item = build_item_model(most_voted_user, last_question)
    result = add_to_db(new_item)
    if result.get("error"):
        log(f"Error assigning item_name: {result.get('error')}", level="ERROR")

def set_item_inactive(group: GroupModel, item_name: str) -> tuple[dict, int]:
    """
    
    :param GroupModel group: The group from which to delete the item_name.
    :param str item_name: The name of the item to delete.

    :return: A tuple containing a dictionary with the result and the HTTP status code.
    :rtype: tuple[dict, int]
    """
    item_to_set_inactive = ItemModel.query.filter_by(group_id=group.id, item_name=item_name).first()
    if not item_to_set_inactive:
        return {"success": True, "message": "Item not found for the user in the group"}, 404
    item_to_set_inactive.state = "inactive"
    result = update_from_db()
    if result.get("error"):
        return {"success": False, "message": result.get("error")}, 500
    return {"success": True, "message": "Item deleted successfully"}, 200

def get_most_voted_user(question: QuestionModel, group: GroupModel) -> dict | None:
    """Get the user with the most votes for a given question in a group. If there is a tie, return None.
    
    :param QuestionModel question: The question for which to find the most voted user.
    :param GroupModel group: The group containing the users.
    
    :return: The user with the most votes or None if there is a tie or no votes.
    :rtype: dict or None"""
    votes_per_user = get_votes_per_user(question, group)
    if not votes_per_user["users"]:
        return None
    max_votes = max(votes_per_user["number_of_votes"])
    if votes_per_user["number_of_votes"].count(max_votes) > 1:
        return None
    max_index = votes_per_user["number_of_votes"].index(max_votes)
    return votes_per_user["users"][max_index]

def get_votes_per_user(question: QuestionModel, group: GroupModel) -> dict:
    """Count how many votes each user in the group received for this question, sorted descending.
    
    :param QuestionModel question: The question for which to count votes.
    :param GroupModel group: The group containing the users.
    
    :return: A dictionary with two lists: 'users' containing user responses and 'number_of_votes' containing the corresponding vote counts.
    :rtype: dict"""
    number_votes_per_user = {"users": [], "number_of_votes": []}

    votes: list[QuestionVote] = question.votes.all()

    counts: dict[int, int] = {}
    for vote in votes:
        for target in vote.targets:
            counts[target.votedUser_id] = counts.get(target.votedUser_id, 0) + 1

    users_by_id = {user.id: user for user in group.users}
    for user in group.users:
        counts.setdefault(user.id, 0)

    sorted_user_ids = sorted(
        counts.keys(),
        key=lambda uid: (-counts[uid], users_by_id[uid].username if uid in users_by_id else "")
    )

    for uid in sorted_user_ids:
        user = users_by_id.get(uid)
        if not user:
            continue
        number_votes_per_user["users"].append(build_user_response(user))
        number_votes_per_user["number_of_votes"].append(counts[uid])

    return number_votes_per_user
