from flask import Flask, Request, request, session
from flask_login import LoginManager
from models import UserModel
from db import db
import os
from lite_logging.lite_logging import log

from auth import create_user, login, update_user, delete_user

app = Flask(__name__)

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


#### USER ENDPOINTS ####

@app.route('/register', methods=['POST'])
def create_user_endpoint():
    return create_user(request)

@app.route('/register/<int:user_id>/', methods=['PUT'])
def update_user_endpoint(user_id):
    return update_user(user_id)

@app.route('/register/<int:user_id>/', methods=['DELETE'])
def delete_user_endpoint(user_id):
    return delete_user(user_id)

@app.route('/account/<int:user_id>/', methods=['GET'])
def test_get_user(user_id):
    user = UserModel.query.get(user_id)
    if not user:
        return {"message": "User not found"}, 404
    return {"email": user.email, "username": user.username, "date_created": user.date_created}, 200

### LOGIN ENDPOINTS ###

@app.route('/login', methods=['POST'])
def login_endpoint():
    return login(request)

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