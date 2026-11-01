"""Read-only aggregate queries for the admin dashboard. Every function needs an app context."""
import datetime

from collections import Counter

from sqlalchemy import case, func

from admin.i18n import get_locale
from db import db
from models import (
    BugReportModel, ChatMessageModel, GroupModel, GroupUser, QuestionFeedbackModel, QuestionModel, QuestionVote,
    ReportUserModel, SuggestionModel, UserModel,
)
from utils import question_pool, question_themes


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
        "question_likes": count(QuestionFeedbackModel, QuestionFeedbackModel.liked.is_(True)),
        "question_dislikes": count(QuestionFeedbackModel, QuestionFeedbackModel.liked.is_(False)),
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


def theme_counts() -> list[dict]:
    """How many groups selected each theme (their current choice), most selected first.

    Every known theme is listed, even when no group picked it; ids missing from question_themes.json
    (removed themes still saved in a group) are listed with their id as label."""
    counts = Counter(theme for (themes,) in db.session.query(GroupModel.themes) for theme in set(themes or []))
    language = get_locale()
    rows = [{"id": theme_id, "label": theme.get(language) or theme_id, "count": counts.get(theme_id, 0)}
            for theme_id, theme in question_themes.items()]
    rows += [{"id": theme_id, "label": theme_id, "count": n} for theme_id, n in counts.items()
             if theme_id not in question_themes]
    return sorted(rows, key=lambda row: (-row["count"], row["label"].lower()))


def question_text(question_id: int) -> str:
    """The pool question's text in the admin's language (its id if it left the pool)."""
    question = next((q for q in question_pool if q["question_id"] == question_id), None)
    if not question:
        return f"#{question_id}"
    return question["content"].get(get_locale()) or next(iter(question["content"].values()), f"#{question_id}")


def question_ratings(limit: int = 5) -> tuple[list[dict], list[dict]]:
    """Likes and dislikes per pool question (every time it was served counts): (most liked, most disliked)."""
    likes = func.sum(case((QuestionFeedbackModel.liked.is_(True), 1), else_=0))
    dislikes = func.sum(case((QuestionFeedbackModel.liked.is_(False), 1), else_=0))
    rows = [
        {"question_id": question_id, "text": question_text(question_id), "likes": int(n_likes), "dislikes": int(n_dislikes)}
        for question_id, n_likes, n_dislikes in (
            db.session.query(QuestionModel.question_id, likes, dislikes)
            .join(QuestionFeedbackModel, QuestionFeedbackModel.question_id == QuestionModel.id)
            .group_by(QuestionModel.question_id).all()
        )
    ]
    most_liked = sorted((r for r in rows if r["likes"]), key=lambda r: (-r["likes"], r["dislikes"], r["question_id"]))
    most_disliked = sorted((r for r in rows if r["dislikes"]), key=lambda r: (-r["dislikes"], r["likes"], r["question_id"]))
    return most_liked[:limit], most_disliked[:limit]
