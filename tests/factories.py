"""Plain-data factories: every helper returns light dataclasses (ids / names), never ORM objects,
so tests are not tied to a live SQLAlchemy session."""
import datetime
import secrets
from dataclasses import dataclass, field

from werkzeug.security import generate_password_hash

from db import db
from models import (
    ChatMessageModel, GroupInvitationModel, GroupModel, GroupUser, ItemModel, QuestionModel,
    QuestionVote, QuestionVoteTarget, UserModel, UserSecurity,
)

PASSWORD = "Passw0rd!"
# Fast hash: the production code uses pbkdf2 with the default (slow) iteration count.
_PASSWORD_HASH = generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class U:
    id: int
    username: str
    email: str
    device_id: str
    password: str = PASSWORD


@dataclass
class G:
    id: int
    name: str
    admin: U | None = None
    members: list[U] = field(default_factory=list)


@dataclass
class Q:
    id: int
    group_id: int
    date: datetime.datetime


def make_user(username: str, *, email: str | None = None, device_authorized: bool = True, deleted: bool = False,
              language: str = "en", last_login_days_ago: int = 0) -> U:
    user = UserModel(username=username, email=email or f"{username}@example.com", password=_PASSWORD_HASH,
                     language=language, deleted=deleted)
    db.session.add(user)
    db.session.flush()
    device_id = f"dev-{username}"
    db.session.add(UserSecurity(
        user_id=user.id, device_id=device_id, device_name="pytest", ip_address="127.0.0.1",
        authorized=device_authorized, last_login=now() - datetime.timedelta(days=last_login_days_ago),
    ))
    db.session.commit()
    return U(id=user.id, username=username, email=user.email, device_id=device_id)


def make_group(admin: U, members: list[U] | None = None, *, name: str = "Team", themes: list[str] | None = None,
               reset: str = "00:00") -> G:
    group = GroupModel(name=name, description="desc", themes=themes or ["connerie", "style"],
                       daily_reset_timestamp=datetime.datetime.strptime(reset, "%H:%M").time())
    db.session.add(group)
    db.session.flush()
    db.session.add(GroupUser(user_id=admin.id, group_id=group.id, role="admin"))
    for member in members or []:
        db.session.add(GroupUser(user_id=member.id, group_id=group.id, role="member"))
    db.session.commit()
    return G(id=group.id, name=name, admin=admin, members=[admin, *(members or [])])


def latest_reset(group_id: int) -> datetime.datetime:
    """The start of the group's current "day" (same formula as builder.build_question_model)."""
    group = db.session.get(GroupModel, group_id)
    current = now()
    reset = datetime.datetime.combine(current.date(), group.daily_reset_timestamp, tzinfo=datetime.timezone.utc)
    return reset if current >= reset else reset - datetime.timedelta(days=1)


def make_question(group: G, *, days_ago: int = 0, question_id: int = 1, theme: str = "connerie",
                  can_write: bool = False, self_vote: bool = True, multiple: bool = False, limit: int = 1,
                  item_name: str = "bonnet_honte") -> Q:
    date = latest_reset(group.id) - datetime.timedelta(days=days_ago)
    question = QuestionModel(question_id=question_id, date=date, theme=theme, enableSelfVote=self_vote,
                             enableMultipleVoting=multiple, voteNumberLimit=limit, canWrite=can_write,
                             item_name=item_name, group_id=group.id)
    db.session.add(question)
    db.session.commit()
    return Q(id=question.id, group_id=group.id, date=date)


def make_vote(question: Q, voter: U, targets: list[U] | None = None, written_answer: str | None = None) -> int:
    vote = QuestionVote(date=question.date, voterUser_id=voter.id, question_id=question.id,
                        group_id=question.group_id, written_answer=written_answer)
    db.session.add(vote)
    db.session.flush()
    for target in targets or []:
        db.session.add(QuestionVoteTarget(vote_id=vote.id, votedUser_id=target.id))
    db.session.commit()
    return vote.id


def make_message(group: G, user: U, content: str = "hello", *, at: datetime.datetime | None = None) -> int:
    message = ChatMessageModel(content=content, user_id=user.id, group_id=group.id, timestamp=at or now())
    db.session.add(message)
    db.session.commit()
    return message.id


def make_invitation(group: G, *, expired: bool = False) -> str:
    token = secrets.token_urlsafe(12)
    delta = datetime.timedelta(hours=-1 if expired else 1)
    db.session.add(GroupInvitationModel(group_id=group.id, token=token, expiration_date=now() + delta))
    db.session.commit()
    return token


def make_item(user: U, group: G, item_name: str = "bonnet_honte", *, acquired_days_ago: int = 3) -> int:
    item = ItemModel(user_id=user.id, group_id=group.id, item_name=item_name,
                     acquired_at=now() - datetime.timedelta(days=acquired_days_ago))
    db.session.add(item)
    db.session.commit()
    return item.id
