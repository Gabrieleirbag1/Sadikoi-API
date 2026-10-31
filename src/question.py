import random
import datetime
import threading

from flask import Request
from flask_login import current_user
from lite_logging.lite_logging import log

from models import GroupModel, QuestionModel, QuestionVoteTarget, UserModel, QuestionVote
from db import add_to_db, update_from_db, db
from auth import get_user_object
from items import assign_items
from builder import build_announcement_response, build_item_response, build_question_response, build_user_response, build_question_model, get_user_items_in_group, current_window_start
from config import ALLOWED_LANGUAGES
from sockets import socketio
from notifications import notify_new_answer
from utils import question_pool


MIN_QUESTION_INTERVAL = datetime.timedelta(hours=24)
# The app asks for the new question as soon as its countdown ends, so every open phone of a group calls
# get_question at the same second: only one of them may create it (the API runs in a single process).
_question_creation_lock = threading.Lock()

# =============================================================================
# TEMPORARY: RANKING questions are not implemented yet (no ranking vote UI or
# scoring), so they must never be given to a group.
# Remove this block, and the `is_question_type_disabled` call in
# is_question_allowed, once RANKING is supported.
# Questions without a `type` field are allowed.
# =============================================================================
DISABLED_QUESTION_TYPES = {"ranking"}

def is_question_type_disabled(question: dict) -> bool:
    """TEMPORARY: whether this question's type can't be given yet (see DISABLED_QUESTION_TYPES)."""
    return str(question.get("type", "")).lower() in DISABLED_QUESTION_TYPES
# ============================ END TEMPORARY ==================================

def count_vote_candidates(enable_self_vote: bool, member_count: int) -> int:
    """How many members a voter can pick from: everyone, minus themselves when self-voting is off.

    :param bool enable_self_vote: Whether the voter can vote for themselves.
    :param int member_count: Number of members in the group.

    :return: The number of members the voter can vote for.
    :rtype: int"""
    return member_count if enable_self_vote else member_count - 1

def required_vote_count(question: QuestionModel, member_count: int) -> int:
    """How many members a vote must target: `voteNumberLimit` for multi-target questions
    with a limit (e.g. DUO = 2), 1 otherwise. Capped by the number of candidates, in case
    members left the group after the question was given.

    :param QuestionModel question: The question being voted on.
    :param int member_count: Number of members in the group.

    :return: The number of members the vote must target.
    :rtype: int"""
    if question.enableMultipleVoting and question.voteNumberLimit > 0:
        return min(question.voteNumberLimit, count_vote_candidates(question.enableSelfVote, member_count))
    return 1

def is_question_playable(question: dict, member_count: int) -> bool:
    """Whether the group has enough members for this question to be voted on.

    A voter must be able to pick `voteNumberLimit` members other than themselves when
    self-voting is off: a DUO question (2 picks, no self vote) needs at least 3 members.

    :param dict question: The question data from the question pool.
    :param int member_count: Number of members in the group.

    :return: True if the question can be given to the group, False otherwise.
    :rtype: bool"""
    if question.get('canWrite'):
        return True
    needed = question['voteNumberLimit'] if question['enableMultipleVoting'] and question['voteNumberLimit'] > 0 else 1
    return count_vote_candidates(question['enableSelfVote'], member_count) >= needed

def is_question_allowed(question: dict, member_count: int) -> bool:
    """Whether this question can be given to a group of `member_count` members."""
    return not is_question_type_disabled(question) and is_question_playable(question, member_count)

def chose_random_question(themes: list, member_count: int) -> dict:
    """Choose a random question from the question pool that matches the given themes
    and can be played with the group's number of members.
    
    :param list themes: The group's selected theme ids.
    :param int member_count: Number of members in the group.

    :return: A dictionary containing the chosen question data.
    :rtype: dict"""
    matching_questions = [
        question for question in question_pool
        if question['theme']['id'] in themes
        and is_question_allowed(question, member_count)
    ]
    if not matching_questions:
        raise StopIteration("No questions match the group's selected themes")
    return random.choice(matching_questions)

def get_question_counts_by_id(group: GroupModel) -> dict[int, int]:
    """Return a mapping of question_id -> number of times it has been asked in this group.

    This replaces the old stored `iteration` column: iteration is now simply
    "how many rows exist for this (group_id, question_id) pair", computed on
    the fly with a GROUP BY count.

    :param GroupModel group: The group for which to count questions.

    :return: A dictionary mapping question_id to the number of times it has been asked in the group.
    :rtype: dict[int, int]
    """
    rows = (
        db.session.query(QuestionModel.question_id, db.func.count(QuestionModel.id))
        .filter(QuestionModel.group_id == group.id)
        .group_by(QuestionModel.question_id)
        .all()
    )
    return {question_id: count for question_id, count in rows}

def get_question_iteration_count(group: GroupModel, question_id: int) -> int:
    """How many times this specific question_id has been asked in this group so far (0 if never).
    
    :param GroupModel group: The group to check.
    :param int question_id: The question_id to check.
    
    :return: The number of times the question has been asked in the group.
    :rtype: int"""
    return (
        db.session.query(db.func.count(QuestionModel.id))
        .filter(QuestionModel.group_id == group.id, QuestionModel.question_id == question_id)
        .scalar()
    ) or 0

def get_mean_iterations_question(group: GroupModel, counts_by_id: dict[int, int] | None = None) -> int:
    """Mean number of times each already-asked question has been asked in this group.
    
    :param GroupModel group: The group for which to compute the mean.
    :param dict[int, int] counts_by_id: Optional; a precomputed mapping of question_id -> number of times it has been asked in this group. If not provided, it will be computed.
    
    :return: The mean number of times each question has been asked in the group.
    :rtype: int"""
    counts_by_id = counts_by_id if counts_by_id is not None else get_question_counts_by_id(group)
    if not counts_by_id:
        return 1
    return sum(counts_by_id.values()) // len(counts_by_id)

def is_question_already_asked(current_count: int, mean_iteration: int) -> bool:
    """A question counts as 'already asked (enough)' once its count reaches the mean (+ offset).
    
    :param int current_count: How many times this question has been asked in the group.
    :param int mean_iteration: The mean number of times questions have been asked in the group
    
    :return: True if the question has been asked enough times, False otherwise.
    :rtype: bool"""
    return current_count >= mean_iteration

def chose_question(group: GroupModel, offset: int = 0) -> dict:
    """Choose a question for the group, preferring questions that have been asked less than the mean number of times.
    
    :param GroupModel group: The group for which to choose a question.
    :param int offset: Optional; an offset to add to the mean iteration count for determining if a question has been asked enough. Default is 0.
    
    :return: A dictionary containing the chosen question data.
    :rtype: dict"""
    member_count = len(group.users)
    counts_by_id = get_question_counts_by_id(group)
    mean_iteration = get_mean_iterations_question(group, counts_by_id)
    for _ in range(len(question_pool)):
        question_data = chose_random_question(group.themes, member_count)
        current_count = counts_by_id.get(question_data['question_id'], 0)
        if not is_question_already_asked(current_count, mean_iteration + offset):
            return question_data
    # If no question found, pick the one with the least occurrences so far, among those
    # the group can still play (themes and member count may have changed since)
    allowed_ids = {
        q['question_id'] for q in question_pool
        if q['theme']['id'] in group.themes and is_question_allowed(q, member_count)
    }
    counts_by_id = {qid: count for qid, count in counts_by_id.items() if qid in allowed_ids}
    if counts_by_id:
        min_question_id = min(counts_by_id, key=lambda qid: counts_by_id[qid])
        question_data = next(q for q in question_pool if q['question_id'] == min_question_id)
        return question_data
    else:
        # Fallback, shouldn't happen
        return chose_random_question(group.themes, member_count)
    
def is_today_based_on_reset(question_or_vote: QuestionModel | QuestionVote, group: GroupModel) -> bool:
    """Check if the question or vote is from today based on the group's daily reset time.
    
    :param QuestionModel | QuestionVote question_or_vote: The question or vote to check.
    :param GroupModel group: The group to check against.
    
    :return: True if the question or vote is from today based on the group's reset time, False otherwise.
    :rtype: bool"""
    if not question_or_vote:
        return False

    item_date = question_or_vote.date
    if item_date.tzinfo is None:
        item_date = item_date.replace(tzinfo=datetime.timezone.utc)

    start_time = current_window_start(group)
    end_time = start_time + datetime.timedelta(days=1)
    log(f"Checking window {start_time} - {end_time}", level="DEBUG")

    return start_time <= item_date < end_time
    
def does_exist_question_today(group: GroupModel) -> bool:
    """Check if there is a question for today based on the group's daily reset time.
    
    :param GroupModel group: The group to check for today's question.
    
    :return: True if there is a question for today, False otherwise.
    :rtype: bool
    """
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

def does_exist_vote_today(group: GroupModel, user: UserModel) -> tuple[bool, QuestionModel | None]:
    """Whether `user` has already voted on the group's *current* question.

    Tied directly to the current question's id rather than a recomputed date
    window, so it isn't affected by daily_reset_timestamp changes after the
    question/vote were created.

    :param GroupModel group: The group to check for today's question.
    :param UserModel user: The user to check for a vote.

    :return: A tuple containing whether the user has voted today and the
        current question, if one exists.
    :rtype: tuple[bool, QuestionModel | None]
    """
    question = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question or not does_exist_question_today(group):
        return False, question

    vote = QuestionVote.query.filter_by(
        group_id=group.id,
        voterUser_id=user.id,
        question_id=question.id,
    ).first()
    return vote is not None, question

def next_question_time(group: GroupModel, question: QuestionModel) -> datetime.datetime:
    """When get_question will create the question after `question` (same rules as does_exist_question_today).

    Usually the group's next reset; later if the reset time was moved and the 24 h interval isn't over then.
    """
    question_date = question.date
    if question_date.tzinfo is None:
        question_date = question_date.replace(tzinfo=datetime.timezone.utc)
    # The question no longer belongs to the current window...
    first_reset_after = current_window_start(group, question_date) + datetime.timedelta(days=1)
    # ...and the required interval since it was set has passed.
    old_reset_time = datetime.datetime.combine(
        question_date.date(), group.daily_reset_timestamp, tzinfo=datetime.timezone.utc
    )
    required_interval = MIN_QUESTION_INTERVAL + max(datetime.timedelta(0), old_reset_time - question_date)
    return max(first_reset_after, question_date + required_interval)

def is_user_in_group(user: UserModel, group: GroupModel) -> bool:
    """Check if a user is a member of a group.
    
    :param UserModel user: The user to check.
    :param GroupModel group: The group to check against.
    
    :return: True if the user is in the group, False otherwise.
    :rtype: bool"""
    return user in group.users

def get_group_for_member(group_id: int) -> tuple[GroupModel | None, UserModel | None, tuple[dict, int] | None]:
    """Load a group and the current user, making sure the user is a member of the group.

    :param int group_id: The ID of the group.

    :return: (group, user, error); error is the (response, status) to return when the access is denied, else None.
    :rtype: tuple[GroupModel | None, UserModel | None, tuple[dict, int] | None]"""
    group = GroupModel.query.get(group_id)
    if not group:
        return None, None, ({"success": False, "message": "Group not found"}, 404)
    user = get_user_object(current_user.id or current_user.username)
    if not user:
        return None, None, ({"success": False, "message": "User not found"}, 404)
    if not is_user_in_group(user, group):
        return None, None, ({"success": False, "message": "User is not a member of the group"}, 403)
    return group, user, None

def extract_votes_info(question: QuestionModel, group: GroupModel, date: datetime.date = None):
    """Extract detailed information about votes for a given question, optionally filtered by group and date.
    
    :param QuestionModel question: The question for which to extract vote information.
    :param GroupModel group: Optional; the group to filter votes by.
    :param datetime.date date: Optional; the date to filter votes by.

    :return: A list of dictionaries containing the extracted vote information.
    :rtype: list[dict]"""
    votes: list[QuestionVote] = question.votes.all()
    votes_data = []
    if not group and not date:
        raise ValueError("Either group or date must be provided to filter votes.")
    for vote in votes:
        if date and vote.date.date() != date:
            continue

        voterUser =  build_user_response(vote.voterUser)
        voterUser["items"] = [build_item_response(item, streak) for item, streak in get_user_items_in_group(voterUser["id"], group.id, question.date)]
        targets = [build_user_response(target.votedUser) for target in vote.targets]
        for target in targets:
            target["items"] = [build_item_response(item, streak) for item, streak in get_user_items_in_group(target["id"], group.id, question.date)]

        vote_info = {
            "voterUser": voterUser,
            "voteDate": vote.date.isoformat(),
            "writtenAnswer": vote.written_answer,
            "targets": targets
        }
        votes_data.append(vote_info)
    return votes_data
    
def get_question(group_id: int) -> tuple[dict, int]:
    """Retrieve the current question for a group, or generate a new one if none exists for today.
    
    :param int group_id: The ID of the group for which to retrieve the question.
    
    :return: A tuple containing a dictionary with the result and the HTTP status code.
    :rtype: tuple[dict, int]"""
    group, user, error = get_group_for_member(group_id)
    if error:
        return error
    db.session.add(group)  # Ensure group is in session
    language = user.language if user.language in ALLOWED_LANGUAGES else 'en'
    created = False
    if not does_exist_question_today(group):
        with _question_creation_lock:
            # Checked again: another request may have created it while this one waited.
            if not does_exist_question_today(group):
                try:
                    question_data = chose_question(group)
                except StopIteration:
                    return {"success": False, "message": "No questions available or not found in the original list"}, 404
                question = build_question_model(question_data, group)
                result = add_to_db(question)
                if result.get("error"):
                    return result, 500
                log(f"New question {question_data['question_id']} of the day for group {group_id}", level="INFO")
                assign_items(question, group)
                created = True

    question = group.questions.order_by(QuestionModel.date.desc()).first()
    votes = None
    if not created:
        has_user_voted_today, _ = does_exist_vote_today(group, user)
        if has_user_voted_today:
            votes = extract_votes_info(question, group)
    else:
        socketio.emit('new_question', {"group_id": group_id}, to=str(group_id))
    announcement = build_announcement_response(question.announcement, group, question.date)
    content = build_question_response(question, question_pool, language, votes, announcement)
    # The app counts down to it, then asks for the new question.
    content["next_question_at"] = next_question_time(group, question).isoformat()
    return {"success": True, "message": "Question retrieved successfully", "content": content}, 200
    
def get_questions_by_date(group_id: int, month: int, year: int) -> tuple[dict, int]:
    """Retrieve all questions for a group filtered by month and year.
    
    :param int group_id: The ID of the group for which to retrieve questions.
    :param int month: The month to filter questions by (1-12).
    :param int year: The year to filter questions by (e.g., 2024).
    
    :return: A tuple containing a dictionary with the result and the HTTP status code.
    :rtype: tuple[dict, int]"""
    group, user, error = get_group_for_member(group_id)
    if error:
        return error
    questions = group.questions.filter(db.extract('month', QuestionModel.date) == month, db.extract('year', QuestionModel.date) == year).all()
    questions_data = []
    for question in questions:
        votes = extract_votes_info(question, group, question.date.date())
        if not votes and not is_today_based_on_reset(question, group):
            continue
        has_user_voted_to_this_question = any(vote['voterUser']['id'] == user.id for vote in votes)
        if not has_user_voted_to_this_question and is_today_based_on_reset(question, group):
            votes = []
        questions_data.append(build_question_response(question, question_pool, user.language if user.language in ALLOWED_LANGUAGES else 'en', votes))

    return {"success": True, "message": f"Questions for month {month} and year {year} retrieved successfully", "content": questions_data}, 200

def vote_question(group_id: int, request: Request) -> tuple[dict, int]:
    """Handle voting for the current question in a group, either by selecting users or providing a written answer.
    
    :param int group_id: The ID of the group for which to vote on the current question.
    :param Request request: The Flask request object containing the vote data.

    :return: A tuple containing a dictionary with the result and the HTTP status code.
    :rtype: tuple[dict, int]"""
    written_answer = None
    group, user, error = get_group_for_member(group_id)
    if error:
        return error

    question: QuestionModel = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question:
        return {"success": False, "message": "Question not found"}, 404

    # Only the current day's question can be voted on.
    if not does_exist_question_today(group):
        return {"success": False, "message": "Question is no longer open"}, 400
    question_id = request.json.get("question_id")
    if question_id is not None and question_id != question.id:
        return {"success": False, "message": "Question is no longer open"}, 400

    has_user_voted_today, _ = does_exist_vote_today(group, user)
    if has_user_voted_today:
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
            requested_names = votedUsers
            found_users = UserModel.query.filter(UserModel.username.in_(requested_names)).all()
            if len(found_users) != len(set(requested_names)):
                return {"success": False, "message": "One or more voted users not found"}, 404
            votedUser_ids = [votedUser.id for votedUser in found_users]
        else:
            return {"success": False, "message": "votedUsers must contain only ids or usernames"}, 400

        member_ids = {member.id for member in group.users}
        if not all(voted_id in member_ids for voted_id in votedUser_ids):
            return {"success": False, "message": "Voted users must be members of the group"}, 400

        if not question.enableSelfVote and user.id in votedUser_ids:
            return {"success": False, "message": "User cannot vote for themselves"}, 400

        if question.enableMultipleVoting and len(set(votedUser_ids)) != len(votedUser_ids):
            return {"success": False, "message": "User cannot vote multiple times"}, 400

        if question.voteNumberLimit != 0 and len(votedUser_ids) > question.voteNumberLimit:
            return {"success": False, "message": f"User cannot vote more than {question.voteNumberLimit} times"}, 400

        required_votes = required_vote_count(question, len(group.users))
        if len(set(votedUser_ids)) < required_votes:
            return {"success": False, "message": f"User must vote for {required_votes} different members"}, 400

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

    log(f"User {user.id} voted on question {question.id} in group {group_id}", level="INFO")
    votes = extract_votes_info(question, group)
    socketio.emit('new_vote', {"question_id": question.id, "votes": votes}, to=str(group_id))
    notify_new_answer(group, user)

    return {"success": True, "message": "Vote recorded successfully", "content": votes}, 200