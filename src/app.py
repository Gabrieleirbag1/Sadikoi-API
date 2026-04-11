from flask import Flask
from flask_login import LoginManager, login_user, current_user, login_required, logout_user
from models import UserModel
from db import db, add_to_db
import os

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

@app.route('/create_user', methods=['POST'])
def create_user(request):
    email = request.json.get('email')
    username = request.json.get('username')
    password = request.json.get('password')

    if not email or not username or not password:
        return {"message": "Email, username, and password are required"}, 400

    user = UserModel(email=email, username=username, password=password)

    result = add_to_db(user)
    if result.get("error"):
        return result, 500
    
    return {"message": "User created successfully"}, 201

@app.route('/delete_user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = UserModel.query.get(user_id)
    if not user:
        return {"message": "User not found"}, 404

    result = add_to_db(user)
    if result.get("error"):
        return result, 500

    return {"message": "User deleted successfully"}, 200


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
    app.run(port=8082, debug=True)