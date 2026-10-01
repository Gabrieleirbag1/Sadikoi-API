import datetime

from flask_login import current_user

from models import ChatMessageModel, GroupModel, QuestionModel
from flask import Request, request
from db import add_to_db
from auth import get_user_object
from builder import build_chat_message_response
from sockets import socketio

def _as_utc(value: datetime.datetime) -> datetime.datetime:
    """Return `value` as an aware UTC datetime (SQLite hands back naive datetimes)."""
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)

def get_question_window(group: GroupModel, question: QuestionModel) -> tuple[datetime.datetime, datetime.datetime | None]:
    """Return the [start, end) window of chat messages that belong to a question's "day".

    A day starts at the question's date (which is the group's reset time) and lasts until the
    next question of the group, capped at 24h so gaps without questions don't leak into it.
    The window of the group's current question has no end (it is still open). Since the reset
    time can be changed over time, a day can span two calendar days, hence the use of question dates
    rather than calendar days.

    :param GroupModel group: The group the question belongs to.
    :param QuestionModel question: The question whose window to compute.

    :return: The start and the (exclusive) end of the window; the end is None if the window is still open.
    :rtype: tuple[datetime.datetime, datetime.datetime | None]
    """
    start = _as_utc(question.date)
    next_question = group.questions.filter(QuestionModel.date > question.date).order_by(QuestionModel.date.asc()).first()
    if next_question:
        return start, min(_as_utc(next_question.date), start + datetime.timedelta(hours=24))
    # Imported here to avoid a circular import (question.py imports from builder/sockets only).
    from question import does_exist_question_today
    if does_exist_question_today(group):
        return start, None
    return start, start + datetime.timedelta(hours=24)

def get_messages(group_id: int) -> tuple[dict, int]:
    """Return the chat messages of one "day" of the group.

    :param int group_id: The group whose messages to fetch.
    :param int | None question_id: The question whose day to fetch; defaults to the group's current question.
    """
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    question_id = request.args.get('question_id', type=int)

    if question_id is not None:
        question = group.questions.filter(QuestionModel.id == question_id).first()
        if not question:
            return {"success": False, "message": "Question not found"}, 404
    else:
        question = group.questions.order_by(QuestionModel.date.desc()).first()

    query = ChatMessageModel.query.filter_by(group_id=group_id)
    if question:
        start, end = get_question_window(group, question)
        query = query.filter(ChatMessageModel.timestamp >= start)
        if end:
            query = query.filter(ChatMessageModel.timestamp < end)
    messages: list[ChatMessageModel] = query.order_by(ChatMessageModel.timestamp.asc()).all()
    messages_data = [
        build_chat_message_response(message) for message in messages
    ]

    return {"success": True, "message": "Messages retrieved successfully", "content": messages_data}, 200

def send_message(group_id: int, request: Request) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    content = request.json.get('content')
    user_info = current_user.id or current_user.username

    if not content or not user_info:
        return {"success": False, "message": "Content and user_info are required"}, 400

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if user not in group.users:
        return {"success": False, "message": "User is not a member of the group"}, 403

    # Messages of a previous day can be read but not written to.
    question_id = request.json.get('question_id')
    if question_id is not None:
        current_question = group.questions.order_by(QuestionModel.date.desc()).first()
        if not current_question or current_question.id != question_id:
            return {"success": False, "message": "Cannot send messages to a previous day"}, 403

    message = ChatMessageModel(content=content, user_id=user.id, group_id=group_id)

    result = add_to_db(message)
    if result.get("error"):
        return result, 500

    response_data = build_chat_message_response(message)
    socketio.emit('new_message', response_data, to=str(group_id))

    return {"success": True, "message": "Message sent successfully", "content": response_data}, 201