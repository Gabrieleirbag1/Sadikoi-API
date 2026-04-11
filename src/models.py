from flask_login import UserMixin
from db import db
from sqlalchemy.orm import validates
from exceptions import ValueTooLongException, UppercaseException

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