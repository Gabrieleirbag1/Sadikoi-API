from flask_login import UserMixin
from db import db
from sqlalchemy.orm import validates
from exceptions import ValueTooLongException, UppercaseException

class GroupUser(db.Model):
    """Association table for users and groups."""
    __tablename__ = 'group_user'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), primary_key=True)
    role = db.Column(db.String(50), default='member')  # Exemple : 'admin', 'member'
    joined_at = db.Column(db.DateTime, server_default=db.func.now())
    
class UserModel(UserMixin, db.Model):
    """User model for the database."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(80), unique=True)
    username = db.Column(db.String(40), unique=True)
    password = db.Column(db.String(80))
    date_created = db.Column(db.DateTime, server_default=db.func.now())
    voted_questions = db.relationship('QuestionModel', secondary='question_vote', back_populates='votedUsers', lazy='dynamic')

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
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(200), server_default="")
    date_created = db.Column(db.DateTime, server_default=db.func.now())

    users = db.relationship('UserModel', secondary='group_user', backref=db.backref('groups', lazy='dynamic'))
    questions = db.relationship('QuestionModel', backref='group', lazy='dynamic')

    def __repr__(self) -> str:
        """Return the group's name.
        
        :return: The group's name.
        :rtype: str
        """
        return f'Group: {self.name}'
    
class ChatMessageModel(db.Model):
    """Chat message model for the database."""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)

    user = db.relationship('UserModel', backref=db.backref('messages', lazy='dynamic'))
    group = db.relationship('GroupModel', backref=db.backref('messages', lazy='dynamic'))

    def __repr__(self) -> str:
        """Return the message content and timestamp.
        
        :return: The message content and timestamp.
        :rtype: str
        """
        return f'Message: {self.content} at {self.timestamp}'
    
class QuestionModel(db.Model):
    """Question model for the database."""
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, unique=True, nullable=False)
    content = db.Column(db.String(500), nullable=False)
    date = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    theme = db.Column(db.String(50), nullable=False)
    enableSelfVote = db.Column(db.Boolean, default=True)
    enableMultipleVoting = db.Column(db.Boolean, default=False)
    voteNumberLimit = db.Column(db.Integer, default=1)
    canWrite = db.Column(db.Boolean, default=False)
    item = db.Column(db.String(100))
    iteration = db.Column(db.Integer, default=1)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    votedUsers = db.relationship('UserModel', secondary='question_vote', back_populates='voted_questions', lazy='dynamic')

class QuestionVote(db.Model):
    """Association table for users and questions."""
    __tablename__ = 'question_vote'

    userVoting_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), primary_key=True)