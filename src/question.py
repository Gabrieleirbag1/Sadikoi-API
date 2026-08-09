import random
import os 
import json
import datetime

from flask import Request
from flask_login import current_user

from models import GroupModel, ItemModel, QuestionModel, QuestionVoteTarget, UserModel, QuestionVote
from db import add_to_db, update_from_db, db

from lite_logging.lite_logging import log

from auth import get_user_object

from builder import build_item_model, build_question_response, build_user_response, build_question_model

from config import ALLOWED_LANGUAGES

json_path = os.path.join(os.path.dirname(__file__), 'data', 'questions.json')
with open(json_path, 'r') as f:
    questions = json.load(f)

MIN_QUESTION_INTERVAL = datetime.timedelta(hours=24)

def chose_random_question() -> dict:
    return random.choice(questions)

def get_question_counts_by_id(group: GroupModel) -> dict[int, int]:
    """Return a mapping of question_id -> number of times it has been asked in this group.

    This replaces the old stored `iteration` column: iteration is now simply
    "how many rows exist for this (group_id, question_id) pair", computed on
    the fly with a GROUP BY count.
    """
    rows = (
        db.session.query(QuestionModel.question_id, db.func.count(QuestionModel.id))
        .filter(QuestionModel.group_id == group.id)
        .group_by(QuestionModel.question_id)
        .all()
    )
    return {question_id: count for question_id, count in rows}

def get_question_iteration_count(group: GroupModel, question_id: int) -> int:
    """How many times this specific question_id has been asked in this group so far (0 if never)."""
    return (
        db.session.query(db.func.count(QuestionModel.id))
        .filter(QuestionModel.group_id == group.id, QuestionModel.question_id == question_id)
        .scalar()
    ) or 0

def get_mean_iterations_question(group: GroupModel, counts_by_id: dict[int, int] | None = None) -> int:
    """Mean number of times each already-asked question has been asked in this group."""
    counts_by_id = counts_by_id if counts_by_id is not None else get_question_counts_by_id(group)
    if not counts_by_id:
        return 1
    return sum(counts_by_id.values()) // len(counts_by_id)

def is_question_already_asked(current_count: int, mean_iteration: int) -> bool:
    """A question counts as 'already asked (enough)' once its count reaches the mean (+ offset)."""
    return current_count >= mean_iteration

def chose_question(group: GroupModel, offset: int = 0) -> dict:
    counts_by_id = get_question_counts_by_id(group)
    mean_iteration = get_mean_iterations_question(group, counts_by_id)
    for _ in range(len(questions)):
        question_data = chose_random_question()
        current_count = counts_by_id.get(question_data['question_id'], 0)
        if not is_question_already_asked(current_count, mean_iteration + offset):
            return question_data
    # If no question found, pick the one with the least occurrences so far
    if counts_by_id:
        min_question_id = min(counts_by_id, key=lambda qid: counts_by_id[qid])
        question_data = next(q for q in questions if q['question_id'] == min_question_id)
        return question_data
    else:
        # Fallback, shouldn't happen
        return chose_random_question()
    
def is_today_based_on_reset(question_or_vote: QuestionModel | QuestionVote, group: GroupModel) -> bool:
    """Check if the question or vote is from today based on the group's daily reset time.
    
    Returns True if the question or vote is from today, False otherwise."""
    if not question_or_vote:
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    reset_time = datetime.datetime.combine(now.date(), group.daily_reset_timestamp, tzinfo=datetime.timezone.utc)
    
    item_date = question_or_vote.date
    if item_date.tzinfo is None:
        item_date = item_date.replace(tzinfo=datetime.timezone.utc)

    if now < reset_time:
        start_time = reset_time - datetime.timedelta(days=1)
        end_time = reset_time
        log(f"Current time {now} is before reset time {reset_time}, checking window {start_time} - {end_time}", level="DEBUG")
    else:
        start_time = reset_time
        end_time = reset_time + datetime.timedelta(days=1)
        log(f"Current time {now} is after reset time {reset_time}, checking window {start_time} - {end_time}", level="DEBUG")

    return start_time <= item_date < end_time
    
def does_exist_question_today(group: GroupModel) -> bool:
    question = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question:
        return False

    # Normal case: question falls in the current reset-based "today" window
    if is_today_based_on_reset(question, group):
        return True

    now = datetime.datetime.now(datetime.timezone.utc)
    question_date = question.date
    if question_date.tzinfo is None:
        question_date = question_date.replace(tzinfo=datetime.timezone.utc)

    # ---------------------------------------------------------------------
    # Adjust for reset timestamp changes:
    # If the current reset time is later in the day than the time the question
    # was originally created at, extend MIN_QUESTION_INTERVAL by that difference
    # so a new question isn't generated before reaching today's new reset time.
    # ---------------------------------------------------------------------
    required_interval = MIN_QUESTION_INTERVAL

    # Compute what the reset time was on the date the question was set
    old_reset_time = datetime.datetime.combine(
        question_date.date(), group.daily_reset_timestamp, tzinfo=datetime.timezone.utc
    )
    
    # If the last question was recorded before the current reset time configuration,
    # add the positive shift delta to the required wait interval.
    time_shift = question_date - old_reset_time
    if time_shift < datetime.timedelta(0):
        # Reset time moved later in the day relative to when the question was set
        required_interval += abs(time_shift)

    if now - question_date < required_interval:
        log(
            f"Reset window excludes last question ({question_date}), but required interval "
            f"({required_interval}) has not passed; blocking new question",
            level="DEBUG",
        )
        return True

    return False

def does_exist_vote_today(group: GroupModel, user: UserModel) -> bool:
    """Whether `user` has already voted on the group's *current* question.

    Tied directly to the current question's id rather than a recomputed date
    window, so it isn't affected by daily_reset_timestamp changes after the
    question/vote were created.
    """
    question = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question or not does_exist_question_today(group):
        return False

    vote = QuestionVote.query.filter_by(
        group_id=group.id,
        voterUser_id=user.id,
        question_id=question.id,
    ).first()
    return vote is not None

def is_user_in_group(user: UserModel, group: GroupModel) -> bool:
    return user in group.users

def extract_votes_info(question: QuestionModel, group: GroupModel = None, date: datetime.date = None):
    votes: list[QuestionVote] = question.votes.all()
    votes_data = []
    if not group and not date:
        raise ValueError("Either group or date must be provided to filter votes.")
    for vote in votes:
        if date and vote.date.date() != date:
            continue
        vote_info = {
            "voterUser": build_user_response(vote.voterUser),
            "voteDate": vote.date.isoformat(),
            "writtenAnswer": vote.written_answer,
            "targets": [build_user_response(target.votedUser) for target in vote.targets]
        }
        votes_data.append(vote_info)
    return votes_data
    
def get_question(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404
    db.session.add(group)  # Ensure group is in session
    user_info = current_user.id or current_user.username
    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    if does_exist_question_today(group):
        question = group.questions.order_by(QuestionModel.date.desc()).first()
        votes = None
        if does_exist_vote_today(group, user):
            votes = extract_votes_info(question, group)
        return {"success": True, "message": "Question retrieved successfully", "content": build_question_response(question, votes)}, 200
    else:
        try:
            question_data = chose_question(group)
        except StopIteration:
            return {"success": False, "message": "No questions available or not found in the original list"}, 404
        print("Chosen question:", question_data)
        question = build_question_model(question_data, group, user.language if user.language in ALLOWED_LANGUAGES else 'en')
        result = add_to_db(question)
        if result.get("error"):
            return result, 500
        assign_items()
        return {"success": True, "message": "Question retrieved successfully", "content": build_question_response(question)}, 200
    
def get_questions_by_date(group_id: int, month: int, year: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404
    questions = group.questions.filter(db.extract('month', QuestionModel.date) == month, db.extract('year', QuestionModel.date) == year).all()
    questions_data = []
    for question in questions:
        votes = extract_votes_info(question, date=question.date.date())
        if not votes and not is_today_based_on_reset(question, group):
            continue
        questions_data.append(build_question_response(question, votes))

    return {"success": True, "message": f"Questions for month {month} and year {year} retrieved successfully", "content": questions_data}, 200

def vote_question(group_id: int, request: Request) -> tuple[dict, int]:
    written_answer = None
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404
    
    question: QuestionModel = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question:
        return {"success": False, "message": "Question not found"}, 404
    
    user_info = current_user.id or current_user.username
    if not user_info:
        return {"success": False, "message": "User info is required to vote"}, 400
    
    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if not group:
        return {"success": False, "message": "Group not found"}, 404
    
    if not is_user_in_group(user, group):
        return {"success": False, "message": "User is not a member of the group"}, 403

    if does_exist_vote_today(group, user):
        return {"success": False, "message": "User has already voted today"}, 400
    
    votedUsers = request.json.get("votedUsers")

    if question.canWrite:
        written_answer = request.json.get("writtenAnswer")
        if not written_answer:
            return {"success": False, "message": "No answer provided"}, 400
        
        db_question = group.questions.order_by(QuestionModel.date.desc()).first()
        vote = QuestionVote(
            voterUser_id=user.id,
            question_id=db_question.id,
            group_id=group_id,
            written_answer=written_answer,
            date=question.date
        )
    else:
        if not votedUsers:
            return {"success": False, "message": "No users voted"}, 400
        if not isinstance(votedUsers, list):
            return {"success": False, "message": "votedUsers must be a list"}, 400

        if all(isinstance(item_name, int) for item_name in votedUsers):
            votedUser_ids = votedUsers
        elif all(isinstance(item_name, str) for item_name in votedUsers):
            votedUsers = UserModel.query.filter(UserModel.username.in_(votedUsers)).all()
            if len(votedUsers) != len(votedUsers):
                return {"success": False, "message": "One or more voted users not found"}, 404
            votedUser_ids = [votedUser.id for votedUser in votedUsers]
        else:
            return {"success": False, "message": "votedUsers must contain only ids or usernames"}, 400

        if not question.enableSelfVote and user.id in votedUser_ids:
            return {"success": False, "message": "User cannot vote for themselves"}, 400

        if question.enableMultipleVoting and len(set(votedUser_ids)) != len(votedUser_ids):
            return {"success": False, "message": "User cannot vote multiple times"}, 400

        if question.voteNumberLimit != 0 and len(votedUser_ids) > question.voteNumberLimit:
            return {"success": False, "message": f"User cannot vote more than {question.voteNumberLimit} times"}, 400

        vote = QuestionVote(
            voterUser_id=user.id,
            question_id=question.id,
            group_id=group_id,
            date=question.date,
            targets=[QuestionVoteTarget(votedUser_id=votedUser_id) for votedUser_id in votedUser_ids]
        )

    db.session.add(vote)
    result = update_from_db()
    if result.get("error"):
        return result, 500
    return {"success": True, "message": "Vote recorded successfully", "content": extract_votes_info(question, group)}, 200

def assign_items():
    #get the last last question not counting the real last question, (it must have at least 2 questions in the group to work)
    last_question = QuestionModel.query.order_by(QuestionModel.date.desc()).offset(1).first()
    if not last_question:
        return
    most_voted_user = get_most_voted_user(last_question, last_question.group)
    if not most_voted_user:
        return
    
    if not delete_item_from_user(last_question.group, last_question.item_name)[0].get("success"):
        log(f"Error deleting item_name from user {most_voted_user.id} in group {last_question.group.id}", level="ERROR")
        return

    new_item = build_item_model(most_voted_user, last_question)
    result = add_to_db(new_item)
    if result.get("error"):
        log(f"Error assigning item_name: {result.get('error')}", level="ERROR")

def delete_item_from_user(group: GroupModel, item_name: str) -> tuple[dict, int]:
    # Delete the item_name from the user in the group if it exists
    item_to_delete = ItemModel.query.filter_by(group_id=group.id, item_name=item_name).first()
    if not item_to_delete:
        return {"success": True, "message": "Item not found for the user in the group"}, 404
    db.session.delete(item_to_delete)
    result = update_from_db()
    if result.get("error"):
        return {"success": False, "message": result.get("error")}, 500
    return {"success": True, "message": "Item deleted successfully"}, 200

def get_most_voted_user(question: QuestionModel, group: GroupModel) -> dict:
    #using get_votes_per_user method, get the most voted user, there must be not equality, if there is equality, return None
    votes_per_user = get_votes_per_user(question, group)
    if not votes_per_user["users"]:
        return None
    max_votes = max(votes_per_user["number_of_votes"])
    if votes_per_user["number_of_votes"].count(max_votes) > 1:
        return None
    max_index = votes_per_user["number_of_votes"].index(max_votes)
    return votes_per_user["users"][max_index]

def get_votes_per_user(question: QuestionModel, group: GroupModel) -> dict:
    """Count how many votes each user in the group received for this question, sorted descending."""
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