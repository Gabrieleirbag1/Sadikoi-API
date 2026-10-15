from flask import current_app, send_from_directory
from flask_admin import AdminIndexView, expose

from admin import stats
from admin.auth import SecretProtectedMixin


class DashboardView(SecretProtectedMixin, AdminIndexView):
    """Home page: key metrics and the latest activity."""

    @expose('/')
    def index(self):
        return self.render(
            'admin/dashboard.html',
            kpis=stats.get_kpis(),
            latest_users=stats.latest_users(),
            latest_bugs=stats.latest_open_bugs(),
            latest_suggestions=stats.latest_suggestions(),
            top_groups=stats.top_groups(),
        )

    @expose('/uploads/<path:filename>')
    def uploads(self, filename):
        """Profile pictures (the API serves them too, but from another app / port)."""
        return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
