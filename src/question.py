import random
import os 
import json
import datetime

from flask import Request
from flask_login import current_user

from models import GroupModel, QuestionModel, QuestionVoteTarget, UserModel, QuestionVote
from db import add_to_db, update_from_db, db

from lite_logging.lite_logging import log

from auth import get_user_object

from builder import build_question_response, build_user_response

from config import ALLOWED_LANGUAGES

json_path = os.path.join(os.path.dirname(__file__), 'data', 'questions.json')
with open(json_path, 'r') as f:
    questions = json.load(f)

def chose_random_question() -> dict:
    return random.choice(questions)

def get_mean_iterations_question(group: GroupModel) -> int:
    if not group.questions.count():
        return 1
    return sum(question.iteration for question in group.questions) // group.questions.count()

def is_question_already_asked(question: QuestionModel | None, mean_iteration: int) -> bool | int:
    if not question:
        return False
    elif question.iteration >= mean_iteration:
        return True
    return False

def chose_question(group: GroupModel, offset: int = 0) -> dict :
    mean_iteration = get_mean_iterations_question(group)
    for _ in range(len(questions)):
        question_data = chose_random_question()
        question = group.questions.filter_by(question_id=question_data['question_id']).first()
        if not is_question_already_asked(question, mean_iteration + offset):
            return question_data, question.iteration if question else None
    # If no question found, pick the one with least iterations
    existing_questions = group.questions.all()
    if existing_questions:
        min_iter_question = min(existing_questions, key=lambda q: q.iteration)
        question_data = next(q for q in questions if q['question_id'] == min_iter_question.question_id)
        return question_data, min_iter_question.iteration
    else:
        # Fallback, shouldn't happen
        return chose_random_question(), None
    
def check_date(question_or_vote: QuestionModel | QuestionVote, group: GroupModel) -> bool:
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
    return check_date(question, group)

def does_exist_vote_today(group: GroupModel, user: UserModel) -> bool:
    vote = QuestionVote.query.filter_by(group_id=group.id, voterUser_id=user.id).order_by(QuestionVote.date.desc()).first()
    return check_date(vote, group)

def is_user_in_group(user: UserModel, group: GroupModel) -> bool:
    return user in group.users

def build_question_model(question_data: dict, iteration: int, group: GroupModel, language: str) -> QuestionModel:
    return QuestionModel(
        question_id=question_data['question_id'],
        content=question_data['content'][language],
        theme=question_data['theme'][language],
        enableSelfVote=question_data['enableSelfVote'],
        enableMultipleVoting=question_data['enableMultipleVoting'],
        voteNumberLimit=question_data['voteNumberLimit'],
        canWrite=question_data['canWrite'],
        item=question_data['item']["id"],
        iteration=iteration,
        group=group
    )

def extract_votes_info(question: QuestionModel):
    votes: list[QuestionVote] = question.votes.all()
    votes_data = []
    for vote in votes:
        vote_info = {
            "voterUser": build_user_response(vote.voterUser),
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
        if does_exist_vote_today(group, current_user):
            votes = extract_votes_info(question)
        return {"success": True, "message": "Question retrieved successfully", "content": build_question_response(question, votes)}, 200
    else:
        question_data, iteration = chose_question(group)
        print("Chosen question:", question_data)
        if iteration is None:
            question = build_question_model(question_data, 1, group, user.language if user.language in ALLOWED_LANGUAGES else 'en')
            result = add_to_db(question)
        else:
            existing_question = group.questions.filter_by(question_id=question_data['question_id']).first()
            existing_question.iteration = iteration + 1
            existing_question.date = datetime.datetime.now(datetime.timezone.utc)
            result = update_from_db()
        if result.get("error"):
            return result, 500
        return {"success": True, "message": "Question retrieved successfully", "content": build_question_response(question if iteration is None else existing_question)}, 200
    
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
    
    group = GroupModel.query.get(group_id)
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
        )
    else:
        if not votedUsers:
            return {"success": False, "message": "No users voted"}, 400
        if not isinstance(votedUsers, list):
            return {"success": False, "message": "votedUsers must be a list"}, 400

        if all(isinstance(item, int) for item in votedUsers):
            votedUser_ids = votedUsers
        elif all(isinstance(item, str) for item in votedUsers):
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
            targets=[QuestionVoteTarget(votedUser_id=votedUser_id) for votedUser_id in votedUser_ids]
        )

    db.session.add(vote)
    result = update_from_db()
    if result.get("error"):
        return result, 500
    return {"success": True, "message": "Vote recorded successfully", "content": extract_votes_info(question)}, 200