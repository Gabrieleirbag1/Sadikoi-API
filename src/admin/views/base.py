from flask import get_template_attribute, request
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import SecureForm
from markupsafe import Markup

from admin.auth import SecretProtectedMixin
from models import UserModel


class ProtectedModelView(SecretProtectedMixin, ModelView):
    """Every admin model view: secret-protected, CSRF on all forms (edit, delete, bulk actions, inline edit)."""
    form_base_class = SecureForm
    page_size = 50
    can_set_page_size = True
    can_view_details = True


class CsrfOnlyForm(SecureForm):
    """Field-less form, only used to carry / check the CSRF token of custom POST endpoints."""


def cell(macro_name: str, *args) -> Markup:
    """Render a macro of admin/_cells.html (formatters are plain Python callables)."""
    return get_template_attribute('admin/_cells.html', macro_name)(*args)


def user_cell(user: UserModel | None) -> Markup:
    return cell('user_cell', user)


def current_url() -> str:
    return request.full_path.rstrip('?')
