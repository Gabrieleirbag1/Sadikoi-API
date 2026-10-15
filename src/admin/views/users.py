from flask import abort, flash, redirect, request
from flask_admin import expose
from flask_admin.actions import action
from lite_logging.lite_logging import log

from admin.auth import safe_next_url
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
        'profile_picture': '', 'id': 'ID', 'username': 'Pseudo', 'email': 'Email', 'language': 'Langue',
        'date_created': 'Inscription', 'group_count': 'Groupes', 'deleted': 'Statut', 'session_version': 'Version de session',
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
            flash("Jeton CSRF invalide, rechargez la page.", 'error')
            return redirect(back)
        user = db.session.get(UserModel, user_id)
        if user is None:
            abort(404)
        set_user_disabled(user, not user.deleted)
        db.session.commit()
        flash(f"Compte de {user.username} {'désactivé' if user.deleted else 'réactivé'}.", 'success')
        return redirect(back)

    def _set_disabled(self, ids: list[str], disabled: bool) -> None:
        users = UserModel.query.filter(UserModel.id.in_([int(i) for i in ids])).all()
        for user in users:
            set_user_disabled(user, disabled)
        db.session.commit()
        flash(f"{len(users)} compte(s) {'désactivé(s)' if disabled else 'réactivé(s)'}.", 'success')

    @action('disable', 'Désactiver', 'Désactiver les comptes sélectionnés ?')
    def action_disable(self, ids):
        self._set_disabled(ids, True)

    @action('enable', 'Réactiver', 'Réactiver les comptes sélectionnés ?')
    def action_enable(self, ids):
        self._set_disabled(ids, False)
