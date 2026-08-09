import datetime

from models import ChatMessageModel, GroupModel, ItemModel, QuestionModel, UserModel

def build_user_response(user: UserModel) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "profile_picture": user.profile_picture,
        "date_created": user.date_created,
        "language": user.language
    }

def build_group_response(group: GroupModel) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "users": [build_user_response(user) for user in group.users],
        "date_created": group.date_created,
        "daily_reset_timestamp": group.daily_reset_timestamp.strftime("%H:%M")
    }

def build_groups_response(groups: list[GroupModel]) -> list[dict]:
    return [build_group_response(group) for group in groups]

def build_chat_message_response(message: ChatMessageModel) -> dict:
    return {
        "id": message.id,
        "content": message.content,
        "timestamp": message.timestamp.isoformat(),
        "sender": build_user_response(message.user)
    }

def build_question_response(question: QuestionModel, votes: dict = None) -> dict:
    return {
        "id": question.id,
        "question_id": question.question_id,
        "content": question.content,
        "theme": question.theme,
        "enableSelfVote": question.enableSelfVote,
        "enableMultipleVoting": question.enableMultipleVoting,
        "voteNumberLimit": question.voteNumberLimit,
        "canWrite": question.canWrite,
        "date": question.date.isoformat(),
        "item_name": question.item_name,
        "votes": votes
    }

def build_question_model(question_data: dict, group: GroupModel, language: str) -> QuestionModel:
    now = datetime.datetime.now(datetime.timezone.utc)
    reset_time = datetime.datetime.combine(now.date(), group.daily_reset_timestamp, tzinfo=datetime.timezone.utc)
    date = reset_time if now >= reset_time else reset_time - datetime.timedelta(days=1)
    return QuestionModel(
        question_id=question_data['question_id'],
        content=question_data['content'][language],
        theme=question_data['theme'][language],
        enableSelfVote=question_data['enableSelfVote'],
        enableMultipleVoting=question_data['enableMultipleVoting'],
        voteNumberLimit=question_data['voteNumberLimit'],
        canWrite=question_data['canWrite'],
        item_name=question_data['item_name']["id"],
        date=date,
        group=group
    )

def build_item_model(most_voted_user: dict, last_question: QuestionModel) -> ItemModel:
    return ItemModel(
        user_id=most_voted_user["id"],
        group_id=last_question.group_id,
        item_name=last_question.item_name,
        acquired_at=last_question.date
    )