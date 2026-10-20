import requests
from lite_logging.lite_logging import log

from config import BREVO_API_KEY, EMAIL_SENDER_ADDRESS, EMAIL_SENDER_NAME

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_SECONDS = 10
AUTH_CODE_TTL_MINUTES = 10
RESET_TOKEN_TTL_MINUTES = 15

def send_email(destinataire, email_subject, email_content):
    """Send a plain-text email through Brevo's transactional API.

    Errors are logged, never raised: a failed email must not break the request that triggered it.

    :return: True if Brevo accepted the email.
    :rtype: bool
    """
    if not BREVO_API_KEY:
        log(f"Email non envoyé à {destinataire} : BREVO_API_KEY manquant.", level="ERROR")
        return False

    payload = {
        "sender": {"name": EMAIL_SENDER_NAME, "email": EMAIL_SENDER_ADDRESS},
        "to": [{"email": destinataire}],
        "subject": email_subject,
        "textContent": email_content,
    }
    headers = {
        "api-key": BREVO_API_KEY,
        "accept": "application/json",
        "content-type": "application/json",
    }

    try:
        response = requests.post(BREVO_SEND_URL, json=payload, headers=headers, timeout=BREVO_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        log(f"Erreur lors de l'envoi à {destinataire} : {error}", level="ERROR")
        return False

    if not response.ok:
        log(f"Erreur Brevo lors de l'envoi à {destinataire} ({response.status_code}) : {response.text}", level="ERROR")
        return False

    message_id = response.json().get("messageId")
    log(f"Email envoyé avec succès à {destinataire} ! ID: {message_id}", level="INFO")
    return True

def send_auth_code_email(user, device, code, language='en'):
    if language == 'fr':
        email_subject = "Code de vérification pour votre connexion"
        email_content = (
                f"Bonjour {user.username},\n\n"
                f"Une tentative de connexion a été détectée depuis un nouvel appareil "
                f"({device.device_name}, IP: {device.ip_address}).\n\n"
                f"Votre code de vérification est : {code}\n\n"
                f"Ce code expire dans {AUTH_CODE_TTL_MINUTES} minutes.\n\n"
                f"Si vous n'êtes pas à l'origine de cette tentative, changez votre mot de passe immédiatement."
            )
    else:
        email_subject = "Verification Code for Your Login"
        email_content = (
                f"Hello {user.username},\n\n"
                f"A login attempt was detected from a new device "
                f"({device.device_name}, IP: {device.ip_address}).\n\n"
                f"Your verification code is: {code}\n\n"
                f"This code will expire in {AUTH_CODE_TTL_MINUTES} minutes.\n\n"
                f"If this wasn't you, please change your password immediately."
            )
    send_email(
        destinataire=user.email,
        email_subject=email_subject,
        email_content=email_content,
    )

def send_password_reset_email(user, reset_url, language='en'):
    if language == 'fr':
        email_subject = "Réinitialisation de votre mot de passe"
        email_content = (
                f"Bonjour {user.username},\n\n"
                f"Une demande de réinitialisation de mot de passe a été effectuée pour votre compte.\n\n"
                f"Cliquez sur ce lien pour choisir un nouveau mot de passe : {reset_url}\n\n"
                f"Ce lien expire dans {RESET_TOKEN_TTL_MINUTES} minutes et ne peut être utilisé qu'une seule fois.\n\n"
                f"Si vous n'êtes pas à l'origine de cette demande, ignorez simplement cet email."
            )
    else:
        email_subject = "Reset Your Password"
        email_content = (
                f"Hello {user.username},\n\n"
                f"A password reset was requested for your account.\n\n"
                f"Click this link to choose a new password: {reset_url}\n\n"
                f"This link expires in {RESET_TOKEN_TTL_MINUTES} minutes and can only be used once.\n\n"
                f"If you didn't request this, you can safely ignore this email."
            )
    send_email(
        destinataire=user.email,
        email_subject=email_subject,
        email_content=email_content,
    )

if __name__ == "__main__":
    # Manual check: python src/email_sender.py someone@example.com
    import sys

    if len(sys.argv) != 2:
        sys.exit("Usage: python src/email_sender.py <destinataire>")
    send_email(
        destinataire=sys.argv[1],
        email_subject="Test Sadikoi",
        email_content="Ceci est un email de test envoyé via Brevo.",
    )
