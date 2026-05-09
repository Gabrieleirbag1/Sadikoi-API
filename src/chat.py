from models import ChatMessageModel, GroupModel, UserModel
from flask import Request
from db import add_to_db
from auth import get_user_object

def get_messages(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    messages: list[ChatMessageModel] = ChatMessageModel.query.filter_by(group_id=group_id).order_by(ChatMessageModel.timestamp.asc()).all()
    messages_data = [
        {
            "id": message.id,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
            "sender": {'id': message.user.id, 'email': message.user.email, 'username': message.user.username, 'date_created': message.user.date_created}
            
        }
        for message in messages
    ]

    return {"success": True, "message": "Messages retrieved successfully", "content": messages_data}, 200

def send_message(group_id: int, request: Request) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    content = request.json.get('content')
    user_info = request.json.get('user_info')

    if not content or not user_info:
        return {"success": False, "message": "Content and user_info are required"}, 400

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if user not in group.users:
        return {"success": False, "message": "User is not a member of the group"}, 403

    message = ChatMessageModel(content=content, user_id=user.id, group_id=group_id)

    result = add_to_db(message)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Message sent successfully", "content": {'id': message.id, 'content': message.content, 'timestamp': message.timestamp.isoformat(), 'sender': {'id': message.user.id, 'email': message.user.email, 'username': message.user.username, 'date_created': message.user.date_created}}}, 201