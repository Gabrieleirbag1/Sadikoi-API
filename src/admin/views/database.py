"""Django-admin-like browser of every table, read-only (flip `can_edit` / `can_delete` on a view to allow writes)."""
from flask_admin import Admin
from sqlalchemy import Boolean, Date, DateTime, Integer, String, Time, inspect

from admin.i18n import lazy
from admin.views.base import ProtectedModelView
from db import db
from models import (
    BugReportModel, ChatMessageModel, GroupInvitationModel, GroupModel, GroupUser, ItemModel, PasswordResetToken,
    QuestionModel, QuestionVote, QuestionVoteTarget, ReportUserModel, SuggestionModel, UserModel, UserSecurity,
)

DATABASE_MODELS = [
    UserModel, UserSecurity, PasswordResetToken, GroupModel, GroupUser, GroupInvitationModel, ChatMessageModel,
    QuestionModel, QuestionVote, QuestionVoteTarget, ItemModel, SuggestionModel, BugReportModel, ReportUserModel,
]
# Secrets or credentials: never displayed, not even hashed.
SENSITIVE_COLUMNS = {'password', 'token_hash', 'auth_code', 'token'}
FILTERABLE_TYPES = (String, Integer, Boolean, DateTime, Date, Time)


class ReadOnlyModelView(ProtectedModelView):
    can_create = False
    can_edit = False
    can_delete = False
    column_display_pk = True

    def __init__(self, model, *args, **kwargs):
        columns = [attr for attr in inspect(model).column_attrs if attr.key not in SENSITIVE_COLUMNS]
        # Every column, foreign keys included (Flask-Admin hides them by default).
        self.column_list = [attr.key for attr in columns]
        self.column_details_list = self.column_list
        self.column_searchable_list = [a.key for a in columns if isinstance(a.columns[0].type, String)]
        self.column_filters = [a.key for a in columns if isinstance(a.columns[0].type, FILTERABLE_TYPES)]
        super().__init__(model, *args, **kwargs)


def register_database_views(admin: Admin) -> None:
    for model in DATABASE_MODELS:
        table = model.__tablename__
        admin.add_view(ReadOnlyModelView(model, db.session, name=table, endpoint=f'db_{table}',
                                         url=f'/admin/db/{table}', category=lazy('Database')))
