from models import ChatMessageModel, GroupModel, UserModel
from flask import Request
from db import add_to_db

def get_messages(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    messages = ChatMessageModel.query.filter_by(group_id=group_id).order_by(ChatMessageModel.timestamp.asc()).all()
    messages_data = [
        {
            "id": message.id,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
            "user_id": message.user_id
        }
        for message in messages
    ]

    return {"messages": messages_data}, 200

def send_message(group_id: int, request: Request) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    content = request.json.get('content')
    user_id = request.json.get('user_id')

    if not content or not user_id:
        return {"message": "Content and user_id are required"}, 400

    user = UserModel.query.get(user_id)
    if not user:
        return {"message": "User not found"}, 404

    message = ChatMessageModel(content=content, user_id=user_id, group_id=group_id)

    result = add_to_db(message)
    if result.get("error"):
        return result, 500
    
    return {"message": "Message sent successfully"}, 201