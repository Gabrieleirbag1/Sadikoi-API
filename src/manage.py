"""Database migrations, Django style (Flask-Migrate / Alembic under the hood).

    python src/manage.py makemigrations "add user bio"   # after a change in models.py: writes migrations/versions/xxx.py
    python src/manage.py migrate                         # apply every pending migration
    python src/manage.py migrate <revision>              # upgrade to a given revision
    python src/manage.py rollback [<revision>]           # undo the last migration (or go back to <revision>)
    python src/manage.py showmigrations                  # history + the revision the database is at
    python src/manage.py makemigrations --check          # exit 1 if models.py has changes without a migration

All commands take --db <path of the SQLite file> (default: instance/data-local.db).
"""
import argparse
import os
import sys

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from flask import Flask
from flask_migrate import Migrate, check, current, downgrade, history, migrate, stamp, upgrade
from lite_logging.lite_logging import log
from sqlalchemy import inspect

from config import DEFAULT_DB_PATH
from db import db
import models  # noqa: F401  (registers every table on db.metadata)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
# Schema of the databases created by db.create_all() before migrations existed.
BASELINE_REVISION = '0001_initial'


def create_migration_app(database_uri: str | None = None) -> Flask:
    """Minimal app (no Socket.IO, login or routes): only what Alembic needs."""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri or f'sqlite:///{DEFAULT_DB_PATH}'
    db.init_app(app)
    # SQLite cannot ALTER most things: batch mode rebuilds the table instead.
    Migrate(app, db, directory=MIGRATIONS_DIR, render_as_batch=True, compare_type=True)
    return app


def current_revision() -> str | None:
    """Revision the database is at (needs an app context)."""
    with db.engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str:
    return ScriptDirectory(MIGRATIONS_DIR).get_current_head()


def has_pending_migrations() -> bool:
    return current_revision() != head_revision()


def adopt_legacy_database() -> bool:
    """Like Django's --fake-initial: a database built by db.create_all() has the tables but no
    alembic_version. Mark it as being at the baseline so only the later migrations run on it."""
    tables = set(inspect(db.engine).get_table_names())
    if 'users' in tables and 'alembic_version' not in tables:
        stamp(directory=MIGRATIONS_DIR, revision=BASELINE_REVISION)
        log(f"Existing database without migration history: marked as {BASELINE_REVISION}.", level="INFO")
        return True
    return False


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog='python src/manage.py', description="Sadikoi database migrations")
    parser.add_argument('--db', default=DEFAULT_DB_PATH, help="path of the SQLite database")
    commands = parser.add_subparsers(dest='command', required=True)

    make = commands.add_parser('makemigrations', help="generate a migration from the changes in models.py")
    make.add_argument('message', nargs='?', default='auto', help="short description, used in the file name")
    make.add_argument('--check', action='store_true', help="only check: exit 1 if a migration is missing")
    up = commands.add_parser('migrate', help="apply the pending migrations")
    up.add_argument('revision', nargs='?', default='head')
    down = commands.add_parser('rollback', help="undo migrations")
    down.add_argument('revision', nargs='?', default='-1', help="target revision (default: the previous one)")
    commands.add_parser('showmigrations', help="list the migrations and the current revision")

    args = parser.parse_args(argv)
    app = create_migration_app(f'sqlite:///{os.path.abspath(args.db)}')
    with app.app_context():
        adopt_legacy_database()
        if args.command == 'makemigrations':
            if args.check:
                check(directory=MIGRATIONS_DIR)
            else:
                if has_pending_migrations():
                    sys.exit("The database is not up to date: run `python src/manage.py migrate` first.")
                migrate(directory=MIGRATIONS_DIR, message=args.message)
        elif args.command == 'migrate':
            upgrade(directory=MIGRATIONS_DIR, revision=args.revision)
        elif args.command == 'rollback':
            downgrade(directory=MIGRATIONS_DIR, revision=args.revision)
        else:
            history(directory=MIGRATIONS_DIR, indicate_current=True)
            current(directory=MIGRATIONS_DIR)


if __name__ == '__main__':
    run()
