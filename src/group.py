import datetime
import secrets

from flask_login import current_user

from models import GroupInvitationModel, GroupModel, UserModel, GroupUser
from flask import Request, request
from db import add_to_db, delete_from_db, update_from_db
from auth import get_user_object
from builder import build_group_response, build_groups_response

def create_group(request: Request) -> tuple[dict, int]:
    user_info = current_user.id or current_user.username
    if not user_info:
        return {"success": False, "message": "User info is required to create a group"}, 400
    name = request.json.get('name')
    description = request.json.get('description')

    if not name:
        return {"success": False, "message": "Name is required"}, 400

    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    group = GroupModel(name=name, description=description)

    result = add_to_db(group)
    if result.get("error"):
        return result, 500
    
    group_user = GroupUser(user_id=user.id, group_id=group.id, role='admin')
    add_to_db(group_user)
    
    return {"success": True, "message": "Group created successfully", "content": build_group_response(group)}, 201

def get_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    return {"success": True, "message": "Group retrieved successfully", "content": build_group_response(group)}, 200

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
    
    return {"success": True, "message": "Group updated successfully", "content": build_group_response(group)}, 200

def delete_group(group_id: int) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    result = delete_from_db(group)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "Group deleted successfully", "content": build_group_response(group)}, 200

def get_user_groups(user_info: str) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    groups = build_groups_response(user.groups)
    return {"success": True, "message": "Groups retrieved successfully", "content": groups}, 200

def add_user_to_group(group_id: int, user_info: str) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    if user in group.users:
        return {"success": False, "message": "User is already in the group"}, 400

    group.users.append(user)

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User added to group successfully", "content": build_group_response(group)}, 200

def remove_user_from_group(group_id: int, user_info: str) -> tuple[dict, int]:
    group = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404

    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    group_user = GroupUser.query.filter_by(user_id=user.id, group_id=group_id).first()
    if not group_user:
        return {"success": False, "message": "User is not in the group"}, 400

    if group_user.role == 'admin':
        # Find another user to make admin
        other_user = GroupUser.query.filter_by(group_id=group_id).filter(GroupUser.user_id != user.id).first()
        if other_user:
            other_user.role = 'admin'
            update_from_db()
        else:
            return {"success": False, "message": "Cannot remove the only admin from the group"}, 400

    result = delete_from_db(group_user)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User removed from group successfully", "content": build_group_response(group)}, 200

def create_invitation(group: GroupModel) -> tuple[dict, int]:
    expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    token = secrets.token_urlsafe(16)
    
    invitation = GroupInvitationModel(group_id=group.id, expiration_date=expiration_date, token=token)
    result = add_to_db(invitation)
    if result.get("error"):
        return result, 500
    return {"success": True, "message": "Invitation created successfully", "content": invitation.token}, 201

def answer_invitation(group_id: int, token: str) -> tuple[dict, int]:
    user_info = current_user.id or current_user.username
    if not user_info:
        return {"success": False, "message": "User info is required to answer an invitation"}, 400
    
    if not token:
        return {"success": False, "message": "Token is required"}, 400

    invitation: GroupInvitationModel = GroupInvitationModel.query.filter_by(group_id=group_id, token=token).first()
    if not invitation:
        return {"success": False, "message": "Invitation not found"}, 404

    if invitation.expiration_date < datetime.datetime.now(datetime.timezone.utc):
        return {"success": False, "message": "Invitation has expired"}, 400

    return add_user_to_group(group_id, user_info)
    

def get_group_invitation(group_id: int) -> tuple[dict, int]:
    group: GroupModel = GroupModel.query.get(group_id)
    if not group:
        return {"success": False, "message": "Group not found"}, 404
    
    user_info = current_user.id or current_user.username
    if not user_info:
        return {"success": False, "message": "User info is required to create a group"}, 400
    
    user: UserModel | None = get_user_object(user_info)
    if user not in group.users:
        return {"success": False, "message": "User is not a member of the group"}, 403

    invitation: GroupInvitationModel = GroupInvitationModel.query.filter_by(group_id=group_id).first()
    if not invitation:
        return {"success": False, "message": "Invitation not found"}, 404