"""English / French for the admin. Our strings are written in English and looked up in FR;
Flask-Admin's own labels (filters, pager, actions...) come from its catalogs through Flask-Babel."""
import datetime

from flask import has_request_context, request, session
from flask_babel import LazyString

LANGUAGES = {'en': 'EN', 'fr': 'FR'}
DEFAULT_LANGUAGE = 'fr'

FR = {
    # navigation / auth
    "Dashboard": "Tableau de bord",
    "Users": "Utilisateurs",
    "Suggestions": "Suggestions",
    "Bugs": "Bugs",
    "Database": "Base de données",
    "Login": "Connexion",
    "Logout": "Déconnexion",
    "Language": "Langue",
    "Admin secret": "Secret admin",
    "Admin access": "Accès administrateur",
    "Enter the local secret": "Entrez le secret local",
    "Sign in": "Se connecter",
    "Too many attempts. Try again in a minute.": "Trop de tentatives. Réessayez dans une minute.",
    "Invalid secret.": "Secret invalide.",
    "Invalid CSRF token, reload the page.": "Jeton CSRF invalide, rechargez la page.",
    # users
    "Username": "Pseudo",
    "Email": "Email",
    "Signed up": "Inscription",
    "Groups": "Groupes",
    "Status": "Statut",
    "Session version": "Version de session",
    "Active": "Actif",
    "Disabled": "Désactivé",
    "disabled": "désactivé",
    "Disable": "Désactiver",
    "Reactivate": "Réactiver",
    "Disable {username}'s account?": "Désactiver le compte de {username} ?",
    "Disable the selected accounts?": "Désactiver les comptes sélectionnés ?",
    "Reactivate the selected accounts?": "Réactiver les comptes sélectionnés ?",
    "{username}'s account disabled.": "Compte de {username} désactivé.",
    "{username}'s account reactivated.": "Compte de {username} réactivé.",
    "{count} account(s) disabled.": "{count} compte(s) désactivé(s).",
    "{count} account(s) reactivated.": "{count} compte(s) réactivé(s).",
    "Deleted user": "Utilisateur supprimé",
    # feedback
    "Author": "Auteur",
    "Theme": "Thème",
    "Question": "Question",
    "Date": "Date",
    "Title": "Titre",
    "Description": "Description",
    "Device": "Appareil",
    "Open": "Ouvert",
    "In progress": "En cours",
    "Resolved": "Résolu",
    "Mark as open": "Marquer ouvert",
    "Mark as in progress": "Marquer en cours",
    "Mark as resolved": "Marquer résolu",
    "{count} report(s) → {status}.": "{count} rapport(s) → {status}.",
    # dashboard
    "Active users": "Utilisateurs actifs",
    "{disabled} disabled · +{week} in 7 d · +{month} in 30 d": "{disabled} désactivé(s) · +{week} sur 7 j · +{month} sur 30 j",
    "{avg} members on average": "{avg} membres en moyenne",
    "Messages": "Messages",
    "+{count} in 7 d": "+{count} sur 7 j",
    "Votes": "Votes",
    "+{week} in 7 d · {questions} questions served": "+{week} sur 7 j · {questions} questions servies",
    "Open bugs": "Bugs ouverts",
    "{in_progress} in progress · {resolved} resolved": "{in_progress} en cours · {resolved} résolu(s)",
    "User reports": "Signalements",
    "reported users": "utilisateurs signalés",
    "Accounts": "Comptes",
    "total in database": "total en base",
    "Unresolved bugs": "Bugs non résolus",
    "See all": "Tout voir",
    "No open bug 🎉": "Aucun bug ouvert 🎉",
    "Latest suggestions": "Dernières suggestions",
    "No suggestion.": "Aucune suggestion.",
    "Latest sign-ups": "Derniers inscrits",
    "No user.": "Aucun utilisateur.",
    "Most active groups": "Groupes les plus actifs",
    "{members} members · {messages} messages": "{members} membres · {messages} messages",
    "No group.": "Aucun groupe.",
}
CATALOGS = {'fr': FR}
DATE_FORMATS = {'en': ('%Y-%m-%d', '%Y-%m-%d %H:%M'), 'fr': ('%d/%m/%Y', '%d/%m/%Y %H:%M')}


def get_locale() -> str:
    """The language picked in the navbar, else the browser's, else DEFAULT_LANGUAGE."""
    if has_request_context():
        language = session.get('admin_lang') or request.accept_languages.best_match(LANGUAGES)
        if language in LANGUAGES:
            return language
    return DEFAULT_LANGUAGE


def tr(text: str, **values) -> str:
    """Translate `text` (English source) into the current language, then fill its {placeholders}."""
    text = CATALOGS.get(get_locale(), {}).get(text, text)
    return text.format(**values) if values else text


def lazy(text: str) -> LazyString:
    """`tr` evaluated at render time: for class attributes (labels, view names, actions)."""
    return LazyString(tr, text)


def format_date(value: datetime.datetime | None, with_time: bool = False) -> str:
    if value is None:
        return ''
    return value.strftime(DATE_FORMATS[get_locale()][with_time])
