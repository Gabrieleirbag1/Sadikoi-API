from flask import Flask, request, send_from_directory, session
from flask_cors import CORS
from flask_login import LoginManager, logout_user
import os
from lite_logging.lite_logging import log

from models import UserModel
from group import create_group, get_group, update_group, delete_group, get_user_groups, answer_invitation, remove_user_from_group, get_group_invitation
from chat import get_messages, send_message
from question import get_question, vote_question
from feedback import create_bug_report, create_suggestion
from db import db
from auth import register_user, get_user, google_login_handler, login, logout, update_user, delete_user, logout_sessions, verify_device, list_devices, revoke_device
from config import SECRET_KEY

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1000 * 1000
CORS(app, supports_credentials=True)

def configure_app(db_name: str) -> None:
    """Configure the Flask app with the given database name.
    
    :param str db_name: The name of the database.

    :return: None
    """
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_name}.db'
    app.secret_key = SECRET_KEY

    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True

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
        
    @app.before_request
    def check_authentication():
        # Allow OPTIONS requests for CORS preflight
        if request.method == 'OPTIONS':
            return
            
        ignore_routes = ['/api/auth/login/', '/api/auth/register/', '/api/auth/google/', '/api/auth/security/verify-device/']
        log(f"Request path: {request.path}, method: {request.method}", level="DEBUG")
        if request.path in ignore_routes and request.method == 'POST':
            return
        if request.path.startswith('/api/auth/profile-picture/'):
            return
            
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {"success": False, "message": "Unauthorized access. Please login first."}, 401

        stored_version = session.get('session_version')
        user = db.session.get(UserModel, int(current_user.id))
        if user and stored_version != user.session_version:
            logout_user()
            return {"success": False, "message": "Session invalidated. Please login again."}, 401

############## AUTH ENDPOINTS ##############

#### REGISTER ENDPOINTS ####

@app.route('/api/auth/register/', methods=['POST'])
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
def login_endpoint():
    log("Login request received with data: " + str(request.json), level="DEBUG")
    return login(request)

@app.route('/api/auth/google/', methods=['POST'])
def google_login_endpoint():
    log("Google login request received", level="DEBUG")
    return google_login_handler(request)

@app.route('/api/auth/logout/', methods=['POST'])
def logout_endpoint():
    return logout()

############## SECURITY ENDPOINTS ##############

@app.route('/api/auth/security/verify-device/', methods=['POST'])
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
def send_message_endpoint(group_id):
    return send_message(group_id, request)


############## QUESTIONS ENDPOINTS ##############

@app.route('/api/questions/<int:group_id>/', methods=['GET'])
def get_questions_endpoint(group_id):
    return get_question(group_id)

@app.route('/api/questions/<int:group_id>/vote/', methods=['POST'])
def vote_question_endpoint(group_id):
    return vote_question(group_id, request)

############## FEEDBACK ENDPOINTS ##############

@app.route('/api/feedback/bug-reports/', methods=['POST'])
def create_bug_report_endpoint():
    return create_bug_report(request)

@app.route('/api/feedback/suggestions/', methods=['POST'])
def create_suggestion_endpoint():
    return create_suggestion(request)

def main(db_name: str = "data-local") -> None:
    """Main function to create the app and initialize the database."
    
    :param str db_name: The name of the database.

    :return: None
    """
    configure_app(db_name)
    create_app()
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    main()
    app.run(port=8082, debug=True)