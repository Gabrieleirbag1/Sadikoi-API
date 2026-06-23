import os.path
import base64
from lite_logging.lite_logging import log
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
AUTH_CODE_TTL_MINUTES = 10

def get_gmail_service():
    creds = None
    if os.path.exists(os.path.join(os.path.dirname(__file__), "token.json")):
        creds = Credentials.from_authorized_user_file(os.path.join(os.path.dirname(__file__), "token.json"), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                os.path.join(os.path.dirname(__file__), "credentials.json"), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(os.path.join(os.path.dirname(__file__), "token.json"), "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def send_email(destinataire, email_subject, email_content):
    try:
        service = get_gmail_service()

        message = EmailMessage()
        message.set_content(email_content)
        message["To"] = destinataire
        message["From"] = "me"
        message["Subject"] = email_subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}

        send_message = (
            service.users()
            .messages()
            .send(userId="me", body=create_message)
            .execute()
        )
        log(f'Email envoyé avec succès à {destinataire} ! ID: {send_message["id"]}', level="INFO")

    except HttpError as error:
        log(f"Erreur lors de l'envoi : {error}", level="ERROR")

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

if __name__ == "__main__":
    send_email(
        destinataire="karimtufaistoujourslecon@gmail.com",
        email_subject="Salut !",
        email_content="Ceci est un message personnalisé envoyé automatiquement."
    )