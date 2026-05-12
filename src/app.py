from flask import Flask, request
from flask_cors import CORS
from flask_login import LoginManager
from models import UserModel
from group import create_group, get_group, update_group, delete_group, get_user_groups, add_user_to_group, remove_user_from_group
from chat import get_messages, send_message
from question import get_question, get_question_votes, vote_question
from db import db
import os
from lite_logging.lite_logging import log

from auth import create_user, get_user, login, update_user, delete_user

app = Flask(__name__)
CORS(app)

def configure_app(db_name: str) -> None:
    """Configure the Flask app with the given database name.
    
    :param str db_name: The name of the database.

    :return: None
    """
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_name}.db'
    app.secret_key = os.urandom(24) 

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
        return UserModel.query.get(int(user_id))


############## AUTH ENDPOINTS ##############

#### REGISTER ENDPOINTS ####

@app.route('/api/register', methods=['POST'])
def create_user_endpoint():
    return create_user(request)

@app.route('/api/register/<user_info>/', methods=['PUT'])
def update_user_endpoint(user_info):
    return update_user(user_info, request)

@app.route('/api/register/<user_info>/', methods=['DELETE'])
def delete_user_endpoint(user_info):
    return delete_user(user_info)

@app.route('/api/account/<user_info>/', methods=['GET'])
def get_user_endpoint(user_info: str | int):
    return get_user(user_info)

### LOGIN ENDPOINTS ###

@app.route('/api/login', methods=['POST'])
def login_endpoint():
    log("Login request received with data: " + str(request.json), level="DEBUG")
    return login(request)


############## USER-GROUP ENDPOINTS ##############

### GROUP ENDPOINTS ###

@app.route('/api/groups', methods=['POST'])
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

@app.route('/api/groups/user/<user_info>/', methods=['GET'])
def get_user_groups_endpoint(user_info):
    return get_user_groups(user_info)

### USERS IN GROUP ENDPOINTS ###

@app.route('/api/groups/<int:group_id>/<user_info>/', methods=['POST'])
def add_user_to_group_endpoint(group_id, user_info):
    return add_user_to_group(group_id, user_info)

@app.route('/api/groups/<int:group_id>/<user_info>/', methods=['DELETE'])
def remove_user_from_group_endpoint(group_id, user_info):
    return remove_user_from_group(group_id, user_info)

## CHAT ENDPOINTS ###

@app.route('/api/groups/<int:group_id>/messages', methods=['GET'])
def get_messages_endpoint(group_id):
    return get_messages(group_id)

@app.route('/api/groups/<int:group_id>/messages', methods=['POST'])
def send_message_endpoint(group_id):
    return send_message(group_id, request)


############## QUESTIONS ENDPOINTS ##############

@app.route('/api/questions/<int:group_id>', methods=['GET'])
def get_questions_endpoint(group_id):
    return get_question(group_id)

@app.route('/api/questions/<int:group_id>/vote', methods=['POST'])
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