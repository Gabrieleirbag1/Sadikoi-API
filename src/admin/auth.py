import hashlib
import hmac
import os
import secrets
from urllib.parse import urlparse

from flask import current_app, flash, redirect, request, session, url_for
from flask_admin import BaseView, expose
from flask_admin.form import SecureForm
from lite_logging.lite_logging import log
from wtforms import PasswordField
from wtforms.validators import DataRequired

from admin.i18n import LANGUAGES, lazy, tr
from config import load_secret_var
from security import SocketRateLimiter

ADMIN_SECRETS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.admin.secrets')
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60


def load_admin_secret(secrets_path: str = ADMIN_SECRETS_PATH) -> str:
    """Load ADMIN_SECRET from `secrets_path`, generating and saving a new one if it is missing.

    :param str secrets_path: The secrets file (gitignored, like every *.secrets file).

    :return: The admin secret.
    :rtype: str
    """
    secret = load_secret_var('ADMIN_SECRET', secrets_path)
    if not secret:
        secret = secrets.token_urlsafe(24)
        with open(secrets_path, 'w') as f:
            f.write(f'ADMIN_SECRET={secret}')
        log(f"Generated a new admin secret in {secrets_path}", level="INFO")
    return secret


def secret_fingerprint(secret: str) -> str:
    """Short hash of the secret stored in the session: changing the secret logs everybody out."""
    return hashlib.sha256(f"admin-session:{secret}".encode()).hexdigest()[:16]


def is_admin_authenticated() -> bool:
    expected = secret_fingerprint(current_app.config['ADMIN_SECRET'])
    return hmac.compare_digest(session.get('admin_fp', ''), expected)


def safe_next_url(target: str | None) -> str:
    """Only allow redirects to a path of this app (no open redirect)."""
    fallback = url_for('admin.index')
    if not target:
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/'):
        return fallback
    return target


class SecretProtectedMixin:
    """Flask-Admin views mixing this in are only reachable after the local secret was entered."""

    def is_accessible(self) -> bool:
        return is_admin_authenticated()

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login.index', next=request.full_path.rstrip('?')))


class LoginForm(SecureForm):
    secret = PasswordField(lazy('Admin secret'), validators=[DataRequired()])


def reset_session() -> None:
    """Clear the session but keep the chosen language."""
    language = session.get('admin_lang')
    session.clear()
    if language:
        session['admin_lang'] = language


class LoginView(BaseView):
    """Hidden view: asks for the local admin secret."""

    def is_visible(self) -> bool:
        return False

    @expose('/', methods=['GET', 'POST'])
    def index(self):
        form = LoginForm(request.form)
        status = 200
        if request.method == 'POST':
            limiter: SocketRateLimiter = current_app.extensions['admin_login_limiter']
            if not limiter.allow(request.remote_addr or 'local'):
                flash(tr("Too many attempts. Try again in a minute."), 'error')
                status = 429
            elif form.validate() and hmac.compare_digest(form.secret.data.encode(), current_app.config['ADMIN_SECRET'].encode()):
                reset_session()
                session['admin_fp'] = secret_fingerprint(current_app.config['ADMIN_SECRET'])
                log(f"Admin logged in from {request.remote_addr}", level="INFO")
                return redirect(safe_next_url(request.args.get('next')))
            else:
                log(f"Failed admin login from {request.remote_addr}", level="WARNING")
                flash(tr("Invalid secret."), 'error')
                status = 401
        return self.render('admin/login.html', form=form), status

    @expose('/logout/')
    def logout(self):
        reset_session()
        log("Admin logged out", level="INFO")
        return redirect(url_for('login.index'))

    @expose('/language/<language>/')
    def language(self, language: str):
        """Language switch of the navbar (reachable before login, like the login page)."""
        if language in LANGUAGES:
            session['admin_lang'] = language
        return redirect(safe_next_url(request.args.get('next')))
