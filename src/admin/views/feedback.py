from flask import flash
from flask_admin.actions import action
from flask_admin.contrib.sqla.filters import FilterLike

from admin.i18n import lazy, tr
from admin.views.base import ProtectedModelView, cell, user_cell
from db import db
from models import BUG_STATUSES, BugReportModel, UserModel

BUG_STATUS_LABELS = {"open": lazy("Open"), "in_progress": lazy("In progress"), "resolved": lazy("Resolved")}
BUG_STATUS_CHOICES = [(status, BUG_STATUS_LABELS[status]) for status in BUG_STATUSES]

AUTHOR_SEARCH = ['user.username', 'user.email']


def author_filter() -> FilterLike:
    return FilterLike(UserModel.username, lazy('Author'))


class SuggestionAdminView(ProtectedModelView):
    can_create = False
    can_edit = False
    can_delete = True  # moderation

    column_list = ['id', 'user', 'theme', 'question', 'timestamp']
    column_labels = {'id': 'ID', 'user': lazy('Author'), 'theme': lazy('Theme'), 'question': lazy('Question'),
                     'timestamp': lazy('Date')}
    column_searchable_list = ['question', 'theme', *AUTHOR_SEARCH]
    column_filters = ['theme', 'timestamp', author_filter()]
    column_sortable_list = ['id', 'theme', 'timestamp', ('user', 'user.username')]
    column_default_sort = ('timestamp', True)
    column_formatters = {'user': lambda v, c, m, n: user_cell(m.user)}


class BugReportAdminView(ProtectedModelView):
    can_create = False
    can_edit = True  # status only
    can_delete = True

    column_list = ['id', 'title', 'user', 'device_name', 'status', 'timestamp']
    column_details_list = ['id', 'title', 'description', 'user', 'device_name', 'status', 'timestamp']
    column_labels = {'id': 'ID', 'title': lazy('Title'), 'description': lazy('Description'), 'user': lazy('Author'),
                     'device_name': lazy('Device'), 'status': lazy('Status'), 'timestamp': lazy('Date')}
    column_searchable_list = ['title', 'description', *AUTHOR_SEARCH]
    column_filters = ['status', 'timestamp', 'device_name', author_filter()]
    column_sortable_list = ['id', 'title', 'device_name', 'status', 'timestamp', ('user', 'user.username')]
    column_default_sort = ('timestamp', True)
    column_editable_list = ['status']
    column_choices = {'status': BUG_STATUS_CHOICES}
    form_choices = {'status': BUG_STATUS_CHOICES}
    form_columns = ['status']
    column_formatters = {'user': lambda v, c, m, n: user_cell(m.user)}
    column_formatters_detail = {
        'user': lambda v, c, m, n: user_cell(m.user),
        'status': lambda v, c, m, n: cell('bug_status', m.status),
        'description': lambda v, c, m, n: cell('multiline', m.description),
    }

    def _set_status(self, ids: list[str], status: str) -> None:
        reports = BugReportModel.query.filter(BugReportModel.id.in_([int(i) for i in ids])).all()
        for report in reports:
            report.status = status
        db.session.commit()
        flash(tr("{count} report(s) → {status}.", count=len(reports), status=BUG_STATUS_LABELS[status]), 'success')

    @action('mark_open', lazy('Mark as open'))
    def action_mark_open(self, ids):
        self._set_status(ids, 'open')

    @action('mark_in_progress', lazy('Mark as in progress'))
    def action_mark_in_progress(self, ids):
        self._set_status(ids, 'in_progress')

    @action('mark_resolved', lazy('Mark as resolved'))
    def action_mark_resolved(self, ids):
        self._set_status(ids, 'resolved')
