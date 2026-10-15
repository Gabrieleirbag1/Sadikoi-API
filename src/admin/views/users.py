from flask import abort, flash, redirect, request
from flask_admin import expose
from flask_admin.actions import action
from lite_logging.lite_logging import log

from admin.auth import safe_next_url
from admin.i18n import lazy, tr
from admin.views.base import CsrfOnlyForm, ProtectedModelView, cell, current_url
from db import db
from models import UserModel


def set_user_disabled(user: UserModel, disabled: bool) -> None:
    """(De)activate an account. `deleted` is the soft-delete flag the API already enforces on every request;
    bumping session_version also invalidates every open session (like auth.set_session_version)."""
    user.deleted = disabled
    user.session_version = (user.session_version or 0) + 1
    log(f"Admin {'disabled' if disabled else 'reactivated'} user {user.id} ({user.username})", level="INFO")


class UserAdminView(ProtectedModelView):
    can_create = False
    can_edit = False
    can_delete = False  # accounts are only ever deactivated

    column_list = ['profile_picture', 'id', 'username', 'email', 'language', 'date_created', 'group_count', 'deleted']
    column_details_list = ['profile_picture', 'id', 'username', 'email', 'language', 'date_created', 'group_count',
                           'session_version', 'deleted']
    column_labels = {
        'profile_picture': '', 'id': 'ID', 'username': lazy('Username'), 'email': lazy('Email'),
        'language': lazy('Language'), 'date_created': lazy('Signed up'), 'group_count': lazy('Groups'),
        'deleted': lazy('Status'), 'session_version': lazy('Session version'),
    }
    column_searchable_list = ['username', 'email']
    column_filters = ['deleted', 'language', 'date_created']
    column_sortable_list = ['id', 'username', 'email', 'language', 'date_created', 'deleted']
    column_default_sort = ('date_created', True)
    column_formatters = {
        'profile_picture': lambda v, c, m, n: cell('avatar', m),
        'group_count': lambda v, c, m, n: m.groups.count(),
        'deleted': lambda v, c, m, n: cell('user_status', m, CsrfOnlyForm().csrf_token, current_url()),
    }

    @expose('/toggle/<int:user_id>/', methods=['POST'])
    def toggle_view(self, user_id: int):
        back = safe_next_url(request.form.get('url'))
        if not CsrfOnlyForm(request.form).validate():
            flash(tr("Invalid CSRF token, reload the page."), 'error')
            return redirect(back)
        user = db.session.get(UserModel, user_id)
        if user is None:
            abort(404)
        set_user_disabled(user, not user.deleted)
        db.session.commit()
        message = "{username}'s account disabled." if user.deleted else "{username}'s account reactivated."
        flash(tr(message, username=user.username), 'success')
        return redirect(back)

    def _set_disabled(self, ids: list[str], disabled: bool) -> None:
        users = UserModel.query.filter(UserModel.id.in_([int(i) for i in ids])).all()
        for user in users:
            set_user_disabled(user, disabled)
        db.session.commit()
        message = "{count} account(s) disabled." if disabled else "{count} account(s) reactivated."
        flash(tr(message, count=len(users)), 'success')

    @action('disable', lazy('Disable'), lazy('Disable the selected accounts?'))
    def action_disable(self, ids):
        self._set_disabled(ids, True)

    @action('enable', lazy('Reactivate'), lazy('Reactivate the selected accounts?'))
    def action_enable(self, ids):
        self._set_disabled(ids, False)
