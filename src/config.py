import os
from lite_logging.lite_logging import log

def load_secret_var(var_name: str, secrets_path: str, default: str = None) -> str:
    """Load a secret variable from the appropriate secrets file.
    
    :param str var_name: The name of the secret variable.
    :param str default: The default value if the variable is not found.

    :return: The value of the secret variable.
    :rtype: str
    """
    if os.path.exists(secrets_path):
        log(f"Found .{var_name.lower()}.secrets file, loading {var_name} from it.", level="DEBUG")
        with open(secrets_path, 'r') as f:
            for line in f:
                if line.startswith(f'{var_name}='):
                    return line.strip().split('=', 1)[1]
    return default

# Load SECRET_KEY
auth_secrets_path = os.path.join(os.path.dirname(__file__), '.auth.secrets')
SECRET_KEY = load_secret_var('SECRET_KEY', auth_secrets_path)

if not SECRET_KEY:
    SECRET_KEY = os.urandom(32).hex()
    log("Generated new secret key.", level="DEBUG")
    with open(auth_secrets_path, 'w') as f:
        f.write(f'SECRET_KEY={SECRET_KEY}')

# Load GOOGLE_CLIENT_BROWSER_ID
google_secrets_path = os.path.join(os.path.dirname(__file__), '.google.secrets')
GOOGLE_CLIENT_BROWSER_ID = load_secret_var('GOOGLE_CLIENT_BROWSER_ID', google_secrets_path)

if not GOOGLE_CLIENT_BROWSER_ID:
    log("GOOGLE_CLIENT_BROWSER_ID not found in .google.secrets file.", level="ERROR")

# Load GOOGLE_CLIENT_MOBILE_ID
GOOGLE_CLIENT_MOBILE_ID = load_secret_var('GOOGLE_CLIENT_MOBILE_ID', google_secrets_path)

if not GOOGLE_CLIENT_MOBILE_ID:
    log("GOOGLE_CLIENT_MOBILE_ID not found in .google.secrets file.", level="ERROR")

# Load FRONTEND_URL (used to build links sent by email)
frontend_secrets_path = os.path.join(os.path.dirname(__file__), '.frontend.secrets')
FRONTEND_URL = load_secret_var('FRONTEND_URL', frontend_secrets_path, default='http://localhost:4200').rstrip('/')

# Load TURNSTILE_SECRET_KEY (Cloudflare Turnstile captcha, verified on login / register)
turnstile_secrets_path = os.path.join(os.path.dirname(__file__), '.turnstile.secrets')
TURNSTILE_SECRET_KEY = load_secret_var('TURNSTILE_SECRET_KEY', turnstile_secrets_path)

if not TURNSTILE_SECRET_KEY:
    log("TURNSTILE_SECRET_KEY not found in .turnstile.secrets file.", level="ERROR")

# Load BREVO_API_KEY (transactional emails: login codes, password resets)
brevo_secrets_path = os.path.join(os.path.dirname(__file__), '.brevo.secrets')
BREVO_API_KEY = load_secret_var('BREVO_API_KEY', brevo_secrets_path)

if not BREVO_API_KEY:
    log("BREVO_API_KEY not found in .brevo.secrets file.", level="ERROR")

# Load KLIPY_API_KEY (GIF search, called by the API only so the key never reaches the browser)
klipy_secrets_path = os.path.join(os.path.dirname(__file__), '.klipy.secrets')
KLIPY_API_KEY = load_secret_var('KLIPY_API_KEY', klipy_secrets_path)

if not KLIPY_API_KEY:
    log("KLIPY_API_KEY not found in .klipy.secrets file.", level="ERROR")

# Sender of every email (must be a verified sender in Brevo)
EMAIL_SENDER_ADDRESS = 'missclick@missclick.net'
EMAIL_SENDER_NAME = 'Sadikoi'


# The local SQLite database (the API names it 'data-local' and runs from the repo root).
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'data-local.db')

ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "https://sadikoi.missclick.net",
    "https://localhost",      # Android
    "capacitor://localhost",  # iOS
]

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_LANGUAGES = {'en', 'fr'}

# Firebase service account key (JSON), used to send push notifications. Without it, nothing is sent.
FIREBASE_SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), '.firebase-service-account.json')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
