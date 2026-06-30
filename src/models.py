from flask_login import UserMixin
import datetime
import secrets
from db import db
from sqlalchemy.orm import validates
import uuid
from exceptions import ValueTooLongException

class GroupUser(db.Model):
    """Association table for users and groups."""
    __tablename__ = 'group_user'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), primary_key=True)
    role = db.Column(db.String(50), default='member')  # Exemple : 'admin', 'member'
    joined_at = db.Column(db.DateTime, server_default=db.func.now())

class UserSecurity(db.Model):
    """Tracks known devices per user and their authorization/security state."""
    __tablename__ = 'user_security'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    device_id = db.Column(db.String(64), nullable=False)
    device_name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)

    first_seen = db.Column(db.DateTime, server_default=db.func.now())
    last_login = db.Column(db.DateTime, server_default=db.func.now())

    auth_code = db.Column(db.String(6), nullable=True)
    auth_code_expiration = db.Column(db.DateTime, nullable=True)
    login_attempts = db.Column(db.Integer, default=0)
    authorized = db.Column(db.Boolean, default=False)

    user = db.relationship('UserModel', backref=db.backref('security_devices', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_id', name='uq_user_device'),
    )

    def __repr__(self) -> str:
        return f'UserSecurity: user={self.user_id} device={self.device_name} authorized={self.authorized}'

    def generate_auth_code(self, ttl_minutes: int = 10) -> str:
        """Generate a fresh 6-digit auth code with expiration, store it, and return it."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.auth_code = code
        self.auth_code_expiration = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ttl_minutes)
        self.login_attempts = 0
        self.authorized = False
        return code

    def is_code_valid(self, submitted_code: str) -> bool:
        """Check if the submitted code matches and hasn't expired."""
        if not self.auth_code or not self.auth_code_expiration:
            return False
        now = datetime.datetime.now(datetime.timezone.utc)
        expiration = self.auth_code_expiration
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=datetime.timezone.utc)
        if now > expiration:
            return False
        return secrets.compare_digest(self.auth_code, submitted_code)

    def clear_auth_code(self) -> None:
        self.auth_code = None
        self.auth_code_expiration = None
        self.login_attempts = 0

    def needs_reauthorization(self, max_days: int = 60) -> bool:
        """True if device is unauthorized, or was authorized but is stale (> max_days since last_login)."""
        if not self.authorized:
            return True
        last_login = self.last_login
        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - last_login) > datetime.timedelta(days=max_days)

class UserModel(UserMixin, db.Model):
    """User model for the database."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, default=lambda: uuid.uuid4().int % (10 ** 14))
    email = db.Column(db.String(80), unique=True)
    username = db.Column(db.String(40), unique=True)
    password = db.Column(db.String(80))
    profile_picture = db.Column(db.String(200), nullable=True)
    date_created = db.Column(db.DateTime, server_default=db.func.now())
    language = db.Column(db.String(10), default='en')
    session_version = db.Column(db.Integer, default=0)
                                
    question_votes_cast = db.relationship(
        'QuestionVote',
        back_populates='voterUser',
        foreign_keys='QuestionVote.voterUser_id',
        lazy='dynamic',
    )
    question_vote_targets = db.relationship(
        'QuestionVoteTarget',
        back_populates='votedUser',
        foreign_keys='QuestionVoteTarget.votedUser_id',
        lazy='dynamic',
    )

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
        return username

    def __repr__(self) -> str:
        """Return the user's username.
        
        :return: The user's username.
        :rtype: str
        """
        return f'User: {self.username}'

class GroupInvitationModel(db.Model):
    """Group invitation model for the database."""
    __tablename__ = 'group_invitations'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    expiration_date = db.Column(db.DateTime, nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)

class GroupModel(db.Model):
    """Group model for the database."""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    description = db.Column(db.String(200), server_default="")
    date_created = db.Column(db.DateTime, server_default=db.func.now())
    daily_reset_timestamp = db.Column(db.Time, server_default=db.text("'15:00:00'"))

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
    question_id = db.Column(db.Integer, nullable=False)
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
    votes = db.relationship('QuestionVote', back_populates='question', lazy='dynamic')

class QuestionVoteTarget(db.Model):
    """Association table for votes and the users who were voted for."""
    __tablename__ = 'question_vote_target'

    vote_id = db.Column(db.Integer, db.ForeignKey('question_vote.id'), primary_key=True)
    votedUser_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)

    vote = db.relationship('QuestionVote', back_populates='targets')
    votedUser = db.relationship('UserModel', back_populates='question_vote_targets')


class QuestionVote(db.Model):
    """Vote for a question (one per user per group per day)."""
    __tablename__ = 'question_vote'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    voterUser_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    written_answer = db.Column(db.String(500))

    voterUser = db.relationship('UserModel', foreign_keys=[voterUser_id], back_populates='question_votes_cast')
    question = db.relationship('QuestionModel', back_populates='votes')
    targets = db.relationship('QuestionVoteTarget', back_populates='vote', lazy='dynamic')

class BugReportModel(db.Model):
    """Bug report model for the database."""
    __tablename__ = 'bug_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False, required=True)
    description = db.Column(db.String(1000), nullable=False, required=True)
    device_name = db.Column(db.String(100), nullable=False, default="Unknown Device")
    timestamp = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship('UserModel', backref=db.backref('bug_reports', lazy='dynamic'))

    def __repr__(self) -> str:
        """Return the bug report description and timestamp.
        
        :return: The bug report description and timestamp.
        :rtype: str
        """
        return f'BugReport: {self.description} at {self.timestamp}'