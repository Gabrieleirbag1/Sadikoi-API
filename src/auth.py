import os
import uuid
import datetime
import secrets
import requests
from werkzeug.utils import secure_filename
from flask import Request, request, session, current_app
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from lite_logging.lite_logging import log
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from models import UserModel, UserSecurity, UserSecurity
from config import allowed_file
from db import add_to_db, delete_from_db, update_from_db
from builder import build_user_response
from email_sender import send_auth_code_email
from config import GOOGLE_CLIENT_ID

MAX_LOGIN_ATTEMPTS = 5
AUTH_CODE_TTL_MINUTES = 10
REAUTH_AFTER_DAYS = 60

def save_profile_picture(file, external=False) -> str | None:
    upload_folder = current_app.config['UPLOAD_FOLDER']
    
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder, exist_ok=True)

    if external and isinstance(file, str):
        try:
            response = requests.get(file)
            if response.status_code == 200:
                # Google picture URLs often lack a file extension, so we guess from headers
                content_type = response.headers.get('content-type', '')
                if content_type == 'image/png':
                    ext = '.png'
                elif content_type == 'image/webp':
                    ext = '.webp'
                elif content_type == 'image/gif':
                    ext = '.gif'
                else:
                    ext = '.jpg' # safe fallback for Google avatars (which are usually JPEGs)
                
                unique_filename = f"{uuid.uuid4().hex}{ext}"
                file_path = os.path.join(upload_folder, unique_filename)
                
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                    
                return unique_filename
        except Exception as e:
            log(f"Failed to download external image: {e}", level="ERROR")
            return None
            
        return None

    elif file and getattr(file, 'filename', None) and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        return unique_filename
        
    return None

def register_user(request: Request) -> tuple[dict, int]:
    data = request.json if request.is_json else request.form
    log("Creating user with data: " + str(data), level="DEBUG")
    email = data.get('email')
    username = data.get('username')
    password = data.get('password')
    confirm_password = data.get('confirm_password')
    device_id = data.get('device_id')
    device_name = data.get('device_name', 'Unknown device')
    language = data.get('language', 'en')

    if password != confirm_password:
        return {"success": False, "message": "Passwords do not match"}, 400
    
    profile_picture = None
    if 'profile_picture' in request.files:
        profile_picture = save_profile_picture(request.files['profile_picture'])
        
    login_val = data.get('login', False)
    login = str(login_val).lower() in ['true', '1', 'yes']

    result = create_user(email, username, password, profile_picture, language)
    if not result[0].get("success"):
        return result

    if login:
        if device_id:
            user: UserModel = result[0].get("content")
            auth_check = check_device_authorization(user, device_id, device_name, request)
            if auth_check is not None:
                return auth_check  # blocks login, returns "requires_verification"
            return login_user_with_session(user, remember=True)
        return {"success": True, "message": "User created successfully. Could not login in user because of no device id", "content": build_user_response(result[0].get("content"))}, 201
    else:
        result[0]["content"] = build_user_response(result[0].get("content"))
        return result

def create_user(email: str, username: str, password: str, profile_picture: str | None = None, language: str = 'en') -> tuple[dict, int]:
    if not email or not username or not password:
        return {"success": False, "message": "Email, username, and password are required"}, 400

    user = UserModel(email=email, username=username, password=generate_password_hash(password, method='pbkdf2:sha256'), profile_picture=profile_picture, language=language)

    result = add_to_db(user)
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User created successfully", "content": user}, 201

def update_user(request: Request) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    data = request.json if request.is_json else request.form
    user.email = data.get('email', user.email)
    user.username = data.get('username', user.username)
    confirm_password = data.get('confirm_password')
    user.language = data.get('language', user.language)
    if 'password' in data and data['password'] != confirm_password:
        return {"success": False, "message": "Passwords do not match"}, 400
    
    # Only update password if provided
    if 'password' in data:
        user.password = generate_password_hash(data['password'], method='pbkdf2:sha256')

    if 'profile_picture' in request.files:
        new_pic = save_profile_picture(request.files['profile_picture'])
        if new_pic:
            user.profile_picture = new_pic

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    return {"success": True, "message": "User updated successfully", "content": build_user_response(user)}, 200

def delete_user() -> tuple[dict, int]:
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    result = delete_from_db(user)
    if result.get("error"):
        return result, 500

    return {"success": True, "message": "User deleted successfully", "content": build_user_response(user)}, 200

def google_login_handler(request: Request) -> tuple[dict, int]:
    if not GOOGLE_CLIENT_ID:
        log("GOOGLE_CLIENT_ID not found in .google.secrets file.", level="ERROR")
        return {"success": False, "message": "Server configuration error."}, 500
                
    token = request.json.get('token')
    if not token:
        return {"success": False, "message": "Token is required"}, 400

    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)
        
        email = idinfo['email']
        username = idinfo.get('name', email.split('@')[0])
        google_picture = idinfo.get('picture')
        language = idinfo.get('locale', 'en')
        
        user = UserModel.query.filter_by(email=email).first()
        
        if not user:
            random_password = secrets.token_urlsafe(32)
            profile_picture = None
            if google_picture:
                profile_picture = save_profile_picture(google_picture, external=True)
            result = create_user(email, username, random_password, profile_picture, language)
            if not result[0].get("success"):
                return result
            user_to_login = result[0].get("content")
        else:
            if google_picture and not user.profile_picture:
                user.profile_picture = google_picture
                update_from_db()
            user_to_login = user
        
        login_result = login_user_with_session(user_to_login, remember=True)
        if not login_result[0].get("success"):
            return login_result
        return {"success": True, "message": "Login with Google successful", "content": login_result[0].get("content")}, 200

    except ValueError:
        # Invalid token
        log("Invalid Google token received.", level="ERROR")
        return {"success": False, "message": "Invalid token."}, 401

def login(request: Request) -> tuple[dict, int]:
    """Login the user."""
    username_or_email = request.json.get('username_or_email')
    password = request.json.get('password')
    remember = True if request.json.get('remember') else False
    device_id = request.json.get('device_id', "unknown-device")
    device_name = request.json.get('device_name', 'Unknown device')

    if not (username_or_email and password):
        return {'success': False, 'message': 'Please fill in all fields.'}, 400

    user: UserModel = UserModel.query.filter_by(email=username_or_email).first()
    if not user:
        user: UserModel = UserModel.query.filter_by(username=username_or_email).first()

    if not (user and check_password_hash(user.password, password)):
        return {'success': False, 'message': 'Invalid email or password.'}, 401

    if not device_id:
        return {'success': False, 'message': 'Unknown device.'}, 400

    # Check device authorization (new device or stale -> requires code)
    auth_check = check_device_authorization(user, device_id, device_name, request)
    if auth_check is not None:
        return auth_check  # blocks login, returns "requires_verification"

    return login_user_with_session(user, remember)
        
def login_user_with_session(user: UserModel, remember: bool = False) -> tuple[dict, int]:
    """Login the user and set the session to permanent if remember is True."""
    if remember:
        session.permanent = True
    result = login_user(user, remember=remember)
    if not result:
        log("Failed to log in user: " + str(user), level="ERROR")
        return {'success': False, 'message': 'Login failed due to server error.'}, 500
    return {'success': True, 'message': 'Login successful.', 'content': build_user_response(user)}, 200

def logout() -> tuple[dict, int]:
    device_id = request.json.get('device_id')
    forgot_device = request.json.get('forgot_device', False)
    if forgot_device and device_id:
        if current_user.is_authenticated:
            user_security = UserSecurity.query.filter_by(user_id=current_user.id, device_id=device_id).first()
            if user_security:
                user_security.authorized = False
                update_from_db()
                log(f"Logged out device_id: {device_id} for user: {current_user.id}", level="INFO")
            else:
                log("No security record found for device_id: " + str(device_id) + " and user: " + str(current_user.id), level="WARNING")
        else:
            return {"success": False, "message": "No user is currently logged in."}, 400
    logout_user()
    return {"success": True, "message": "Logout successful."}, 200
        
def get_user_object(user_info: str | int) -> UserModel | None:
    """Get the user object with the given user_info."""
    if isinstance(user_info, int) or user_info.isdigit():
        return UserModel.query.get(int(user_info))
    else:
        return UserModel.query.filter((UserModel.email == user_info) | (UserModel.username == user_info)).first()
        
def get_user() -> tuple[dict, int]:
    """Get the user with the given user_info."""
    user = get_user_object(current_user.id or current_user.username)
    if not user:
        return {'success': False, 'message': 'User not found'}, 404
    return {'success': True, 'message': 'User found', 'content': build_user_response(user)}, 200

def get_client_ip(request: Request) -> str:
    """Best-effort extraction of the real client IP, accounting for reverse proxies."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

def get_or_create_device(user: UserModel, device_id: str, device_name: str, request: Request) -> tuple[UserSecurity, bool]:
    """Get the device record for this user, creating it if it doesn't exist.

    :return: tuple of (UserSecurity, created) where created is True if this is a brand new device.
    """
    device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
    if device:
        return device, False

    device = UserSecurity(
        user_id=user.id,
        device_id=device_id,
        device_name=device_name or 'Unknown device',
        ip_address=get_client_ip(request),
        authorized=False,
    )
    result = add_to_db(device)
    if result.get("error"):
        log(f"Failed to create device record: {result}", level="ERROR")
    return device, True

def send_auth_code(user: UserModel, device: UserSecurity) -> tuple[dict, int]:
    """Generate a new auth code for the device and email it to the user."""
    code = device.generate_auth_code(ttl_minutes=AUTH_CODE_TTL_MINUTES)
    result = update_from_db()
    if result.get("error"):
        return {"success": False, "message": "Could not generate authorization code"}, 500

    try:
        send_auth_code_email(user, device, code, language=user.language)
    except Exception as e:
        log(f"Failed to send auth code email: {e}", level="ERROR")
        return {"success": False, "message": "Could not send authorization email"}, 500

    return {"success": True, "message": "Authorization code sent to your email"}, 200

def verify_device(request: Request) -> tuple[dict, int]:
    """Verify the auth code submitted for a given device, authorizing it on success."""
    user_info = request.json.get('user_info')
    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    device_id = request.json.get('device_id')
    submitted_code = request.json.get('code')

    if not device_id or not submitted_code:
        return {"success": False, "message": "device_id and code are required"}, 400

    device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
    if not device:
        return {"success": False, "message": "Device not found"}, 404
    
    if device.authorized:
        return {"success": True, "message": "Device already authorized"}, 200

    if device.login_attempts >= MAX_LOGIN_ATTEMPTS:
        return {"success": False, "message": "Too many failed attempts. Request a new code."}, 429

    if not device.is_code_valid(submitted_code):
        device.login_attempts += 1
        update_from_db()
        remaining = MAX_LOGIN_ATTEMPTS - device.login_attempts
        return {"success": False, "message": f"Invalid or expired code. {max(remaining, 0)} attempts remaining."}, 401

    device.authorized = True
    device.last_login = datetime.datetime.now(datetime.timezone.utc)
    device.clear_auth_code()
    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    log(f"Device {device.device_name} (ID: {device.device_id}) authorized for user {user.username}", level="INFO")
    
    return {"success": True, "message": "Device authorized successfully"}, 200

def check_device_authorization(user: UserModel, device_id: str, device_name: str, request: Request) -> tuple[dict, int] | None:
    """Call this during login. Returns None if device is authorized and fresh (login can proceed),
    otherwise returns the (response, status_code) the caller should return immediately.
    """
    device, created = get_or_create_device(user, device_id, device_name, request)

    if device.needs_reauthorization(max_days=REAUTH_AFTER_DAYS):
        result, status = send_auth_code(user, device)
        result["requires_verification"] = True
        result["device_id"] = device.device_id
        return result, 401 if not result.get("success") else 403

    # Device is authorized and recent: update login metadata and let login proceed
    device.last_login = datetime.datetime.now(datetime.timezone.utc)
    device.ip_address = get_client_ip(request)
    update_from_db()
    return None

def list_devices() -> tuple[dict, int]:
    """List all known devices for the current user."""
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    devices = UserSecurity.query.filter_by(user_id=user.id).order_by(UserSecurity.last_login.desc()).all()
    content = [
        {
            "device_id": d.device_id,
            "device_name": d.device_name,
            "ip_address": d.ip_address,
            "first_seen": d.first_seen.isoformat() if d.first_seen else None,
            "last_login": d.last_login.isoformat() if d.last_login else None,
            "authorized": d.authorized,
        }
        for d in devices
    ]
    return {"success": True, "message": "Devices retrieved", "content": content}, 200

def revoke_device(request: Request) -> tuple[dict, int]:
    """Revoke authorization for a device (or delete it), e.g. user clicks 'this wasn't me'."""
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    device_id = request.json.get('device_id')
    if not device_id:
        return {"success": False, "message": "device_id is required"}, 400

    device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
    if not device:
        return {"success": False, "message": "Device not found"}, 404

    result = delete_from_db(device)
    if result.get("error"):
        return result, 500

    return {"success": True, "message": "Device revoked successfully"}, 200