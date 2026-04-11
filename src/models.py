from flask_login import UserMixin
from db import db
from sqlalchemy.orm import validates
from exceptions import ValueTooLongException, UppercaseException

class GroupUser(db.Model):
    """Association table for users and groups."""
    __tablename__ = 'group_user'  # Nom de la table
    user_id = db.Column(db.Integer, db.ForeignKey('user_model.id'), primary_key=True)  # Clé étrangère vers UserModel
    group_id = db.Column(db.Integer, db.ForeignKey('group_model.id'), primary_key=True)  # Clé étrangère vers GroupModel
    # Optionnel : ajoutez des champs comme rôle ou date
    role = db.Column(db.String(50), default='member')  # Exemple : 'admin', 'member'
    joined_at = db.Column(db.DateTime, server_default=db.func.now())
    
class UserModel(UserMixin, db.Model):
    """User model for the database."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(80), unique=True)
    username = db.Column(db.String(40), unique=True)
    password = db.Column(db.String(80))
    date_created = db.Column(db.DateTime, server_default=db.func.now())

    @validates('email')
    def validate_email(self, _key: str, email: str) -> str:
        """Validate the email to ensure it is 80 characters or less.
        
        :param str key: The key to validate.
        :param str email: The email to validate.

        :raise ValueTooLongException: If the email is more than 80 characters.

        :return: The email.
        :rtype: str
        """
        if len(email) > 80:
            raise ValueTooLongException("Email must be 80 characters or less")
        return email

    @validates('username')
    def validate_username(self, _key: str, username: str) -> str:
        """Validate the username to ensure it is 40 characters or less.
        
        :param str key: The key to validate.
        :param str username: The username to validate.

        :raise ValueTooLongException: If the username is more than 40 characters.

        :return: The username.
        :rtype: str
        """
        if len(username) > 40:
            raise ValueTooLongException("Username must be 40 characters or less")
        for char in username:
            if char.isupper():
                raise UppercaseException("Username must be lowercase")
        return username

    def __repr__(self) -> str:
        """Return the user's username.
        
        :return: The user's username.
        :rtype: str
        """
        return f'User: {self.username}'
    
class GroupModel(db.Model):
    """Group model for the database."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(200))
    date_created = db.Column(db.DateTime, server_default=db.func.now())

    users = db.relationship('UserModel', secondary='group_user', backref=db.backref('groups', lazy='dynamic'))

    def __repr__(self) -> str:
        """Return the group's name.
        
        :return: The group's name.
        :rtype: str
        """
        return f'Group: {self.name}'