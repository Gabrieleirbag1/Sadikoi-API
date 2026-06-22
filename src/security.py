import datetime

from flask import Request
from flask_login import current_user

from models import UserModel, UserSecurity
from db import add_to_db, update_from_db, delete_from_db, db
from email_sender import send_email
from lite_logging.lite_logging import log

MAX_LOGIN_ATTEMPTS = 5
AUTH_CODE_TTL_MINUTES = 10
REAUTH_AFTER_DAYS = 60

def get_user_object(user_info: str | int) -> UserModel | None:
    """Get the user object with the given user_info."""
    if isinstance(user_info, int) or user_info.isdigit():
        return UserModel.query.get(int(user_info))
    else:
        return UserModel.query.filter((UserModel.email == user_info) | (UserModel.username == user_info)).first()
    
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
        send_email(
            destinataire=user.email,
            sujet="Code de vérification - Nouvel appareil détecté",
            contenu=(
                f"Bonjour {user.username},\n\n"
                f"Une tentative de connexion a été détectée depuis un nouvel appareil "
                f"({device.device_name}, IP: {device.ip_address}).\n\n"
                f"Votre code de vérification est : {code}\n\n"
                f"Ce code expire dans {AUTH_CODE_TTL_MINUTES} minutes.\n\n"
                f"Si vous n'êtes pas à l'origine de cette tentative, changez votre mot de passe immédiatement."
            ),
        )
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


def list_devices(user: UserModel) -> tuple[dict, int]:
    """List all known devices for the current user."""
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
    user: UserModel | None = UserModel.query.get(current_user.id)
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