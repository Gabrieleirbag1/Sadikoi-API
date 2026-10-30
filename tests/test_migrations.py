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
        # Added by 0003_push_notifications (and 0005_group_notification_settings).
        connection.execute("DROP TABLE push_tokens")
        for table, column in [("users", "notify_messages"), ("users", "notify_questions"),
                              ("users", "notify_vote_reminder"), ("users", "notify_answers"),
                              ("group_user", "notify_messages"), ("group_user", "notify_questions"),
                              ("group_user", "notify_vote_reminder"), ("group_user", "notify_answers"),
                              ("groups", "last_question_notified_at"), ("groups", "last_vote_reminder_at")]:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        # Added by 0004_item_announcements.
        connection.execute("DROP TABLE item_announcements")
        # Added by 0006_review_account.
        connection.execute("ALTER TABLE users DROP COLUMN skip_device_verification")
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
    manage.run(["--db", str(db_file), "rollback"])  # the latest one: 0006_review_account
    assert "skip_device_verification" not in columns(db_file, "users")
    manage.run(["--db", str(db_file), "rollback"])  # then 0005_group_notification_settings
    assert "notifications_muted" in columns(db_file, "group_user")
    assert "notify_answers" not in columns(db_file, "users")
    manage.run(["--db", str(db_file), "rollback"])  # then 0004_item_announcements
    assert columns(db_file, "item_announcements") == []
    assert "notify_messages" in columns(db_file, "users")
    manage.run(["--db", str(db_file), "rollback"])  # then 0003_push_notifications
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


def test_muted_groups_keep_every_notification_off(db_file):
    """0005_group_notification_settings: notifications_muted becomes one switch per type, and back."""
    manage.run(["--db", str(db_file), "migrate", "0004_item_announcements"])
    with sqlite3.connect(db_file) as connection:
        connection.execute("INSERT INTO users (id, username, email) VALUES (1, 'alice', 'a@example.com')")
        connection.execute("INSERT INTO groups (id, name) VALUES (1, 'muted'), (2, 'loud')")
        connection.execute("INSERT INTO group_user (user_id, group_id, notifications_muted) VALUES (1, 1, 1), (1, 2, 0)")
    manage.run(["--db", str(db_file), "migrate"])
    switches = "notify_messages, notify_questions, notify_vote_reminder, notify_answers"
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute(f"SELECT group_id, {switches} FROM group_user ORDER BY group_id").fetchall()
    assert rows == [(1, 0, 0, 0, 0), (2, 1, 1, 1, 1)]
    manage.run(["--db", str(db_file), "rollback", "0004_item_announcements"])
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute("SELECT group_id, notifications_muted FROM group_user ORDER BY group_id").fetchall()
    assert rows == [(1, 1), (2, 0)]


# ------------------------------------------------------------ review account
REVIEW_PASSWORD = "a-long-review-password"


def review_users(db_file):
    with sqlite3.connect(db_file) as connection:
        return connection.execute(
            "SELECT username, email, password, skip_device_verification, session_version FROM users").fetchall()


@pytest.fixture
def migrated(db_file):
    manage.run(["--db", str(db_file), "migrate"])
    return db_file


def typed(monkeypatch, *answers):
    answers = iter(answers)
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": next(answers))


def test_create_review_account(migrated, monkeypatch):
    typed(monkeypatch, REVIEW_PASSWORD, REVIEW_PASSWORD)
    manage.run(["--db", str(migrated), "create-review-account"])
    [(username, email, password_hash, skip, _)] = review_users(migrated)
    assert (username, email, skip) == ("google_review", "google-review@missclick.net", 1)
    assert REVIEW_PASSWORD not in password_hash
    from werkzeug.security import check_password_hash
    assert check_password_hash(password_hash, REVIEW_PASSWORD)


def test_running_it_again_changes_the_password_and_logs_out(migrated, monkeypatch):
    typed(monkeypatch, REVIEW_PASSWORD, REVIEW_PASSWORD, "another-long-password!", "another-long-password!")
    manage.run(["--db", str(migrated), "create-review-account"])
    manage.run(["--db", str(migrated), "create-review-account"])
    [(_, _, password_hash, _, session_version)] = review_users(migrated)
    from werkzeug.security import check_password_hash
    assert check_password_hash(password_hash, "another-long-password!")
    assert session_version == 1


def test_never_flags_an_existing_normal_account(migrated, monkeypatch):
    with sqlite3.connect(migrated) as connection:
        connection.execute("INSERT INTO users (id, email, username, password) "
                           "VALUES (1, 'google-review@missclick.net', 'squatter', 'x')")
    typed(monkeypatch, REVIEW_PASSWORD, REVIEW_PASSWORD)
    with pytest.raises(SystemExit):
        manage.run(["--db", str(migrated), "create-review-account"])
    assert review_users(migrated) == [("squatter", "google-review@missclick.net", "x", 0, None)]


@pytest.mark.parametrize("answers", [("short", "short"), (REVIEW_PASSWORD, REVIEW_PASSWORD + "!")])
def test_bad_password_creates_nothing(migrated, monkeypatch, answers):
    typed(monkeypatch, *answers)
    with pytest.raises(SystemExit):
        manage.run(["--db", str(migrated), "create-review-account"])
    assert review_users(migrated) == []


def test_requires_an_up_to_date_database(db_file, monkeypatch):
    manage.run(["--db", str(db_file), "migrate", manage.BASELINE_REVISION])
    typed(monkeypatch, REVIEW_PASSWORD, REVIEW_PASSWORD)
    with pytest.raises(SystemExit):
        manage.run(["--db", str(db_file), "create-review-account"])
