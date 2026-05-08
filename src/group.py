from models import GroupModel, UserModel
from flask import Request, request
from db import add_to_db, delete_from_db, update_from_db
from auth import get_user_object

def create_group(request: Request) -> tuple[dict, int]:
    user_info = request.json.get('user_info')
    if not user_info:
        return {"success": False, "message": "User info is required to create a group"}, 400
    name = request.json.get('name')
    description = request.json.get('description')

    if not name:
        return {"success": False, "message": "Name is required"}, 400

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    group = GroupModel(name=name, description=description, users=[user])

    result = add_to_db(group)
    if result.get("error"):
        return result, 500
    return {"success": True, "message": "Group created successfully", "content": {"id": group.id, "name": group.name, "description": group.description, "users": [user.username for user in group.users], "date_created": group.date_created}}, 201

def update_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    data = request.json
    group.name = data.get('name', group.name)
    group.description = data.get('description', group.description)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Group updated successfully", "content": {"id": group.id, "name": group.name, "description": group.description}}, 200

def delete_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    result = delete_from_db(group)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Group deleted successfully"}, 200

def get_user_groups(user_info: str) -> tuple[dict, int]:
    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    groups = [{"id": group.id, "name": group.name, "description": group.description, "users": [user.username for user in group.users], "date_created": group.date_created} for group in user.groups]
    return {"success": True, "message": "Groups retrieved successfully", "content": groups}, 200

def add_user_to_group(group_id: int, user_info: str) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    group.users.append(user)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User added to group successfully"}, 200

def remove_user_from_group(group_id: int, user_info: str) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    group.users.remove(user)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User removed from group successfully"}, 200