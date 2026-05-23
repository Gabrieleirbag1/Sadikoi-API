from flask import Flask, request
from flask_cors import CORS
from flask_login import LoginManager
from models import UserModel
from group import create_group, get_group, update_group, delete_group, get_user_groups, answer_invitation, remove_user_from_group, get_group_invitation
from chat import get_messages, send_message
from question import get_question, get_question_votes, vote_question
from db import db
import os
from lite_logging.lite_logging import log

from auth import create_user, get_user, login, logout, update_user, delete_user

app = Flask(__name__)
CORS(app, supports_credentials=True)

def get_secret_key(length: int = 32) -> str:
    """Generate a random secret key of the specified length.
    
    :param int length: The length of the secret key. Default is 32.

    :return: A random secret key.
    :rtype: str
    """
    secrets_path = os.path.join(os.path.dirname(__file__), '.secrets')
    if os.path.exists(secrets_path):
        log("Found .secrets file, loading secret key from it.", level="DEBUG")
        with open(secrets_path, 'r') as f:
            for line in f:
                if line.startswith('SECRET_KEY='):
                    return line.strip().split('=', 1)[1]
    
    secret_key = os.urandom(length).hex()
    log("Generated new secret key.", level="DEBUG")
    with open(secrets_path, 'w') as f:
        f.write(f'SECRET_KEY={secret_key}')
    return secret_key

def configure_app(db_name: str) -> None:
    """Configure the Flask app with the given database name.
    
    :param str db_name: The name of the database.

    :return: None
    """
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_name}.db'
    app.secret_key = get_secret_key()

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
            
        ignore_routes = ['/api/login/', '/api/register/']
        log(f"Request path: {request.path}, method: {request.method}", level="DEBUG")
        if request.path in ignore_routes and request.method == 'POST':
            return
            
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {"success": False, "message": "Unauthorized access. Please login first."}, 401


############## AUTH ENDPOINTS ##############

#### REGISTER ENDPOINTS ####

@app.route('/api/register/', methods=['POST'])
def create_user_endpoint():
    return create_user(request)

@app.route('/api/register/<user_info>/', methods=['PUT'])
def update_user_endpoint(user_info):
    return update_user(user_info, request)

@app.route('/api/register/<user_info>/', methods=['DELETE'])
def delete_user_endpoint(user_info):
    return delete_user(user_info)

@app.route('/api/account/', methods=['GET'])
def get_user_endpoint():
    return get_user()

### LOGIN ENDPOINTS ###

@app.route('/api/login/', methods=['POST'])
def login_endpoint():
    log("Login request received with data: " + str(request.json), level="DEBUG")
    return login(request)

@app.route('/api/logout/', methods=['POST'])
def logout_endpoint():
    return logout()


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

@app.route('/api/questions/<int:group_id>/vote', methods=['GET'])
def get_question_votes_endpoint(group_id):
    return get_question_votes(group_id)

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