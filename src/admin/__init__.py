"""Local-only administration app (Flask-Admin). Never imported by the API: run it with `python src/admin`."""
import hashlib
import os

from flask import Flask, redirect, url_for
from flask_admin import Admin
from flask_admin.theme import Bootstrap4Theme
from flask_babel import Babel

from config import SECRET_KEY
from db import db, upgrade_schema
from models import BugReportModel, SuggestionModel, UserModel
from security import SocketRateLimiter

from admin.auth import LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS, LoginView, is_admin_authenticated, load_admin_secret
from admin.i18n import LANGUAGES, format_date, get_locale, lazy, tr
from admin.views.dashboard import DashboardView
from admin.views.database import register_database_views
from admin.views.feedback import BugReportAdminView, SuggestionAdminView
from admin.views.users import UserAdminView

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(os.path.dirname(SRC_DIR), 'instance', 'data-local.db')


def create_admin_app(config: dict | None = None) -> Flask:
    """Build the admin app. `config` overrides the defaults (ADMIN_SECRET, SQLALCHEMY_DATABASE_URI, UPLOAD_FOLDER...)."""
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{DEFAULT_DB_PATH}',
        UPLOAD_FOLDER=os.path.join(SRC_DIR, 'uploads'),
        # Cookies of localhost are shared by every port: don't collide with the API's `session` cookie.
        SESSION_COOKIE_NAME='sadikoi_admin_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
    )
    app.config.update(config or {})
    if not app.config.get('ADMIN_SECRET'):
        app.config['ADMIN_SECRET'] = load_admin_secret()
    # Stable across restarts, but distinct from the key signing the API sessions.
    app.secret_key = hashlib.sha256(f"admin:{SECRET_KEY}".encode()).hexdigest()
    app.extensions['admin_login_limiter'] = SocketRateLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)
    app.jinja_env.globals.update(is_admin_authenticated=is_admin_authenticated, tr=tr, get_locale=get_locale,
                                 languages=LANGUAGES)
    app.jinja_env.filters['local_date'] = format_date
    Babel(app, locale_selector=get_locale)  # Flask-Admin's own labels (filters, actions, pager) follow the switch

    db.init_app(app)
    with app.app_context():
        upgrade_schema()

    admin = Admin(
        app,
        name='Sadikoi Admin',
        theme=Bootstrap4Theme(swatch='flatly', fluid=True, base_template='admin/sadikoi_base.html'),
        index_view=DashboardView(name=lazy('Dashboard'), url='/admin', menu_icon_type='fa', menu_icon_value='fa-tachometer'),
    )
    admin.add_view(UserAdminView(UserModel, db.session, name=lazy('Users'), endpoint='users', url='/admin/users',
                                 menu_icon_type='fa', menu_icon_value='fa-users'))
    admin.add_view(SuggestionAdminView(SuggestionModel, db.session, name=lazy('Suggestions'), endpoint='suggestions',
                                       url='/admin/suggestions', menu_icon_type='fa', menu_icon_value='fa-lightbulb-o'))
    admin.add_view(BugReportAdminView(BugReportModel, db.session, name=lazy('Bugs'), endpoint='bugs', url='/admin/bugs',
                                      menu_icon_type='fa', menu_icon_value='fa-bug'))
    register_database_views(admin)
    admin.add_view(LoginView(name=lazy('Login'), endpoint='login', url='/admin/login'))

    @app.route('/')
    def root():
        return redirect(url_for('admin.index'))

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    return app
