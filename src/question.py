import random
import os 
import json
import datetime

from models import GroupModel, QuestionModel
from db import add_to_db, delete_from_db, update_from_db

language = "en"  # or "fr" for French, depending on your needs

json_path = os.path.join(os.path.dirname(__file__), 'data', 'questions.json')
with open(json_path, 'r') as f:
    questions = json.load(f)

def chose_random_question() -> dict:
    return random.choice(questions)

def get_mean_iterations_question(group) -> int:
    if not group.questions.count():
        return 1
    return sum(question.iteration for question in group.questions) // group.questions.count()

def is_question_already_asked(group, question, iteration) -> bool:
    question = group.questions.filter_by(questionId=question['questionId']).first()
    if not question:
        return False
    elif question.iteration >= iteration:
        return True
    return False

def chose_question(group, offset = 0) -> dict :
    iteration = get_mean_iterations_question(group)
    for _ in range(len(questions)):
        question = chose_random_question()
        if not is_question_already_asked(group, question, iteration + offset):
            return question
    return chose_question(group, offset + 1)

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

def get_question(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404
    elif does_exist_question_today(group):
        question = group.questions.order_by(QuestionModel.date.desc()).first()
        return {"question": build_question_data(question)}, 200
    else:
        question_data = chose_question(group)
        print("Chosen question:", question_data)
        question = QuestionModel(
            questionId=question_data['questionId'],
            content=question_data['content'][language],
            theme=question_data['theme'][language],
            voteMyself=question_data['voteMyself'],
            canWrite=question_data['canWrite'],
            item=question_data['item'],
            group=group
        )
        result = add_to_db(question)
        if result.get("error"):
            return result, 500
        return {"question": build_question_data(question)}, 200