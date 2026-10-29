"""Run the local admin: `python src/admin` (or `cd src && python -m admin`)."""
import argparse
import os
import sys

# The API modules use flat imports (`from models import ...`): put src/ on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin import DEFAULT_DB_PATH, create_admin_app  # noqa: E402
from lite_logging.lite_logging import log  # noqa: E402

LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sadikoi local admin")
    parser.add_argument('--host', default='127.0.0.1', help="local interface only (127.0.0.1, localhost, ::1)")
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--db', default=DEFAULT_DB_PATH, help="path of the SQLite database")
    args = parser.parse_args()

    if args.host not in LOCAL_HOSTS:
        parser.error("the admin must never be exposed: use 127.0.0.1, localhost or ::1")
    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        parser.error(f"database not found: {db_path} (start the API once to create it)")

    app = create_admin_app({'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}'})
    log(f"Sadikoi admin on http://{args.host}:{args.port}/admin/ (secret in src/.admin.secrets)", level="INFO")
    app.run(host=args.host, port=args.port, debug=os.environ.get('FLASK_DEBUG') == '1')


if __name__ == '__main__':
    main()
