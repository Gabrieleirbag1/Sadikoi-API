import datetime
import os
import threading

import requests
from flask import Request, current_app
from flask_login import current_user
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from lite_logging.lite_logging import log

from builder import current_window_start
from config import ALLOWED_LANGUAGES, FIREBASE_SERVICE_ACCOUNT_PATH
from db import db, update_from_db
from models import ChatMessageModel, GroupModel, GroupUser, PushTokenModel, QuestionModel, UserModel
from sockets import socketio

DAY = datetime.timedelta(days=1)
REMINDER_BEFORE_END = datetime.timedelta(hours=1)
SCHEDULER_INTERVAL_SECONDS = 60
MESSAGE_PREVIEW_LENGTH = 150

# Android notification channels, created by the app (the user can also tune them in Android settings).
CHANNEL_MESSAGES = 'messages'
CHANNEL_QUESTIONS = 'questions'
CHANNEL_REMINDERS = 'reminders'
CHANNEL_ANSWERS = 'answers'

TEXTS = {
    'en': {
        'message': '{user}: {content}',
        'gif': '{user} sent a GIF',
        'question': 'New question of the day!',
        'reminder': '1 hour left to vote!',
        'answer': '{user} answered the question of the day!',
    },
    'fr': {
        'message': '{user} : {content}',
        'gif': '{user} a envoyé un GIF',
        'question': 'Nouvelle question du jour !',
        'reminder': "Plus qu'1 h pour voter !",
        'answer': '{user} a répondu à la question du jour !',
    },
}

# API setting name -> column, the same on UserModel (global switch) and GroupUser (this group's switch).
SETTINGS_COLUMNS = {
    'messages': 'notify_messages',
    'questions': 'notify_questions',
    'vote_reminder': 'notify_vote_reminder',
    'answers': 'notify_answers',
}
PLATFORMS = {'android', 'ios'}


def _as_utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """SQLite hands back naive datetimes: they are UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def _texts(user: UserModel) -> dict:
    return TEXTS[user.language if user.language in ALLOWED_LANGUAGES else 'en']


############## FIREBASE ##############

class FcmClient:
    """Sends one message to one device token. The OAuth token is cached and refreshed when it expires."""
    SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'

    def __init__(self, service_account_path: str):
        self.service_account_path = service_account_path
        self._credentials = None
        self._lock = threading.Lock()
        self._warned = False

    @property
    def enabled(self) -> bool:
        if os.path.exists(self.service_account_path):
            return True
        if not self._warned:
            log(f"Push notifications disabled: {self.service_account_path} not found.", level="WARNING")
            self._warned = True
        return False

    def _access_token(self) -> tuple[str, str]:
        with self._lock:
            if self._credentials is None:
                self._credentials = service_account.Credentials.from_service_account_file(
                    self.service_account_path, scopes=[self.SCOPE])
            if not self._credentials.valid:
                self._credentials.refresh(GoogleAuthRequest())
            return self._credentials.token, self._credentials.project_id

    def send(self, token: str, message: dict) -> str:
        """Return 'ok', 'unregistered' (the app was uninstalled or the token expired) or 'error'."""
        access_token, project_id = self._access_token()
        response = requests.post(
            f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send',
            headers={'Authorization': f'Bearer {access_token}'},
            json={'message': {'token': token, **message}},
            timeout=10,
        )
        if response.status_code == 200:
            return 'ok'
        if response.status_code == 404 or 'UNREGISTERED' in response.text:
            return 'unregistered'
        log(f"FCM error {response.status_code}: {response.text[:300]}", level="ERROR")
        return 'error'


fcm = FcmClient(FIREBASE_SERVICE_ACCOUNT_PATH)


def build_message(title: str, body: str, route: str, channel: str, tag: str | None = None) -> dict:
    """FCM message: `route` is the page the app opens when the notification is tapped.

    `channel` and `tag` are also in `data`: when the app is open it shows the notification itself
    (unless that page is on screen), with the same channel and tag.
    """
    android_notification = {'channel_id': channel}
    data = {'route': route, 'channel': channel}
    if tag:
        # A new notification with the same tag replaces the previous one in the tray.
        android_notification['tag'] = tag
        data['tag'] = tag
    return {
        'notification': {'title': title, 'body': body},
        'data': data,
        'android': {'priority': 'high', 'notification': android_notification},
    }


def deliver(pairs: list[tuple[str, dict]]) -> None:
    """Send (token, message) pairs in the background, so no request waits for Firebase."""
    if not pairs or not fcm.enabled:
        return
    socketio.start_background_task(_send_all, current_app._get_current_object(), pairs)


def _send_all(app, pairs: list[tuple[str, dict]]) -> None:
    stale = []
    for token, message in pairs:
        try:
            if fcm.send(token, message) == 'unregistered':
                stale.append(token)
        except Exception as error:  # a network error must not stop the other notifications
            log(f"Push notification failed: {error}", level="ERROR")
    log(f"Push notifications sent: {len(pairs)} device(s), {len(stale)} unregistered", level="INFO")
    if stale:
        with app.app_context():
            PushTokenModel.query.filter(PushTokenModel.token.in_(stale)).delete(synchronize_session=False)
            db.session.commit()


############## RECIPIENTS ##############

def recipients(group_id: int, setting: str, exclude_user_id: int | None = None) -> list[UserModel]:
    """Members of the group with this setting on, both globally and for this group, and an active account."""
    column = SETTINGS_COLUMNS[setting]
    query = (
        UserModel.query
        .join(GroupUser, GroupUser.user_id == UserModel.id)
        .filter(GroupUser.group_id == group_id, getattr(GroupUser, column).is_(True),
                getattr(UserModel, column).is_(True), UserModel.deleted.isnot(True))
    )
    if exclude_user_id is not None:
        query = query.filter(UserModel.id != exclude_user_id)
    return query.all()


def _pairs_for(users: list[UserModel], build) -> list[tuple[str, dict]]:
    """One message per device of each user, built in the user's language by `build(user)`."""
    if not users:
        return []
    by_id = {user.id: user for user in users}
    tokens = PushTokenModel.query.filter(PushTokenModel.user_id.in_(by_id)).all()
    messages = {}
    pairs = []
    for push_token in tokens:
        user = by_id[push_token.user_id]
        if user.id not in messages:
            messages[user.id] = build(user)
        pairs.append((push_token.token, messages[user.id]))
    return pairs


############## THE NOTIFICATIONS ##############

def notify_new_message(message: ChatMessageModel) -> None:
    group = message.group
    sender = message.user
    content = message.content
    is_gif = content.startswith('https://') and 'klipy' in content  # same test as the chat component
    if len(content) > MESSAGE_PREVIEW_LENGTH:
        content = content[:MESSAGE_PREVIEW_LENGTH - 1] + '…'

    def build(user: UserModel) -> dict:
        texts = _texts(user)
        body = texts['gif'] if is_gif else texts['message']
        return build_message(group.name, body.format(user=sender.username, content=content),
                             f'/group/{group.id}', CHANNEL_MESSAGES, tag=f'chat-{group.id}')

    deliver(_pairs_for(recipients(group.id, 'messages', exclude_user_id=sender.id), build))


def notify_new_answer(group: GroupModel, voter: UserModel) -> None:
    """A member answered the question of the day: tell the other members."""
    def build(user: UserModel) -> dict:
        return build_message(group.name, _texts(user)['answer'].format(user=voter.username), f'/group/{group.id}',
                             CHANNEL_ANSWERS, tag=f'answers-{group.id}')

    deliver(_pairs_for(recipients(group.id, 'answers', exclude_user_id=voter.id), build))


def init_notification_markers(group: GroupModel, now: datetime.datetime | None = None) -> None:
    """Mark the current day as already handled, so the scheduler notifies from the next reset on.

    Called when a group is created or its reset time changes (the caller commits): without it, a group
    whose reset comes before the scheduler first sees it would miss that day's notification.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start = current_window_start(group, now)
    group.last_question_notified_at = start
    # No reminder for a day already in its last hour.
    group.last_vote_reminder_at = start if now >= start + DAY - REMINDER_BEFORE_END else start - DAY


def notify_new_questions(now: datetime.datetime | None = None) -> None:
    """At each group's reset time: one notification per new daily window."""
    pairs = []
    for group in GroupModel.query.all():
        start = current_window_start(group, now)
        last = _as_utc(group.last_question_notified_at)
        group.last_question_notified_at = start
        # Group created before init_notification_markers existed: start from the next window.
        if last is None or last >= start:
            continue

        def build(user: UserModel, group=group) -> dict:
            return build_message(group.name, _texts(user)['question'], f'/group/{group.id}',
                                 CHANNEL_QUESTIONS, tag=f'question-{group.id}')

        group_pairs = _pairs_for(recipients(group.id, 'questions'), build)
        log(f"New question notification for group {group.id}: {len(group_pairs)} device(s)", level="INFO")
        pairs += group_pairs
    db.session.commit()
    deliver(pairs)


def _voters_of_window(group: GroupModel, start: datetime.datetime) -> set[int]:
    """Users who voted on the question of the window starting at `start` (none if it wasn't created yet)."""
    question = group.questions.order_by(QuestionModel.date.desc()).first()
    if not question or not start <= _as_utc(question.date) < start + DAY:
        return set()
    return {vote.voterUser_id for vote in question.votes}


def notify_vote_reminders(now: datetime.datetime | None = None) -> None:
    """One hour before the end of each group's day: remind the members who haven't voted."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    pairs = []
    for group in GroupModel.query.all():
        start = current_window_start(group, now)
        in_last_hour = now >= start + DAY - REMINDER_BEFORE_END
        last = _as_utc(group.last_vote_reminder_at)
        if last is None:
            # Group created before init_notification_markers existed: no reminder for a day already in its last hour.
            group.last_vote_reminder_at = start if in_last_hour else start - DAY
            continue
        if not in_last_hour or last >= start:
            continue
        group.last_vote_reminder_at = start
        voters = _voters_of_window(group, start)
        users = [user for user in recipients(group.id, 'vote_reminder') if user.id not in voters]

        def build(user: UserModel, group=group) -> dict:
            return build_message(group.name, _texts(user)['reminder'], f'/group/{group.id}',
                                 CHANNEL_REMINDERS, tag=f'question-{group.id}')

        group_pairs = _pairs_for(users, build)
        log(f"Vote reminder for group {group.id}: {len(group_pairs)} device(s)", level="INFO")
        pairs += group_pairs
    db.session.commit()
    deliver(pairs)


def run_scheduler(app) -> None:
    """Background loop: checks every minute for groups whose new day started or ends within the hour."""
    while True:
        socketio.sleep(SCHEDULER_INTERVAL_SECONDS)
        with app.app_context():
            try:
                notify_new_questions()
                notify_vote_reminders()
            except Exception as error:
                db.session.rollback()
                log(f"Notification scheduler failed: {error}", level="ERROR")
            finally:
                db.session.remove()


def start_scheduler(app) -> None:
    """Needs a single process (like Flask-Limiter's memory storage and Socket.IO rooms)."""
    socketio.start_background_task(run_scheduler, app)
    log(f"Notification scheduler started (every {SCHEDULER_INTERVAL_SECONDS} s)", level="INFO")


############## SETTINGS AND DEVICES (API) ##############

def _current_user() -> UserModel:
    return db.session.get(UserModel, int(current_user.id))


def _switches(row: UserModel | GroupUser) -> dict:
    return {name: bool(getattr(row, column)) for name, column in SETTINGS_COLUMNS.items()}


def _switch_changes(request: Request) -> tuple[dict | None, tuple[dict, int] | None]:
    """The switches sent in the body (any of them), or a 400 response."""
    data = request.get_json(silent=True) or {}
    changes = {name: value for name, value in data.items() if name in SETTINGS_COLUMNS}
    if not changes or not all(isinstance(value, bool) for value in changes.values()):
        return None, ({"success": False, "message": f"Expected booleans among: {', '.join(SETTINGS_COLUMNS)}"}, 400)
    return changes, None


def _apply_switches(row, changes: dict) -> dict:
    """Set the switches that differ on `row` (user or membership); returns only those."""
    changed = {name: value for name, value in changes.items() if getattr(row, SETTINGS_COLUMNS[name]) != value}
    for name, value in changed.items():
        setattr(row, SETTINGS_COLUMNS[name], value)
    return changed


def get_settings() -> tuple[dict, int]:
    """The user's global switches."""
    content = _switches(_current_user())
    return {"success": True, "message": "Notification settings retrieved", "content": content}, 200


def update_settings(request: Request) -> tuple[dict, int]:
    """Save any of the global switches."""
    changes, error = _switch_changes(request)
    if error:
        return error
    user = _current_user()
    changed = _apply_switches(user, changes)
    if not changed:
        return get_settings()  # nothing to write
    result = update_from_db()
    if result.get("error"):
        return result, 500
    log(f"User {user.id} changed their notification settings: {changed}", level="INFO")
    return get_settings()


def _membership(group_id: int) -> GroupUser | None:
    return GroupUser.query.filter_by(user_id=int(current_user.id), group_id=group_id).first()


def get_group_settings(group_id: int) -> tuple[dict, int]:
    """This group's switches, with the global ones (a type off globally is off for every group)."""
    membership = _membership(group_id)
    if not membership:
        return {"success": False, "message": "User is not a member of the group"}, 403
    content = {'group': _switches(membership), 'global': _switches(_current_user())}
    return {"success": True, "message": "Group notification settings retrieved", "content": content}, 200


def update_group_settings(group_id: int, request: Request) -> tuple[dict, int]:
    """Save any of this group's switches."""
    changes, error = _switch_changes(request)
    if error:
        return error
    membership = _membership(group_id)
    if not membership:
        return {"success": False, "message": "User is not a member of the group"}, 403
    changed = _apply_switches(membership, changes)
    if not changed:
        return get_group_settings(group_id)  # nothing to write
    result = update_from_db()
    if result.get("error"):
        return result, 500
    log(f"User {membership.user_id} changed their notification settings for group {group_id}: {changed}", level="INFO")
    return get_group_settings(group_id)


def register_device(request: Request) -> tuple[dict, int]:
    """Save the phone's FCM token for the current user (a token moves to whoever logged in last on it)."""
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    device_id = data.get('device_id')
    platform = data.get('platform', 'android')
    if not isinstance(token, str) or not 0 < len(token) <= 255:
        return {"success": False, "message": "A token is required"}, 400
    if device_id is not None and (not isinstance(device_id, str) or len(device_id) > 64):
        return {"success": False, "message": "Invalid device_id"}, 400
    if platform not in PLATFORMS:
        return {"success": False, "message": f"platform must be one of: {', '.join(sorted(PLATFORMS))}"}, 400

    user_id = int(current_user.id)
    push_token = PushTokenModel.query.filter_by(token=token).first()
    if push_token:
        push_token.user_id, push_token.device_id, push_token.platform = user_id, device_id, platform
    else:
        push_token = PushTokenModel(user_id=user_id, token=token, device_id=device_id, platform=platform)
        db.session.add(push_token)
    if device_id:
        # Firebase sometimes renews a phone's token: forget the old one.
        PushTokenModel.query.filter(PushTokenModel.user_id == user_id, PushTokenModel.device_id == device_id,
                                    PushTokenModel.token != token).delete(synchronize_session=False)
    result = update_from_db()
    if result.get("error"):
        return result, 500
    log(f"User {user_id} registered a {platform} device for push notifications", level="INFO")
    return {"success": True, "message": "Device registered for push notifications"}, 201


def unregister_device(request: Request) -> tuple[dict, int]:
    token = (request.get_json(silent=True) or {}).get('token')
    if not isinstance(token, str) or not token:
        return {"success": False, "message": "A token is required"}, 400
    PushTokenModel.query.filter_by(token=token, user_id=int(current_user.id)).delete(synchronize_session=False)
    result = update_from_db()
    if result.get("error"):
        return result, 500
    log(f"User {current_user.id} unregistered a device from push notifications", level="INFO")
    return {"success": True, "message": "Device unregistered from push notifications"}, 200


def remove_device_tokens(user_id: int, device_id: str | None) -> None:
    """On logout: the phone stops receiving this user's notifications (the caller commits)."""
    if device_id:
        PushTokenModel.query.filter_by(user_id=user_id, device_id=device_id).delete(synchronize_session=False)
