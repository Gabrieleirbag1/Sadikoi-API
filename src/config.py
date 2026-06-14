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

# Load GOOGLE_CLIENT_ID
google_secrets_path = os.path.join(os.path.dirname(__file__), '.google.secrets')
GOOGLE_CLIENT_ID = load_secret_var('GOOGLE_CLIENT_ID', google_secrets_path)

if not GOOGLE_CLIENT_ID:
    log("GOOGLE_CLIENT_ID not found in .google.secrets file.", level="ERROR")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_LANGUAGES = {'en', 'fr'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS