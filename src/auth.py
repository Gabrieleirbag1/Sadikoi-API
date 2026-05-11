from flask import Request, request, session
from flask_login import login_user
from werkzeug.security import check_password_hash, generate_password_hash
from models import UserModel
from lite_logging.lite_logging import log

from db import add_to_db, delete_from_db, update_from_db
from builder import build_user_response

def create_user(request: Request) -> tuple[dict, int]:
    log("Creating user with data: " + str(request.json), level="DEBUG")
    email = request.json.get('email')
    username = request.json.get('username')
    password = request.json.get('password')

    if not email or not username or not password:
        return {"success": False, "message": "Email, username, and password are required"}, 400

    user = UserModel(email=email, username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))

    result = add_to_db(user)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User created successfully", "content": build_user_response(user)}, 201

def update_user(user_info: str | int, request: Request) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    data = request.json
    user.email = data.get('email', user.email)
    user.username = data.get('username', user.username)
    
    # Only update password if provided
    if 'password' in data:
        user.password = generate_password_hash(data['password'], method='pbkdf2:sha256')

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User updated successfully", "content": build_user_response(user)}, 200

def delete_user(user_info: str | int) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    result = delete_from_db(user)
    if result.get("error"):
        return result, 500

    return {"success": True, "message": "User deleted successfully", "content": build_user_response(user)}, 200


def login(request: Request) -> tuple[dict, int]:
    """Login the user.
    
    :param Request request: The request object.
    
    :return: A tuple with the status of the login and the response.
    :rtype: tuple"""
    username_or_email = request.json.get('username_or_email')
    password = request.json.get('password')
    remember = True if request.json.get('remember') else False
    log(f"Remember: {remember, username_or_email, password}", level="DEBUG")

    if not (username_or_email and password):
        return {'success': False, 'message': 'Please fill in all fields.'}, 400
    else:
        user: UserModel = UserModel.query.filter_by(email=username_or_email).first()
        if not user:
            user: UserModel = UserModel.query.filter_by(username=username_or_email).first()
        if user and check_password_hash(user.password, password):
            # Make session permanent for remembered users
            if remember:
                session.permanent = True
            login_user(user, remember=remember)
            return {'success': True, 'message': 'Login successful.', 'content': build_user_response(user)}, 200
        else:
            return {'success': False, 'message': 'Invalid email or password.'}, 401
        
def get_user_object(user_info: str | int) -> UserModel | None:
    """Get the user object with the given user_info."""
    if isinstance(user_info, int) or user_info.isdigit():
        return UserModel.query.get(int(user_info))
    else:
        return UserModel.query.filter((UserModel.email == user_info) | (UserModel.username == user_info)).first()
        
def get_user(user_info: str | int) -> tuple[dict, int]:
    """Get the user with the given user_info."""
    user = get_user_object(user_info)
    if not user:
        return {'success': False, 'message': 'User not found'}, 404
    return {'success': True, 'message': 'User found', 'content': build_user_response(user)}, 200