import random
import os 
import json
import datetime

from models import GroupModel, QuestionModel, QuestionVoteTarget, UserModel, QuestionVote
from db import add_to_db, delete_from_db, update_from_db, db

from lite_logging.lite_logging import log

language = "en"

json_path = os.path.join(os.path.dirname(__file__), 'data', 'questions.json')
with open(json_path, 'r') as f:
    questions = json.load(f)

def chose_random_question() -> dict:
    return random.choice(questions)

def get_mean_iterations_question(group) -> int:
    if not group.questions.count():
        return 1
    return sum(question.iteration for question in group.questions) // group.questions.count()

def is_question_already_asked(question, mean_iteration) -> bool | int:
    if not question:
        return False
    elif question.iteration >= mean_iteration:
        return True
    return False

def chose_question(group, offset = 0) -> dict :
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

def does_exist_question_today(group) -> bool:
    question = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question:
        return False
    return question.date.date() == datetime.datetime.now(datetime.timezone.utc).date()

def build_question_data(question) -> dict:
    return {
        "question_id": question.question_id,
        "content": question.content,
        "theme": question.theme,
        "enableSelfVote": question.enableSelfVote,
        "enableMultipleVoting": question.enableMultipleVoting,
        "voteNumberLimit": question.voteNumberLimit,
        "canWrite": question.canWrite,
        "item": question.item
    }

def build_question_model(question_data, iteration, group) -> QuestionModel:
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

def get_question(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404
    db.session.add(group)  # Ensure group is in session
    if does_exist_question_today(group):
        question = group.questions.order_by(QuestionModel.date.desc()).first()
        return {"question": build_question_data(question)}, 200
    else:
        question_data, iteration = chose_question(group)
        print("Chosen question:", question_data)
        if iteration is None:
            question = build_question_model(question_data, 1, group)
            result = add_to_db(question)
        else:
            existing_question = group.questions.filter_by(question_id=question_data['question_id']).first()
            existing_question.iteration = iteration + 1
            existing_question.date = datetime.datetime.now(datetime.timezone.utc)
            result = update_from_db()
        if result.get("error"):
            return result, 500
        return {"question": build_question_data(question if iteration is None else existing_question)}, 200
    
def vote_question(group_id, request) -> tuple[dict, int]:
    written_answer = None
    question_data = get_question(group_id)
    question = question_data[0].get("question")
    log(f"Voting on question: {question}")
    if not question:
        return {"message": "Question not found"}, 404
    
    username = request.json.get("username")
    if not username:
        return {"message": "Username is required to vote"}, 400
    
    user = UserModel.query.filter_by(username=username).first()
    if not user:
        return {"message": "User not found"}, 404
    
    votedUsers = request.json.get("votedUsers")

    if question.get("canWrite"):
        written_answer = request.json.get("writtenAnswer")
        if not written_answer:
            return {"message": "No answer provided"}, 400
        vote = QuestionVote(
            voterUser_id=user.id,
            question_id=question['question_id'],
            group_id=group_id,
            written_answer=written_answer,
        )
    else:
        if not votedUsers:
            return {"message": "No users voted"}, 400
        if not isinstance(votedUsers, list):
            return {"message": "votedUsers must be a list"}, 400

        if all(isinstance(item, int) for item in votedUsers):
            votedUser_ids = votedUsers
        elif all(isinstance(item, str) for item in votedUsers):
            votedUsers = UserModel.query.filter(UserModel.username.in_(votedUsers)).all()
            if len(votedUsers) != len(votedUsers):
                return {"message": "One or more voted users not found"}, 404
            votedUser_ids = [votedUser.id for votedUser in votedUsers]
        else:
            return {"message": "votedUsers must contain only ids or usernames"}, 400

        if not question.get("enableSelfVote") and user.id in votedUser_ids:
            return {"message": "User cannot vote for themselves"}, 400

        if question.get("enableMultipleVoting") and len(set(votedUser_ids)) != len(votedUser_ids):
            return {"message": "User cannot vote multiple times"}, 400

        if question.get("voteNumberLimit") != 0 and len(votedUser_ids) > question.get("voteNumberLimit"):
            return {"message": f"User cannot vote more than {question.get('voteNumberLimit')} times"}, 400

        vote = QuestionVote(
            voterUser_id=user.id,
            question_id=question['question_id'],
            group_id=group_id,
            targets=[QuestionVoteTarget(votedUser_id=votedUser_id) for votedUser_id in votedUser_ids]
        )

    db.session.add(vote)
    result = update_from_db()
    if result.get("error"):
        return result, 500
    return {"message": "Vote recorded successfully"}, 200