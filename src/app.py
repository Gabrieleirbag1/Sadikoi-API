from flask import Flask, request, send_from_directory, session
from flask_cors import CORS
from flask_login import LoginManager, current_user, logout_user
from flask_socketio import join_room, leave_room
import os
from werkzeug.middleware.proxy_fix import ProxyFix
from lite_logging.lite_logging import log

from models import UserModel, GroupUser, UserSecurity
from group import create_group, get_group, promote_user_group_role, update_group, delete_group, get_user_groups, answer_invitation, remove_user_from_group, get_group_invitation
from chat import get_messages, send_message
from question import get_question, vote_question, get_questions_by_date
from gifs import get_trending_gifs, get_recent_gifs, search_gifs, share_gif
from feedback import create_bug_report, create_suggestion
from db import db
from manage import has_pending_migrations
from sockets import socketio
from auth import register_user, get_user, google_login_handler, login, logout, update_user, delete_user, logout_sessions, verify_device, list_devices, revoke_device, forgot_password, reset_password, report_user
from config import SECRET_KEY, ALLOWED_ORIGINS
from security import limiter, init_security, json_field_key, user_or_ip_key, SocketRateLimiter
from exceptions import ValueTooLongException
from notifications import get_settings, update_settings, get_group_settings, update_group_settings, register_device, unregister_device, start_scheduler

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1000 * 1000
# Exactly one reverse proxy (Apache) sits in front: trust its X-Forwarded-* headers, nothing more.
# Flask must therefore only listen on 127.0.0.1, otherwise X-Forwarded-For becomes spoofable.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)
init_security(app)
socketio.init_app(app)
socket_join_limiter = SocketRateLimiter(max_events=30, window_seconds=60)

def configure_app(db_name: str) -> None:
    """Configure the Flask app with the given database name.
    
    :param str db_name: The name of the database.

    :return: None
    """
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_name}.db'
    app.secret_key = SECRET_KEY

    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True
    # Flask-Login's "remember me" cookie needs the same settings, or it isn't sent from the mobile app.
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'None'
    app.config['REMEMBER_COOKIE_SECURE'] = True

def create_app():
    """Create the Flask app and initialize the database and login manager."""
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'account'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Load the user with the given user_id.
        
        :param str user_id: The user_id.
        
        :return: The user with the given user_id.
        :rtype: UserModel"""
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return db.session.get(UserModel, int(user_id))
        

    def _force_logout(message: str):
        logout_user()
        session.clear()
        return {"success": False, "message": message}, 401

    @app.before_request
    def check_authentication():
        if request.method == 'OPTIONS':
            return

        ignore_routes = ['/api/auth/login/', '/api/auth/register/', '/api/auth/google/', '/api/auth/security/verify-device/', '/api/auth/security/forgot-password/', '/api/auth/security/reset-password/']
        if request.path in ignore_routes and request.method == 'POST':
            return
        if request.path.startswith('/api/auth/profile-picture/'):
            return

        if not current_user.is_authenticated:
            return {"success": False, "message": "Unauthorized access. Please login first."}, 401

        user = db.session.get(UserModel, int(current_user.id))
        if not user or user.deleted or session.get('session_version') != user.session_version:
            return _force_logout("Session invalidated. Please login again.")

        # Device check: revoked / unauthorized / unknown device => logged out immediately
        device_id = session.get('device_id')
        device = (
            UserSecurity.query.filter_by(user_id=user.id, device_id=device_id).first()
            if device_id else None
        )
        if not device or not device.authorized:
            return _force_logout("Device revoked. Please login again.")

@app.errorhandler(ValueTooLongException)
def handle_too_long(e):
    return {"success": False, "message": str(e)}, 400

############## AUTH ENDPOINTS ##############

#### REGISTER ENDPOINTS ####

@app.route('/api/auth/register/', methods=['POST'])
@limiter.limit("5 per hour")
def create_user_endpoint():
    return register_user(request)

@app.route('/api/auth/account/', methods=['POST'])
def get_user_endpoint():
    return get_user()

@app.route('/api/auth/account/', methods=['PUT'])
def update_user_endpoint():
    return update_user(request)

@app.route('/api/auth/account/<user_info>', methods=['DELETE'])
def delete_user_endpoint(user_info):
    return delete_user(user_info)

@app.route('/api/auth/profile-picture/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

### LOGIN ENDPOINTS ###

@app.route('/api/auth/login/', methods=['POST'])
@limiter.limit("10 per minute; 50 per hour")
@limiter.limit("5 per 15 minutes", key_func=json_field_key("username_or_email"))
def login_endpoint():
    return login(request)

@app.route('/api/auth/google/', methods=['POST'])
@limiter.limit("20 per minute")
def google_login_endpoint():
    log("Google login request received", level="DEBUG")
    return google_login_handler(request)

@app.route('/api/auth/logout/', methods=['POST'])
def logout_endpoint():
    return logout()

############## SECURITY ENDPOINTS ##############

@app.route('/api/auth/security/verify-device/', methods=['POST'])
@limiter.limit("10 per minute")
@limiter.limit("10 per 15 minutes", key_func=json_field_key("user_info"))
def verify_device_endpoint():
    return verify_device(request)

@app.route('/api/auth/security/devices/', methods=['GET'])
def list_devices_endpoint():
    return list_devices()

@app.route('/api/auth/security/logout-devices/', methods=['GET'])
def logout_devices_endpoint():
    print("Logging out all devices for the current user.")
    return logout_sessions()

@app.route('/api/auth/security/devices/', methods=['DELETE'])
def revoke_device_endpoint():
    return revoke_device(request)

@app.route('/api/auth/security/forgot-password/', methods=['POST'])
@limiter.limit("3 per hour")
@limiter.limit("3 per hour", key_func=json_field_key("email"))
def forgot_password_endpoint():
    return forgot_password(request)

@app.route('/api/auth/security/reset-password/', methods=['POST'])
@limiter.limit("10 per hour")
def reset_password_endpoint():
    return reset_password(request)

@app.route('/api/auth/security/report-user/', methods=['POST'])
@limiter.limit("5 per hour", key_func=user_or_ip_key)
def report_user_endpoint():
    return report_user(request)

############## USER-GROUP ENDPOINTS ##############

### GROUP ENDPOINTS ###

@app.route('/api/groups/', methods=['POST'])
def create_group_endpoint():
    return create_group(request)

@app.route('/api/groups/<int:group_id>/', methods=['GET'])
def get_group_endpoint(group_id):
    return get_group(group_id)

@app.route('/api/groups/<int:group_id>/', methods=['PUT'])
def update_group_endpoint(group_id):
    return update_group(group_id)

@app.route('/api/groups/<int:group_id>/', methods=['DELETE'])
def delete_group_endpoint(group_id):
    return delete_group(group_id)

@app.route('/api/groups/user/', methods=['GET'])
def get_user_groups_endpoint():
    return get_user_groups()

@app.route('/api/groups/<int:group_id>/role/', methods=['POST'])
def promote_user_group_role_endpoint(group_id):
    return promote_user_group_role(group_id)

@app.route('/api/groups/<int:group_id>/invitations/', methods=['GET'])
def get_group_invitation_endpoint(group_id):
    return get_group_invitation(group_id)

@app.route('/api/groups/invitations/<token>/', methods=['POST'])
def answer_invitation_endpoint(token):
    return answer_invitation(token)

@app.route('/api/groups/<int:group_id>/<user_info>/', methods=['DELETE'])
def remove_user_from_group_endpoint(group_id, user_info):
    return remove_user_from_group(group_id, user_info)

## CHAT ENDPOINTS ###

@app.route('/api/groups/<int:group_id>/messages/', methods=['GET'])
def get_messages_endpoint(group_id):
    return get_messages(group_id)

@app.route('/api/groups/<int:group_id>/messages/', methods=['POST'])
@limiter.limit("30 per minute", key_func=user_or_ip_key)
def send_message_endpoint(group_id):
    return send_message(group_id, request)


############## QUESTIONS ENDPOINTS ##############

@app.route('/api/questions/<int:group_id>/', methods=['GET'])
def get_question_endpoint(group_id):
    return get_question(group_id)


@app.route('/api/questions/<int:group_id>/<int:month>/<int:year>/', methods=['GET'])
def get_questions_by_date_endpoint(group_id, month, year):
    return get_questions_by_date(group_id, month, year)

@app.route('/api/questions/<int:group_id>/vote/', methods=['POST'])
@limiter.limit("30 per minute", key_func=user_or_ip_key)
def vote_question_endpoint(group_id):
    return vote_question(group_id, request)

############## FEEDBACK ENDPOINTS ##############

@app.route('/api/feedback/bug-reports/', methods=['POST'])
@limiter.limit("5 per hour", key_func=user_or_ip_key)
def create_bug_report_endpoint():
    return create_bug_report(request)

@app.route('/api/feedback/suggestions/', methods=['POST'])
@limiter.limit("5 per hour", key_func=user_or_ip_key)
def create_suggestion_endpoint():
    return create_suggestion(request)



############## PUSH NOTIFICATIONS ENDPOINTS ##############

@app.route('/api/notifications/settings/', methods=['GET'])
def get_notification_settings_endpoint():
    return get_settings()

@app.route('/api/notifications/settings/', methods=['PUT'])
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def update_notification_settings_endpoint():
    return update_settings(request)

@app.route('/api/notifications/settings/groups/<int:group_id>/', methods=['GET'])
def get_group_notification_settings_endpoint(group_id: int):
    return get_group_settings(group_id)

@app.route('/api/notifications/settings/groups/<int:group_id>/', methods=['PUT'])
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def update_group_notification_settings_endpoint(group_id: int):
    return update_group_settings(group_id, request)

@app.route('/api/notifications/devices/', methods=['POST'])
@limiter.limit("20 per minute", key_func=user_or_ip_key)
def register_push_device_endpoint():
    return register_device(request)

@app.route('/api/notifications/devices/', methods=['DELETE'])
@limiter.limit("20 per minute", key_func=user_or_ip_key)
def unregister_push_device_endpoint():
    return unregister_device(request)

############## GIFS (Klipy proxy: the API key stays on the server) ##############

@app.route('/api/gifs/trending/', methods=['GET'])
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def get_trending_gifs_endpoint():
    return get_trending_gifs()

@app.route('/api/gifs/recent/', methods=['GET'])
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def get_recent_gifs_endpoint():
    return get_recent_gifs()

@app.route('/api/gifs/search/', methods=['GET'])
@limiter.limit("30 per minute", key_func=user_or_ip_key)
def search_gifs_endpoint():
    return search_gifs(request)

@app.route('/api/gifs/share/<slug>/', methods=['POST'])
@limiter.limit("60 per minute", key_func=user_or_ip_key)
def share_gif_endpoint(slug):
    return share_gif(slug)

############## SOCKET IO EVENTS ##############

@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False
    log(f"User {current_user.id} connected", level="DEBUG")

@socketio.on('disconnect')
def handle_disconnect():
    log("User disconnected", level="DEBUG")

@socketio.on('join_group')
def handle_join(data):
    if not current_user.is_authenticated:
        return
    if not socket_join_limiter.allow(str(current_user.id)):
        log(f"Rate limited join_group for user {current_user.id}", level="WARNING")
        return
    group_id = int(data['groupId'])
    if not GroupUser.query.filter_by(user_id=current_user.id, group_id=group_id).first():
        log(f"Denied join_group: user {current_user.id} not a member of group {group_id}", level="WARNING")
        return
    join_room(str(group_id))
    log(f"User {current_user.id} joined room {group_id}", level="DEBUG")

@socketio.on('leave_group')
def handle_leave(data):
    group_id = str(data['groupId'])
    leave_room(group_id)
    log(f"User left room {group_id}", level="DEBUG")

def main(db_name: str = "data-local") -> None:
    """Main function to create the app and check the database schema."
    
    :param str db_name: The name of the database.

    :return: None
    """
    configure_app(db_name)
    create_app()
    # The schema is owned by the migrations (python src/manage.py migrate), never by db.create_all().
    with app.app_context():
        if has_pending_migrations():
            log("The database is not up to date: run `python src/manage.py migrate`.", level="ERROR")
    # Daily question and vote reminder push notifications (checks every minute).
    start_scheduler(app)

if __name__ == '__main__':
    main()
    # Werkzeug's debugger allows remote code execution: opt-in only, never in production.
    debug = os.environ.get('FLASK_DEBUG') == '1'
    socketio.run(
        app,
        host='0.0.0.0',
        port=8082,
        debug=debug,
        allow_unsafe_werkzeug=not debug
    )