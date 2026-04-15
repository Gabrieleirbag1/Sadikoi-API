import random
import os 
import json
import datetime

from models import GroupModel, QuestionModel
from db import add_to_db, delete_from_db, update_from_db, db

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
        question = group.questions.filter_by(questionId=question_data['questionId']).first()
        if not is_question_already_asked(question, mean_iteration + offset):
            return question_data, question.iteration if question else None
    # If no question found, pick the one with least iterations
    existing_questions = group.questions.all()
    if existing_questions:
        min_iter_question = min(existing_questions, key=lambda q: q.iteration)
        question_data = next(q for q in questions if q['questionId'] == min_iter_question.questionId)
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
        "questionId": question.questionId,
        "content": question.content,
        "theme": question.theme,
        "voteMyself": question.voteMyself,
        "canWrite": question.canWrite,
        "item": question.item
    }

def build_question_model(question_data, iteration, group) -> QuestionModel:
    return QuestionModel(
        questionId=question_data['questionId'],
        content=question_data['content'][language],
        theme=question_data['theme'][language],
        voteMyself=question_data['voteMyself'],
        canWrite=question_data['canWrite'],
        item=question_data['item'],
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
            existing_question = group.questions.filter_by(questionId=question_data['questionId']).first()
            existing_question.iteration = iteration + 1
            existing_question.date = datetime.datetime.now(datetime.timezone.utc)
            result = update_from_db()
        if result.get("error"):
            return result, 500
        return {"question": build_question_data(question if iteration is None else existing_question)}, 200
    
def vote_question(group_id, request) -> tuple[dict, int]:
    question_data = get_question(group_id)
    question = question_data[0].get("question")
    if not question:
        return {"message": "Question not found"}, 404
    