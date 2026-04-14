from models import GroupModel, UserModel
from flask import Request, request
from db import add_to_db, delete_from_db, update_from_db

def create_group(request: Request) -> tuple[dict, int]:
    username = request.json.get('username')
    if not username:
        return {"message": "User is required to create a group"}, 400
    name = request.json.get('name')
    description = request.json.get('description')

    if not name:
        return {"message": "Name is required"}, 400
    
    user = UserModel.query.filter_by(username=username).first()
    if not user:
        return {"message": "User not found"}, 404
    
    group = GroupModel(name=name, description=description, users=[user])

    result = add_to_db(group)
    if result.get("error"):
        return result, 500
    return {"message": "Group created successfully"}, 201

def update_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    data = request.json
    group.name = data.get('name', group.name)
    group.description = data.get('description', group.description)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"message": "Group updated successfully"}, 200

def delete_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    result = delete_from_db(group)
    if result.get("error"):
        return result, 500
    
    return {"message": "Group deleted successfully"}, 200

def add_user_to_group(group_id: int, user_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    user = UserModel.query.get(user_id)
    if not user:
        return {"message": "User not found"}, 404

    group.users.append(user)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"message": "User added to group successfully"}, 200

def remove_user_from_group(group_id: int, user_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"message": "Group not found"}, 404

    user = UserModel.query.get(user_id)
    if not user:
        return {"message": "User not found"}, 404

    group.users.remove(user)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"message": "User removed from group successfully"}, 200