import datetime

from lite_logging.lite_logging import log

from models import ItemAnnouncement, ItemModel, QuestionModel, QuestionVote, GroupModel
from builder import build_item_model, build_user_response, streak_at
from db import add_to_db, update_from_db

def assign_items(question: QuestionModel, group: GroupModel) -> None:
    """Give the last question's item to its most voted user, and record what happened as the
    announcement of `question` (the new day's question).

    - nobody held the item: "new"
    - another user held it: "stolen" (the item moves, `streak` is the one the previous holder lost)
    - the winner already held it: "kept" (the item is not touched, so the streak keeps growing)

    Nobody wins the item after a written-answer question (canWrite, even in a single-player group),
    a tie or a day without votes: the items stay where they are and the previous day's
    announcement is repeated as "kept"."""
    last_question: QuestionModel | None = (
        QuestionModel.query
        .filter(QuestionModel.group_id == group.id, QuestionModel.date < question.date)
        .order_by(QuestionModel.date.desc())
        .first()
    )
    if not last_question:
        return
    most_voted_user = None if last_question.canWrite else get_most_voted_user(last_question, group)
    if not most_voted_user:
        repeat_previous_announcement(last_question, question, group)
        return

    holder = get_active_item(group, last_question.item_name)
    if holder and holder.user_id == most_voted_user["id"]:
        save_announcement(question, "kept", holder.user_id, holder.item_name, streak_at(holder, question.date))
        return

    from_user_id, lost_streak = (holder.user_id, streak_at(holder, question.date)) if holder else (None, 0)
    if not set_item_inactive(group, last_question.item_name, question.date)[0].get("success"):
        log(f"Error deleting item_name from user {most_voted_user['id']} in group {last_question.group_id}", level="ERROR")
        return

    new_item = build_item_model(most_voted_user, last_question)
    result = add_to_db(new_item)
    if result.get("error"):
        log(f"Error assigning item_name: {result.get('error')}", level="ERROR")
        return

    if holder:
        save_announcement(question, "stolen", new_item.user_id, new_item.item_name, lost_streak, from_user_id)
    else:
        save_announcement(question, "new", new_item.user_id, new_item.item_name, streak_at(new_item, question.date))

def repeat_previous_announcement(last_question: QuestionModel, question: QuestionModel, group: GroupModel) -> None:
    """Nobody won yesterday's item: announce again that yesterday's subject keeps their item."""
    previous: ItemAnnouncement | None = last_question.announcement
    if not previous:
        return
    item = get_active_item(group, previous.item_name)
    if not item or item.user_id != previous.user_id or item.user_id not in {user.id for user in group.users}:
        return
    save_announcement(question, "kept", item.user_id, item.item_name, streak_at(item, question.date))

def save_announcement(question: QuestionModel, kind: str, user_id: int, item_name: str, streak: int,
                      from_user_id: int | None = None) -> None:
    announcement = ItemAnnouncement(question_id=question.id, kind=kind, user_id=user_id, item_name=item_name,
                                    from_user_id=from_user_id, streak=streak)
    result = add_to_db(announcement)
    if result.get("error"):
        log(f"Error saving the item announcement of question {question.id}: {result.get('error')}", level="ERROR")

def get_active_item(group: GroupModel, item_name: str) -> ItemModel | None:
    """The item of this name currently held in the group (at most one user holds it)."""
    return (ItemModel.query
            .filter_by(group_id=group.id, item_name=item_name)
            .filter(ItemModel.inactive_since.is_(None))
            .first())

def set_item_inactive(group: GroupModel, item_name: str, date: datetime.datetime) -> tuple[dict, int]:
    """
    Set the inactive_since date for an item in a group, effectively marking it as deleted.
    
    :param GroupModel group: The group from which to delete the item_name.
    :param str item_name: The name of the item to delete.
    :param datetime.datetime date: The date to set as the inactive since date.

    :return: A tuple containing a dictionary with the result and the HTTP status code.
    :rtype: tuple[dict, int]
    """
    item_to_set_inactive = get_active_item(group, item_name)  # only items that are currently active
    if not item_to_set_inactive:
        return {"success": True, "message": "Item not found for the user in the group"}, 404
    item_to_set_inactive.inactive_since = date
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
    # Nobody can win with zero votes (e.g. a single-player group that did not vote).
    if max_votes == 0 or votes_per_user["number_of_votes"].count(max_votes) > 1:
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
