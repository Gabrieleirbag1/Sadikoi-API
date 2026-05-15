from models import ChatMessageModel, GroupModel, QuestionModel, UserModel

def build_user_response(user: UserModel) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "date_created": user.date_created
    }

def build_group_response(group: GroupModel) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "users": [build_user_response(user) for user in group.users],
        "date_created": group.date_created
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

def build_question_data(question: QuestionModel, has_voted: bool = False) -> dict:
    return {
        "id": question.id,
        "question_id": question.question_id,
        "content": question.content,
        "theme": question.theme,
        "enableSelfVote": question.enableSelfVote,
        "enableMultipleVoting": question.enableMultipleVoting,
        "voteNumberLimit": question.voteNumberLimit,
        "canWrite": question.canWrite,
        "item": question.item,
        "hasVoted": has_voted
    }