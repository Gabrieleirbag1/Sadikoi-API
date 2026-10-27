from flask_login import UserMixin
import datetime
import secrets
import hashlib
from db import db
from sqlalchemy.orm import validates
import uuid
from exceptions import ValueTooLongException

class GroupUser(db.Model):
    """Association table for users and groups."""
    __tablename__ = 'group_user'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), primary_key=True)
    role = db.Column(db.String(50), default='member')
    joined_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    # Push notifications: the user turned off every notification from this group.
    notifications_muted = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    
class ItemModel(db.Model):
    """Tracks items per user, scoped to a group membership"""
    __tablename__ = 'items'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    inactive_since = db.Column(db.DateTime(timezone=True), nullable=True)
    acquired_at = db.Column(db.DateTime(timezone=True), nullable=False)

    user = db.relationship('UserModel', backref=db.backref('items', lazy='dynamic'))

class UserSecurity(db.Model):
    """Tracks known devices per user and their authorization/security state."""
    __tablename__ = 'user_security'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    device_id = db.Column(db.String(64), nullable=False)
    device_name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)

    first_seen = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    last_login = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    auth_code = db.Column(db.String(6), nullable=True)
    auth_code_expiration = db.Column(db.DateTime(timezone=True), nullable=True)
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
    date_created = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    language = db.Column(db.String(10), default='en')
    session_version = db.Column(db.Integer, default=0)
    deleted = db.Column(db.Boolean, default=False)
    # Push notification preferences (per group: GroupUser.notifications_muted).
    notify_messages = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    notify_questions = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    notify_vote_reminder = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
                                
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

class PasswordResetToken(db.Model):
    """Single-use password reset token. Only the SHA-256 hash of the token is stored."""
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expiration_date = db.Column(db.DateTime(timezone=True), nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    user = db.relationship('UserModel', backref=db.backref('password_reset_tokens', lazy='dynamic'))

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def is_valid(self) -> bool:
        """True if the token has not been used and has not expired."""
        if self.used:
            return False
        expiration = self.expiration_date
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.now(datetime.timezone.utc) <= expiration

class GroupInvitationModel(db.Model):
    """Group invitation model for the database."""
    __tablename__ = 'group_invitations'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    expiration_date = db.Column(db.DateTime(timezone=True), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)

class GroupModel(db.Model):
    """Group model for the database."""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30))
    description = db.Column(db.String(200), server_default="")
    date_created = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    daily_reset_timestamp = db.Column(db.Time, server_default=db.text("'15:00:00'"))
    themes = db.Column(db.JSON, nullable=False, server_default=db.text("'[]'"))
    # Start of the last daily window whose push notification was sent (so each one is sent once).
    last_question_notified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_vote_reminder_at = db.Column(db.DateTime(timezone=True), nullable=True)

    users = db.relationship('UserModel', secondary='group_user', backref=db.backref('groups', lazy='dynamic'))
    questions = db.relationship('QuestionModel', backref='group', lazy='dynamic')

    def __repr__(self) -> str:
        """Return the group's name.
        
        :return: The group's name.
        :rtype: str
        """
        return f'Group: {self.name}'

    @validates('name')
    def validate_name(self, _key: str, name: str) -> str:
        """Validate the group name to ensure it is 30 characters or less.
        
        :param str key: The key to validate.
        :param str name: The group name to validate.

        :raise ValueTooLongException: If the group name is more than 30 characters.

        :return: The group name.
        :rtype: str
        """
        if len(name) > 30:
            raise ValueTooLongException("Group name must be 30 characters or less")
        return name

    @validates('description')
    def validate_description(self, _key: str, description: str) -> str:
        """Validate the group description to ensure it is 200 characters or less.
        
        :param str key: The key to validate.
        :param str description: The group description to validate.

        :raise ValueTooLongException: If the group description is more than 200 characters.

        :return: The group description.
        :rtype: str
        """
        if description is None:
            return ""
        if len(description) > 200:
            raise ValueTooLongException("Group description must be 200 characters or less")
        return description
    
class ChatMessageModel(db.Model):
    """Chat message model for the database."""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
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
    """Question model for the database.

    Note: `iteration` is no longer a stored column. Every time a question is
    served (even a repeat of an earlier question_id), a new row is inserted
    here, so history is fully preserved. "Iteration" (i.e. how many times a
    given question_id has been asked in a group) is now a *computed* value —
    see `get_question_iteration_count` / `get_mean_iterations_question` in
    question.py — obtained by counting rows that share the same
    (group_id, question_id) pair.
    """
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime(timezone=True), nullable=False)
    theme = db.Column(db.String(50), nullable=False)
    enableSelfVote = db.Column(db.Boolean, default=True)
    enableMultipleVoting = db.Column(db.Boolean, default=False)
    voteNumberLimit = db.Column(db.Integer, default=1)
    canWrite = db.Column(db.Boolean, default=False)
    item_name = db.Column(db.String(100))
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    votes = db.relationship('QuestionVote', back_populates='question', lazy='dynamic')
    announcement = db.relationship('ItemAnnouncement', back_populates='question', uselist=False)

class ItemAnnouncement(db.Model):
    """What happened to the previous question's item, announced with the question it led to.

    - new: `user` got an item nobody held.
    - stolen: `user` took the item from `from_user`, who had `streak` days on it.
    - kept: `user` still holds the item, with `streak` days on it.
    """
    __tablename__ = 'item_announcements'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, unique=True)
    kind = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    streak = db.Column(db.Integer, nullable=False)

    question = db.relationship('QuestionModel', back_populates='announcement')
    user = db.relationship('UserModel', foreign_keys=[user_id])
    from_user = db.relationship('UserModel', foreign_keys=[from_user_id])

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
    date = db.Column(db.DateTime(timezone=True), nullable=False)
    voterUser_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    written_answer = db.Column(db.String(500))

    voterUser = db.relationship('UserModel', foreign_keys=[voterUser_id], back_populates='question_votes_cast')
    question = db.relationship('QuestionModel', back_populates='votes')
    targets = db.relationship('QuestionVoteTarget', back_populates='vote', lazy='dynamic')

BUG_STATUSES = ("open", "in_progress", "resolved")

class BugReportModel(db.Model):
    """Bug report model for the database."""
    __tablename__ = 'bug_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000), nullable=False)
    device_name = db.Column(db.String(100), nullable=False, default="Unknown Device")
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    status = db.Column(db.String(20), nullable=False, default="open", server_default="open")

    user = db.relationship('UserModel', backref=db.backref('bug_reports', lazy='dynamic'))

    @validates('status')
    def validate_status(self, _key: str, status: str) -> str:
        """Validate the status against BUG_STATUSES.

        :raise ValueError: If the status is unknown.

        :return: The status.
        :rtype: str
        """
        if status not in BUG_STATUSES:
            raise ValueError(f"Bug report status must be one of {', '.join(BUG_STATUSES)}")
        return status

    def __repr__(self) -> str:
        """Return the bug report description and timestamp.
        
        :return: The bug report description and timestamp.
        :rtype: str
        """
        return f'BugReport: {self.description} at {self.timestamp}'

class ReportUserModel(db.Model):
    """Report user model for the database."""
    __tablename__ = 'report_users'

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reported_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_messages.id'), nullable=True)
    reason = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    reporter = db.relationship('UserModel', foreign_keys=[reporter_id], backref=db.backref('reports_made', lazy='dynamic'))
    reported = db.relationship('UserModel', foreign_keys=[reported_id], backref=db.backref('reports_received', lazy='dynamic'))
    group = db.relationship('GroupModel', foreign_keys=[group_id], backref=db.backref('reports', lazy='dynamic'))
    message = db.relationship('ChatMessageModel', foreign_keys=[message_id], backref=db.backref('reports', lazy='dynamic'))

    def __repr__(self) -> str:
        """Return the report reason and timestamp.
        
        :return: The report reason and timestamp.
        :rtype: str
        """
        return f'ReportUser: {self.reason} at {self.timestamp}'
    
class SuggestionModel(db.Model):
    """Suggestion model for the database."""
    __tablename__ = 'suggestions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    theme = db.Column(db.String(50), nullable=False)
    question = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    user = db.relationship('UserModel', backref=db.backref('suggestions', lazy='dynamic'))

    def __repr__(self) -> str:
        """Return the suggestion description and timestamp.
        
        :return: The suggestion description and timestamp.
        :rtype: str
        """
        return f'Suggestion: {self.description} at {self.timestamp}'


class PushTokenModel(db.Model):
    """A phone that receives push notifications (Firebase Cloud Messaging registration token)."""
    __tablename__ = 'push_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    device_id = db.Column(db.String(64), nullable=True)
    platform = db.Column(db.String(20), nullable=False, default='android')
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())

    user = db.relationship('UserModel', backref=db.backref('push_tokens', lazy='dynamic'))
