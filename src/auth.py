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

from models import PasswordResetToken, UserModel, UserSecurity, ReportUserModel
from config import allowed_file
from notifications import remove_device_tokens
from db import db, add_to_db, delete_from_db, update_from_db
from builder import build_user_response
from email_sender import send_auth_code_email, send_password_reset_email, RESET_TOKEN_TTL_MINUTES
from config import GOOGLE_CLIENT_BROWSER_ID, GOOGLE_CLIENT_MOBILE_ID, FRONTEND_URL, TURNSTILE_SECRET_KEY

MAX_LOGIN_ATTEMPTS = 5
AUTH_CODE_TTL_MINUTES = 10
REAUTH_AFTER_DAYS = 60
RESET_REQUEST_COOLDOWN_SECONDS = 60
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_TIMEOUT_SECONDS = 5
FORGOT_PASSWORD_MESSAGE = "If an account exists for this email, a reset link has been sent."

IMAGE_SIGNATURES = (b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a')

def has_image_signature(stream) -> bool:
    """Check the file's magic bytes so a renamed non-image is not stored as a profile picture."""
    head = stream.read(8)
    stream.seek(0)
    return head.startswith(IMAGE_SIGNATURES)

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

    elif file and getattr(file, 'filename', None) and allowed_file(file.filename) and has_image_signature(file.stream):
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        return unique_filename
        
    return None

def verify_captcha(token: str | None, request: Request) -> tuple[dict, int] | None:
    """Verify a Cloudflare Turnstile token. Returns None when valid, else the (response, status) to return.

    Fails closed: if the secret is missing or Cloudflare is unreachable, the request is refused.
    """
    if not TURNSTILE_SECRET_KEY:
        return {"success": False, "message": "Server configuration error."}, 500
    if not token:
        return {"success": False, "message": "Captcha is required."}, 400

    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": get_client_ip(request)},
            timeout=TURNSTILE_TIMEOUT_SECONDS,
        )
        result = response.json()
    except (requests.RequestException, ValueError) as e:
        log(f"Captcha verification failed: {e}", level="ERROR")
        return {"success": False, "message": "Could not verify captcha."}, 503

    if not result.get("success"):
        log(f"Captcha rejected: {result.get('error-codes')}", level="WARNING")
        return {"success": False, "message": "Captcha verification failed."}, 400
    return None

def register_user(request: Request) -> tuple[dict, int]:
    data = request.json if request.is_json else request.form
    captcha_error = verify_captcha(data.get('captcha_token'), request)
    if captcha_error is not None:
        return captcha_error
    log("Creating user", level="DEBUG")
    email = data.get('email')
    username = data.get('username')
    password = data.get('password')
    confirm_password = data.get('confirm_password')
    device_id = data.get('device_id')
    device_name = data.get('device_name', 'Unknown device')
    language = data.get('language', 'en').split("-")[0]  # Handle cases like "en-US" or "fr-FR"

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
            return login_user_with_session(user, remember=True, device_id=device_id)
        return {"success": True, "message": "User created successfully. Could not login in user because of no device id", "content": build_user_response(result[0].get("content"))}, 201
    else:
        result[0]["content"] = build_user_response(result[0].get("content"))
        return result

def create_user(email: str, username: str, password: str, profile_picture: str | None = None, language: str = 'en') -> tuple[dict, int]:
    if not email or not username or not password:
        return {"success": False, "message": "Email, username, and password are required"}, 400

    # Unique constraints also cover soft-deleted accounts, so they are checked without the `deleted` filter.
    if UserModel.query.filter_by(email=email).first():
        return {"success": False, "message": "Email already in use"}, 409
    if UserModel.query.filter_by(username=username).first():
        return {"success": False, "message": "Username already in use"}, 409

    user = UserModel(email=email, username=username, password=generate_password_hash(password, method='pbkdf2:sha256'), profile_picture=profile_picture, language=language)

    result = add_to_db(user)
    if result.get("error"):
        return result, 500
    
    log(f"User {user.id} ({user.username}) created", level="INFO")
    return {"success": True, "message": "User created successfully", "content": user}, 201

def make_unique_username(base: str) -> str:
    """Return `base`, or `base` + a short random suffix when that username is already taken (max 40 chars)."""
    base = base[:40]
    candidate = base
    while UserModel.query.filter_by(username=candidate).first():
        candidate = f"{base[:33]}_{secrets.token_hex(3)}"
    return candidate

def update_user(request: Request) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404
    
    update_password = False

    data = request.json if request.is_json else request.form
    user.email = data.get('email', user.email)
    user.username = data.get('username', user.username)
    confirm_password = data.get('confirm_password')
    user.language = data.get('language', user.language).split("-")[0]  # Handle cases like "en-US" or "fr-FR"
    if 'password' in data and data['password'] != confirm_password:
        return {"success": False, "message": "Passwords do not match"}, 400
    
    # Only update password if provided
    if 'password' in data:
        user.password = generate_password_hash(data['password'], method='pbkdf2:sha256')
        update_password = True

    if 'profile_picture' in request.files:
        new_pic = save_profile_picture(request.files['profile_picture'])
        if new_pic:
            user.profile_picture = new_pic

    result = update_from_db()
    if result.get("error"):
        return result, 500
    
    if update_password:
        result, status = logout_sessions(user)
        if not result.get("success"):
            log(f"Could not invalidate sessions: {result}", level="ERROR")
        
        result, status = prohibit_devices(user)  # Déauthorise tous les devices
        if not status == 200:
            log(f"Failed to prohibit devices: {result}", level="ERROR")

    log(f"User {user.id} ({user.username}) updated their profile" + (" and password" if update_password else ""), level="INFO")
    return {"success": True, "message": "User updated successfully", "content": build_user_response(user)}, 200

def delete_user(user_info: str) -> tuple[dict, int]:
    user: UserModel | None = get_user_object(current_user.id)
    if not user:
        return {"success": False, "message": "User not found"}, 404

    user_to_delete: UserModel | None = get_user_object(user_info)
    if not user_to_delete:
        return {"success": False, "message": "User to delete not found"}, 404

    if user != user_to_delete:
        return {"success": False, "message": "You can only delete your own account"}, 403

    user_to_delete.deleted = True  # Mark the user as deleted instead of removing from DB

    result = update_from_db()
    if result.get("error"):
        return result, 500

    log(f"User {user.id} ({user.username}) deleted their account", level="INFO")

    return {"success": True, "message": "User deleted successfully", "content": build_user_response(user)}, 200

def google_login_handler(request: Request) -> tuple[dict, int]:
    if not GOOGLE_CLIENT_BROWSER_ID:
        log("GOOGLE_CLIENT_BROWSER_ID not found in .google.secrets file.", level="ERROR")
        return {"success": False, "message": "Server configuration error."}, 500
                
    token = request.json.get('token')
    if not token:
        return {"success": False, "message": "Token is required"}, 400

    try:
        # The mobile app's native login normally issues tokens for the web client ID too;
        # the mobile client ID is accepted as well in case a token is issued for it.
        audiences = [client_id for client_id in (GOOGLE_CLIENT_BROWSER_ID, GOOGLE_CLIENT_MOBILE_ID) if client_id]
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), audiences)
        
        email = idinfo['email']
        username = idinfo.get('name', email.split('@')[0])
        google_picture = idinfo.get('picture')
        language = idinfo.get('locale', 'en').split("-")[0]  # Handle cases like "en-US" or "fr-FR"
        
        user = get_user_object(email)
        
        if not user:
            random_password = secrets.token_urlsafe(32)
            username = make_unique_username(username)
            profile_picture = None
            if google_picture:
                profile_picture = save_profile_picture(google_picture, external=True)
            result = create_user(email, username, random_password, profile_picture, language)
            if not result[0].get("success"):
                return result
            user_to_login = result[0].get("content")
        else:
            # if google_picture and not user.profile_picture:
            #     profile_picture = save_profile_picture(google_picture, external=True)
            #     user.profile_picture = profile_picture
            #     update_from_db()
            user_to_login = user

        device_id = request.json.get('device_id')
        device_name = request.json.get('device_name', 'Unknown device')
        device, created = get_or_create_device(user_to_login, device_id, device_name, request, authorized=True)
        if not device and not created:
            return {"success": False, "message": "Could not retrieve or create device record"}, 500
        result = update_device(device)
        if result.get("error"):
            return result, 500

        login_result = login_user_with_session(user_to_login, remember=True, device_id=device_id)
        if not login_result[0].get("success"):
            return login_result
        log(f"User {user_to_login.id} logged in with Google", level="INFO")
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
    device_id = request.json.get('device_id')
    device_name = request.json.get('device_name', 'Unknown device')

    if not (username_or_email and password):
        return {'success': False, 'message': 'Please fill in all fields.'}, 400

    # The captcha is single-use, so the re-login right after the device code was verified
    # carries none: it is only accepted for a device that is already authorized.
    if not is_known_authorized_device(username_or_email, device_id):
        captcha_error = verify_captcha(request.json.get('captcha_token'), request)
        if captcha_error is not None:
            return captcha_error

    user: UserModel = get_user_object(username_or_email)
    if not (user and check_password_hash(user.password, password)):
        log(f"Failed login attempt for {username_or_email!r}", level="WARNING")
        return {'success': False, 'message': 'Invalid username / email or password.'}, 401

    if not device_id:
        return {'success': False, 'message': 'Unknown device.'}, 400

    # Check device authorization (new device or stale -> requires code)
    auth_check = check_device_authorization(user, device_id, device_name, request)
    if auth_check is not None:
        return auth_check  # blocks login, returns "requires_verification"

    return login_user_with_session(user, remember, device_id=device_id)
        
def is_known_authorized_device(user_info: str, device_id: str | None) -> bool:
    """True if device_id is an already-authorized device of this user (device ids are unguessable)."""
    if not device_id:
        return False
    user = get_user_object(user_info)
    if not user:
        return False
    device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
    return bool(device and device.authorized)

def login_user_with_session(user: UserModel, remember: bool = False, device_id: str | None = None) -> tuple[dict, int]:
    """Login the user and set the session to permanent if remember is True."""
    if remember:
        session.permanent = True
    
    result = login_user(user, remember=remember)
    if not result:
        log("Failed to log in user: " + str(user), level="ERROR")
        return {'success': False, 'message': 'Login failed due to server error.'}, 500
    
    session['session_version'] = user.session_version
    if device_id:
        session['device_id'] = device_id
    
    log(f"User {user.id} ({user.username}) logged in on device {device_id}", level="INFO")
    return {'success': True, 'message': 'Login successful.', 'content': build_user_response(user)}, 200

def logout() -> tuple[dict, int]:
    device_id = request.json.get('device_id')
    forget_device = request.json.get('forget_device', False)
    if forget_device:
        if device_id:
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
        else:
            log(f"Logging out user: {current_user.id} without forgetting device because no device ID was provided.", level="WARNING")
    if current_user.is_authenticated:
        # This phone stops receiving the user's push notifications.
        remove_device_tokens(current_user.id, device_id)
        update_from_db()
        log(f"User {current_user.id} logged out from device {device_id}", level="INFO")
    logout_user()
    return {"success": True, "message": "Logout successful."}, 200

def set_session_version(user: UserModel) -> tuple[dict, int]:
    """Increment the session version for a user, invalidating all existing sessions."""
    user.session_version += 1
    result = update_from_db()
    if result.get("error"):
        return result, 500
    log(f"Session version incremented for user {user.username} to {user.session_version}", level="INFO")
    return {"success": True, "message": "All sessions invalidated"}, 200

def logout_sessions(user: UserModel = None) -> tuple[dict, int]:
    """Log out all sessions for the given user."""
    if user is None:
        user = get_user_object(current_user.id)
        if not user:
            return {"success": False, "message": "User not found"}, 404
    return set_session_version(user)
        
def get_user_object(user_info: str | int) -> UserModel | None:
    """Get the user object with the given user_info (an id, a username or an email)."""
    if user_info is None or not isinstance(user_info, (int, str)) or user_info == "":
        return None
    if isinstance(user_info, int) or user_info.isdigit():
        user = UserModel.query.get(int(user_info))
    else:
        user = UserModel.query.filter((UserModel.email == user_info) | (UserModel.username == user_info)).first()
    if user and user.deleted:
        return None
    return user

def get_user() -> tuple[dict, int]:
    """Get the user with the given user_info."""
    user = get_user_object(current_user.id or current_user.username)
    if not user:
        return {'success': False, 'message': 'User not found'}, 404
    device_id = request.json.get('device_id')
    if device_id:
        device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
        if device:
            if not device.authorized:
                return {'success': False, 'message': 'Device not authorized.'}, 403
            session['device_id'] = device_id
            device.last_login = datetime.datetime.now(datetime.timezone.utc)
            update_from_db()
        else:
            return {'success': False, 'message': 'Device not found'}, 404
    else:
        return {'success': False, 'message': 'Device ID not provided'}, 400
    return {'success': True, 'message': 'User found', 'content': build_user_response(user)}, 200

def get_client_ip(request: Request) -> str:
    """Client IP. Behind the reverse proxy, ProxyFix (app.py) has already put the real IP in remote_addr;
    never read X-Forwarded-For here, it is client-controlled."""
    return request.remote_addr or 'unknown'

def get_or_create_device(user: UserModel, device_id: str, device_name: str, request: Request, authorized: bool = False) -> tuple[UserSecurity, bool]:
    """Get the device record for this user, creating it if it doesn't exist.

    :return: tuple of (UserSecurity, created) where created is True if this is a brand new device.
    """
    device = UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
    if device:
        return device, False

    device, created = add_device(user, device_id, device_name, request, authorized=authorized)
    return device, created

def add_device(user: UserModel, device_id: str, device_name: str, request: Request, authorized: bool = False) -> tuple[UserSecurity, bool]:
    device = UserSecurity(
        user_id=user.id,
        device_id=device_id,
        device_name=device_name or 'Unknown device',
        ip_address=get_client_ip(request),
        authorized=authorized,
    )
    result = add_to_db(device)
    if result.get("error"):
        log(f"Failed to add device: {result}", level="ERROR")
        return None, False
    return device, True

def update_device(device: UserSecurity) -> tuple[dict, int]:
    device.authorized = True
    device.last_login = datetime.datetime.now(datetime.timezone.utc)
    device.clear_auth_code()
    result = update_from_db()
    return result

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

    log(f"Authorization code sent to user {user.id} for device {device.device_id}", level="INFO")

    return {"success": True, "message": "Authorization code sent to your email"}, 203

def verify_device(request: Request) -> tuple[dict, int]:
    """Verify the auth code submitted for a given device, authorizing it on success."""
    data = request.json or {}
    user_info = data.get('user_info')
    device_id = data.get('device_id')
    submitted_code = data.get('code')

    if not user_info or not device_id or not submitted_code:
        return {"success": False, "message": "user_info, device_id and code are required"}, 400

    user = get_user_object(user_info)
    if not user:
        return {"success": False, "message": "User not found"}, 404

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

    result = update_device(device)
    if result.get("error"):
        return result, 500
    
    log(f"Device {device.device_name} (ID: {device.device_id}) authorized for user {user.username}", level="INFO")
    
    return {"success": True, "message": "Device authorized successfully"}, 200

def check_device_authorization(user: UserModel, device_id: str, device_name: str, request: Request) -> tuple[dict, int] | None:
    """Call this during login. Returns None if device is authorized and fresh (login can proceed),
    otherwise returns the (response, status_code) the caller should return immediately.
    """
    device, created = get_or_create_device(user, device_id, device_name, request)

    if not device and not created:
        return {"success": False, "message": "Could not retrieve or create device record"}, 500

    if user.skip_device_verification and device.needs_reauthorization(max_days=REAUTH_AFTER_DAYS):
        # Store reviewers can't receive the emailed code: the password (and captcha) are enough.
        device.ip_address = get_client_ip(request)
        update_device(device)
        log(f"Device {device.device_id} authorized without code for review account {user.id}", level="WARNING")
        return None

    if device.needs_reauthorization(max_days=REAUTH_AFTER_DAYS):
        result, status = send_auth_code(user, device)
        result["requires_verification"] = True
        result["device_id"] = device.device_id
        return result, status

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

    if session.get('device_id') == device_id:
        logout_user()
        session.clear()

    log(f"User {user.id} revoked device {device_id}", level="INFO")

    return {"success": True, "message": "Device revoked successfully"}, 200

def prohibit_devices(user: UserModel) -> tuple[dict, int]:
    """Mark all devices for this user as unauthorized without deleting them."""
    devices = UserSecurity.query.filter_by(user_id=user.id).all()
    if not devices:
        return {"success": False, "message": "No devices found for this user"}, 404

    for device in devices:
        device.authorized = False
    result = update_from_db()
    if result.get("error"):
        return result, 500

    log(f"All {len(devices)} device(s) of user {user.id} marked as unauthorized", level="INFO")

    return {"success": True, "message": "All devices marked as unauthorized"}, 200

def forgot_password(request: Request) -> tuple[dict, int]:
    """Email a single-use password reset link. Always answers 200 so accounts can't be enumerated."""
    captcha_error = verify_captcha((request.json or {}).get('captcha_token'), request)
    if captcha_error is not None:
        return captcha_error

    email = (request.json or {}).get('email')
    if not email:
        return {"success": False, "message": "Email is required"}, 400

    ok_response = {"success": True, "message": FORGOT_PASSWORD_MESSAGE}, 200

    user = get_user_object(email)
    if not user or user.deleted:
        return ok_response

    now = datetime.datetime.now(datetime.timezone.utc)
    pending = PasswordResetToken.query.filter_by(user_id=user.id, used=False).all()
    for existing in pending:
        created_at = existing.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        if created_at and (now - created_at).total_seconds() < RESET_REQUEST_COOLDOWN_SECONDS:
            return ok_response
        existing.used = True

    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=PasswordResetToken.hash_token(token),
        expiration_date=now + datetime.timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
    )
    result = add_to_db(reset_token)
    if result.get("error"):
        return {"success": False, "message": "Could not generate reset link"}, 500

    try:
        send_password_reset_email(user, f"{FRONTEND_URL}/reset-password/{token}", language=user.language)
    except Exception as e:
        log(f"Failed to send password reset email: {e}", level="ERROR")
        return {"success": False, "message": "Could not send reset email"}, 500

    log(f"Password reset requested for user {user.username}", level="INFO")
    return ok_response

def reset_password(request: Request) -> tuple[dict, int]:
    """Set a new password using a valid reset token, then invalidate all existing sessions."""
    data = request.json or {}
    token = data.get('token')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if not token or not password:
        return {"success": False, "message": "Token and password are required"}, 400
    if password != confirm_password:
        return {"success": False, "message": "Passwords do not match"}, 400

    reset_token = PasswordResetToken.query.filter_by(token_hash=PasswordResetToken.hash_token(token)).first()
    if not reset_token or not reset_token.is_valid():
        return {"success": False, "message": "Invalid or expired reset link"}, 400

    user = db.session.get(UserModel, reset_token.user_id)
    if not user or user.deleted:
        return {"success": False, "message": "Invalid or expired reset link"}, 400

    user.password = generate_password_hash(password, method='pbkdf2:sha256')
    user.session_version += 1
    reset_token.used = True
    result = update_from_db()
    if result.get("error"):
        return {"success": False, "message": "Could not reset password"}, 500

    log(f"Password reset completed for user {user.username}", level="INFO")
    return {"success": True, "message": "Password reset successfully"}, 200

def report_user(request: Request) -> tuple[dict, int]:
    """Report a user for inappropriate behavior."""
    reporter: UserModel | None = get_user_object(current_user.id)
    if not reporter:
        return {"success": False, "message": "Reporter not found"}, 404

    reported_user_info = request.json.get('reported_user_info')
    reason = request.json.get('reason', 'No reason provided')

    reported_user: UserModel | None = get_user_object(reported_user_info)
    if not reported_user:
        return {"success": False, "message": "Reported user not found"}, 404

    group_id = request.json.get('group_id', None)  # Optional: if the report is related to a group
    message_id = request.json.get('message_id', None)  # Optional: if the report is related to a specific message

    report: ReportUserModel = ReportUserModel(
        reporter_id=reporter.id,
        reported_id=reported_user.id,
        group_id = group_id,
        message_id = message_id,
        reason=reason,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    result = add_to_db(report)
    if result.get("error"):
        return result, 500

    log(f"User {reporter.username} reported user {reported_user.username} for reason: {reason}", level="INFO")

    return {"success": True, "message": "User reported successfully"}, 200