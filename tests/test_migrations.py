"""migrations/ + src/manage.py: the migrations build the same schema as models.py, and old databases are adopted."""
import sqlite3

import pytest
from flask_migrate import check, upgrade

import manage
from db import db

TABLES = {"users", "groups", "group_user", "bug_reports", "suggestions", "report_users", "chat_messages"}


def columns(db_file, table: str) -> list[str]:
    with sqlite3.connect(db_file) as connection:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "migrations.db"


def migration_app(db_file):
    return manage.create_migration_app(f"sqlite:///{db_file}")


def test_migrations_match_the_models(db_file):
    """Like `makemigrations --check` in CI: fails when models.py changed without a migration."""
    app = migration_app(db_file)
    with app.app_context():
        assert manage.has_pending_migrations()
        upgrade(directory=manage.MIGRATIONS_DIR)
        assert not manage.has_pending_migrations()
        check(directory=manage.MIGRATIONS_DIR)  # sys.exit(1) on any difference
        assert manage.current_revision() == manage.head_revision()


def test_legacy_database_is_adopted(db_file):
    """A database built by db.create_all() before migrations, with data and without the newer columns."""
    app = migration_app(db_file)
    with app.app_context():
        db.create_all()
    with sqlite3.connect(db_file) as connection:
        connection.execute("ALTER TABLE bug_reports DROP COLUMN status")
        # Old report_users, before group_id / message_id (SQLite cannot drop a foreign key column).
        connection.execute("DROP TABLE report_users")
        connection.execute("""CREATE TABLE report_users (
            id INTEGER PRIMARY KEY, reporter_id INTEGER NOT NULL REFERENCES users (id),
            reported_id INTEGER NOT NULL REFERENCES users (id), reason VARCHAR(200) NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""")
        # Added by 0003_push_notifications.
        connection.execute("DROP TABLE push_tokens")
        for table, column in [("users", "notify_messages"), ("users", "notify_questions"),
                              ("users", "notify_vote_reminder"), ("group_user", "notifications_muted"),
                              ("groups", "last_question_notified_at"), ("groups", "last_vote_reminder_at")]:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.execute("INSERT INTO users (id, username, email) VALUES (1, 'alice', 'alice@example.com')")

    manage.run(["--db", str(db_file), "migrate"])

    assert "status" in columns(db_file, "bug_reports")
    assert {"group_id", "message_id"} <= set(columns(db_file, "report_users"))
    with sqlite3.connect(db_file) as connection:
        assert connection.execute("SELECT username FROM users").fetchall() == [("alice",)]
    with app.app_context():
        assert not manage.has_pending_migrations()


def test_fresh_database_is_not_adopted(db_file):
    with migration_app(db_file).app_context():
        assert manage.adopt_legacy_database() is False
        assert manage.current_revision() is None


def test_rollback_then_migrate_again(db_file):
    manage.run(["--db", str(db_file), "migrate"])
    manage.run(["--db", str(db_file), "rollback"])  # the latest one: 0003_push_notifications
    assert "notify_messages" not in columns(db_file, "users")
    assert "status" in columns(db_file, "bug_reports")
    manage.run(["--db", str(db_file), "rollback", manage.BASELINE_REVISION])
    assert "status" not in columns(db_file, "bug_reports")
    manage.run(["--db", str(db_file), "migrate"])
    assert "status" in columns(db_file, "bug_reports")
    assert "notify_messages" in columns(db_file, "users")


def test_the_baseline_cannot_be_rolled_back(db_file):
    manage.run(["--db", str(db_file), "migrate", manage.BASELINE_REVISION])
    with pytest.raises(SystemExit):
        manage.run(["--db", str(db_file), "rollback"])
    with sqlite3.connect(db_file) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= tables


def test_makemigrations_requires_an_up_to_date_database(db_file):
    with pytest.raises(SystemExit):
        manage.run(["--db", str(db_file), "makemigrations", "nothing"])


def test_makemigrations_check_and_showmigrations(db_file):
    manage.run(["--db", str(db_file), "migrate"])
    manage.run(["--db", str(db_file), "makemigrations", "--check"])  # sys.exit(1) if a migration is missing
    manage.run(["--db", str(db_file), "showmigrations"])
    with migration_app(db_file).app_context():
        assert manage.current_revision() == manage.head_revision()
