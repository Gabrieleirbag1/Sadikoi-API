# Sadikoi API

[![Tests](https://github.com/Gabrieleirbag1/Sadikoi-API/actions/workflows/tests.yml/badge.svg)](https://github.com/Gabrieleirbag1/Sadikoi-API/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.14-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Backend of [Sadikoi](https://sadikoi.missclick.net), a social game for groups of friends.

Every day, each group gets a new question such as *"Who'd be the first to throw up at a party?"*. Members vote for one of their friends, and the most voted player of the day wins an item (Dunce Cap, Leader's Cape, Traitor's Mask...) that they keep until someone else takes it. Each group also has a chat with GIF support.

The web and Android client lives in a separate repository: [Gabrieleirbag1/Sadikoi](https://github.com/Gabrieleirbag1/Sadikoi).

## Features

- Accounts with email/password or Google sign-in, new-device verification by email code, password reset
- Groups with roles (admin / member), invitation links and per-group question themes
- One question per group per day, picked from a pool of 1,300+ questions in English and French
- Votes, daily results and item announcements (new, stolen, kept, with streaks)
- Real-time group chat over Socket.IO, with GIFs through the Klipy API
- Push notifications through Firebase Cloud Messaging: new question, vote reminder one hour before the end of the day, new messages, with per-group settings
- Bug reports, suggestions and user reports
- Rate limiting, Cloudflare Turnstile captcha, restricted CORS
- Local admin interface (Flask-Admin)

## Tech stack

| | |
|---|---|
| Language | Python 3.14 |
| Web framework | Flask 3, Flask-Login, Flask-CORS |
| Real time | Flask-SocketIO |
| Database | SQLite through Flask-SQLAlchemy, migrations with Flask-Migrate (Alembic) |
| Server | Gunicorn, behind Apache in production |
| External services | Google Identity, Brevo (emails), Cloudflare Turnstile, Klipy (GIFs), Firebase Cloud Messaging |
| Tests | pytest, pytest-cov |

## Project structure

```
.
├── src/
│   ├── app.py              # Flask app, routes and Socket.IO events
│   ├── wsgi.py             # Gunicorn entry point
│   ├── manage.py           # Database migration commands
│   ├── config.py           # Settings and secrets loading
│   ├── models.py           # SQLAlchemy models
│   ├── auth.py             # Accounts, sessions, devices
│   ├── group.py            # Groups, roles, invitations
│   ├── question.py         # Daily questions and votes
│   ├── items.py            # Item assignment
│   ├── chat.py, gifs.py    # Group chat and GIF search
│   ├── notifications.py    # Push notifications and scheduler
│   ├── security.py         # Rate limiting and security headers
│   ├── admin/              # Local admin interface
│   └── data/               # Questions, themes and items (JSON)
├── migrations/             # Alembic migrations
├── tests/                  # pytest suite
├── deploy/                 # Example Apache virtual host
├── Dockerfile
└── server_sadikoi.sh       # Docker helper script
```

## Requirements

- Python 3.14
- pip
- Docker (optional, for the container setup)

## Installation

```bash
git clone https://github.com/Gabrieleirbag1/Sadikoi-API.git
cd Sadikoi-API

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For tests and the admin interface, install the development dependencies instead:

```bash
pip install -r requirements-dev.txt
```

## Configuration

Secrets are read from small `KEY=value` files in `src/`. They are all git-ignored.

| File | Key | Used for |
|---|---|---|
| `src/.auth.secrets` | `SECRET_KEY` | Flask session signing. Generated on first start if missing. |
| `src/.google.secrets` | `GOOGLE_CLIENT_BROWSER_ID`, `GOOGLE_CLIENT_MOBILE_ID` | Google sign-in (web and Android client IDs) |
| `src/.turnstile.secrets` | `TURNSTILE_SECRET_KEY` | Captcha on login, register and forgot password |
| `src/.brevo.secrets` | `BREVO_API_KEY` | Transactional emails (login codes, password resets) |
| `src/.klipy.secrets` | `KLIPY_API_KEY` | GIF search |
| `src/.frontend.secrets` | `FRONTEND_URL` | Links sent by email. Defaults to `http://localhost:4200`. |
| `src/.admin.secrets` | `ADMIN_SECRET` | Admin interface login. Generated on first start if missing. |
| `src/.firebase-service-account.json` | | Firebase service account key. Without it, no push notification is sent. |

Example:

```bash
echo "TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA" > src/.turnstile.secrets
```

`1x0000000000000000000000000000000AA` is Cloudflare's test secret: every captcha passes, which is convenient in development.

A missing key is logged as an error at startup, but the API still starts. Only the features that depend on it stop working.

Other settings live in `src/config.py`:

- `ALLOWED_ORIGINS`: allowed CORS and Socket.IO origins
- `EMAIL_SENDER_ADDRESS`, `EMAIL_SENDER_NAME`: email sender (must be a verified sender in Brevo)

Environment variables:

| Variable | Default | Effect |
|---|---|---|
| `DEBUG` | `false` | Print `DEBUG` logs |
| `INFO` | `true` | Print `INFO` logs |
| `FLASK_DEBUG` | unset | `1` enables the Flask debugger. Never set it in production. |

`WARNING`, `ERROR` and `CRITICAL` logs are always printed.

## Database

The schema is managed by migrations. The API does not create tables itself, so run the migrations before the first start and after each pull:

```bash
python src/manage.py migrate
```

The database is stored in `instance/data-local.db`.

| Command | Effect |
|---|---|
| `python src/manage.py migrate` | Apply pending migrations (creates the database if needed) |
| `python src/manage.py makemigrations "add user bio"` | Generate a migration from changes in `models.py` |
| `python src/manage.py rollback` | Undo the last migration |
| `python src/manage.py showmigrations` | Show the migration history and the current revision |
| `python src/manage.py makemigrations --check` | Fail if `models.py` changed without a migration |

All commands accept `--db path/to/file.db`.

Notes:

- Commit the generated migration together with the `models.py` change, and read it before committing. SQLite cannot alter columns, so migrations use batch mode (the table is recreated), and renames are detected as a drop and an add.
- A database created before migrations existed (no `alembic_version` table) is detected on the first `migrate`: it is stamped as `0001_initial` and only later migrations are applied.
- `0001_initial` cannot be rolled back.
- At startup, the API logs an error if migrations are pending.

## Running locally

```bash
python src/manage.py migrate
python src/app.py
```

The API listens on `http://localhost:8082`, and routes are under `/api/`. The Angular dev server (`http://localhost:4200`) is already in the allowed origins.

To run it like in production, with Gunicorn:

```bash
gunicorn -w 1 --threads 100 -b 0.0.0.0:8082 --chdir src wsgi:app
```

Always use a single worker. Rate limits, Socket.IO rooms and the notification scheduler are kept in memory, so they would not be shared between workers.

## Docker

Build the image:

```bash
sudo docker build -t sadikoi-api .
```

Log levels are set at build time:

```bash
sudo docker build --build-arg DEBUG=true --build-arg INFO=true -t sadikoi-api .
```

Secret files in `src/` are copied into the image, so create them before building.

`server_sadikoi.sh` wraps the usual commands:

```bash
./server_sadikoi.sh -m                  # Apply migrations (run once before the first start)
./server_sadikoi.sh                     # Start the container in the background
./server_sadikoi.sh -it                 # Start in the foreground
./server_sadikoi.sh -r                  # Restart
./server_sadikoi.sh -s                  # Stop
./server_sadikoi.sh -m showmigrations   # Any manage.py command
```

The container exposes port `8082`. Two host folders are mounted so data survives restarts:

| Host | Container | Content |
|---|---|---|
| `instance/` | `/app/instance` | SQLite database |
| `src/uploads/` | `/app/src/uploads` | Profile pictures |

They can be moved with the `HOST_INSTANCE_DIR` and `HOST_UPLOADS_DIR` environment variables. Container output is appended to `sadikoi-logs` next to the script (override with `LOG_FILE`).

## Deployment

In production, the API runs on the host behind Apache, which serves the Angular build and proxies `/api/` and Socket.IO to port `8082`. An example virtual host is in [`deploy/apache-sadikoi.conf`](deploy/apache-sadikoi.conf), with TLS, timeouts, request size limits and mod_evasive.

- The API trusts exactly one proxy hop (`ProxyFix`) to read the client IP. Do not expose port `8082` directly.
- The server cannot absorb volumetric DDoS attacks on its own. Put Cloudflare or your host's DDoS filtering in front. With Cloudflare, read the client IP from `CF-Connecting-IP` instead of `X-Forwarded-For`.

## Security

- **Rate limiting**: Flask-Limiter, in memory. Limits are set per route in `src/app.py` with `@limiter.limit`. Requests over the limit get a JSON `429` with a `Retry-After` header.
- **Captcha**: Cloudflare Turnstile on login, register and forgot password.
- **Sessions**: disabling an account or logging out all devices increments `session_version`, which ends every open session immediately.
- **Socket.IO**: only authenticated users can connect, and only group members can join a group room.
- **Debug mode**: off unless `FLASK_DEBUG=1`.

## Admin interface

A Flask-Admin interface for local use only. It shows a dashboard, users (disable / re-enable), suggestions, bug reports, and every table in read-only mode.

```bash
pip install -r requirements-dev.txt
python src/admin
```

Open `http://127.0.0.1:8090/admin/` and log in with `ADMIN_SECRET` from `src/.admin.secrets`. Options: `--port`, `--db path/to/file.db`.

- It runs as a separate process and is never imported by the API.
- It refuses to listen on anything other than `127.0.0.1`, `localhost` or `::1`. Do not put it behind Apache.
- Login is limited to 5 attempts per minute. Changing `ADMIN_SECRET` logs out every admin session.
- Available in English and French (`src/admin/i18n.py`).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                                  # Whole suite
python -m pytest tests/test_chat.py -k expired    # A subset
python -m pytest --cov=src --cov-report=term-missing
```

- The suite runs in about 10 seconds, without network access or real emails.
- Each test uses a temporary SQLite database. `instance/` and `uploads/` are never touched.
- External services (emails, Turnstile, Google, Socket.IO emits) are faked in `tests/conftest.py`.
- Rate limiting is disabled by default. Mark a test with `@pytest.mark.ratelimit` to run it against the real limiter.
- Test data is built with `tests/factories.py` and the `world` fixture.
- `tests/test_migrations.py` checks that migrations produce exactly the schema in `models.py`.
- `tests/test_zz_route_coverage.py` fails if a route has no test, so every new endpoint needs one.

More commands and conventions are in [`tests/README.md`](tests/README.md).

### Continuous integration

GitHub Actions ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)) runs the suite on every pull request and push to `main`. The build fails below 85% coverage. No secret is needed.

## Contributing

1. Create a branch from `main`.
2. If you change `models.py`, generate a migration and commit it with your change.
3. Add tests for new routes and behavior.
4. Run `python -m pytest` before opening a pull request.

## Author

**Gabriel Garrone** ([@Gabrieleirbag1](https://github.com/Gabrieleirbag1))

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
