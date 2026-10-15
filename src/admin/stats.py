"""Read-only aggregate queries for the admin dashboard. Every function needs an app context."""
import datetime

from sqlalchemy import func

from db import db
from models import (
    BugReportModel, ChatMessageModel, GroupModel, GroupUser, QuestionModel, QuestionVote, ReportUserModel,
    SuggestionModel, UserModel,
)


def days_ago(days: int) -> datetime.datetime:
    """Naive UTC cutoff: SQLite stores the timestamps without their offset."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)


def count(model, *criteria) -> int:
    return db.session.query(func.count()).select_from(model).filter(*criteria).scalar() or 0


def get_kpis() -> dict[str, int | float]:
    """Key metrics of the database."""
    week, month = days_ago(7), days_ago(30)
    groups = count(GroupModel)
    memberships = count(GroupUser)
    return {
        "users_total": count(UserModel),
        "users_active": count(UserModel, UserModel.deleted.isnot(True)),
        "users_disabled": count(UserModel, UserModel.deleted.is_(True)),
        "users_new_7d": count(UserModel, UserModel.date_created >= week),
        "users_new_30d": count(UserModel, UserModel.date_created >= month),
        "groups_total": groups,
        "groups_avg_members": round(memberships / groups, 1) if groups else 0,
        "messages_total": count(ChatMessageModel),
        "messages_7d": count(ChatMessageModel, ChatMessageModel.timestamp >= week),
        "questions_total": count(QuestionModel),
        "votes_total": count(QuestionVote),
        "votes_7d": count(QuestionVote, QuestionVote.date >= week),
        "bugs_open": count(BugReportModel, BugReportModel.status == "open"),
        "bugs_in_progress": count(BugReportModel, BugReportModel.status == "in_progress"),
        "bugs_resolved": count(BugReportModel, BugReportModel.status == "resolved"),
        "suggestions_total": count(SuggestionModel),
        "suggestions_7d": count(SuggestionModel, SuggestionModel.timestamp >= week),
        "user_reports_total": count(ReportUserModel),
    }


def latest_users(limit: int = 5) -> list[UserModel]:
    return UserModel.query.order_by(UserModel.date_created.desc()).limit(limit).all()


def latest_open_bugs(limit: int = 5) -> list[BugReportModel]:
    return (BugReportModel.query.filter(BugReportModel.status != "resolved")
            .order_by(BugReportModel.timestamp.desc()).limit(limit).all())


def latest_suggestions(limit: int = 5) -> list[SuggestionModel]:
    return SuggestionModel.query.order_by(SuggestionModel.timestamp.desc()).limit(limit).all()


def top_groups(limit: int = 5) -> list[tuple[GroupModel, int, int]]:
    """Groups with the most chat messages: (group, message count, member count)."""
    messages = (db.session.query(ChatMessageModel.group_id, func.count().label("n"))
                .group_by(ChatMessageModel.group_id).subquery())
    members = (db.session.query(GroupUser.group_id, func.count().label("n"))
               .group_by(GroupUser.group_id).subquery())
    rows = (db.session.query(GroupModel, func.coalesce(messages.c.n, 0), func.coalesce(members.c.n, 0))
            .outerjoin(messages, messages.c.group_id == GroupModel.id)
            .outerjoin(members, members.c.group_id == GroupModel.id)
            .order_by(func.coalesce(messages.c.n, 0).desc(), GroupModel.id)
            .limit(limit).all())
    return [(group, int(n_messages), int(n_members)) for group, n_messages, n_members in rows]
