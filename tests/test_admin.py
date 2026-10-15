"""Local admin app (src/admin): secret login, dashboard, users, suggestions, bug reports, database browser."""
import re
import sys

import pytest
from sqlalchemy import text

from admin import create_admin_app, stats
from admin import __main__ as admin_main
from admin.auth import load_admin_secret
from admin.views.database import DATABASE_MODELS
from db import db, upgrade_schema
from models import BugReportModel, SuggestionModel, UserModel
from tests import factories

SECRET = "admin-test-secret"
CSRF_RE = re.compile(r'name="csrf_token" type="hidden" value="([^"]+)"')


@pytest.fixture(scope="session")
def admin_app(app):
    """The admin app, on the same throw-away database as the API app."""
    return create_admin_app({
        "TESTING": True,
        "ADMIN_SECRET": SECRET,
        "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
        "UPLOAD_FOLDER": app.config["UPLOAD_FOLDER"],
    })


@pytest.fixture
def anon_admin(admin_app):
    admin_app.extensions["admin_login_limiter"]._hits.clear()
    return admin_app.test_client()


def csrf(client, url: str) -> str:
    return CSRF_RE.search(client.get(url).text).group(1)


def login(client, secret: str = SECRET, next_url: str | None = None):
    query = f"?next={next_url}" if next_url else ""
    return client.post(f"/admin/login/{query}", data={"csrf_token": csrf(client, "/admin/login/"), "secret": secret})


@pytest.fixture
def admin(anon_admin):
    assert login(anon_admin).status_code == 302
    return anon_admin


class TestAuth:
    @pytest.mark.parametrize("url", ["/admin/", "/admin/users/", "/admin/bugs/", "/admin/db/users/"])
    def test_pages_require_the_secret(self, anon_admin, url):
        response = anon_admin.get(url)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/admin/login/?next=")

    def test_root_redirects_to_dashboard(self, anon_admin):
        assert anon_admin.get("/").headers["Location"] == "/admin/"

    def test_wrong_secret(self, anon_admin):
        response = login(anon_admin, "nope")
        assert response.status_code == 401
        assert "Secret invalide" in response.text
        assert anon_admin.get("/admin/").status_code == 302

    def test_right_secret_goes_to_next(self, anon_admin):
        response = login(anon_admin, next_url="/admin/bugs/")
        assert response.headers["Location"] == "/admin/bugs/"
        assert anon_admin.get("/admin/").status_code == 200

    @pytest.mark.parametrize("next_url", ["//evil.example", "https://evil.example/", "admin"])
    def test_no_open_redirect(self, anon_admin, next_url):
        assert login(anon_admin, next_url=next_url).headers["Location"] == "/admin/"

    def test_login_requires_csrf(self, anon_admin):
        assert anon_admin.post("/admin/login/", data={"secret": SECRET}).status_code == 401
        assert anon_admin.get("/admin/").status_code == 302

    def test_brute_force_is_limited(self, anon_admin):
        for _ in range(5):
            assert login(anon_admin, "nope").status_code == 401
        assert login(anon_admin).status_code == 429

    def test_logout(self, admin):
        admin.get("/admin/login/logout/")
        assert admin.get("/admin/").status_code == 302

    def test_changing_the_secret_logs_out(self, admin, admin_app, monkeypatch):
        monkeypatch.setitem(admin_app.config, "ADMIN_SECRET", "rotated")
        assert admin.get("/admin/").status_code == 302

    def test_security_headers(self, anon_admin):
        headers = anon_admin.get("/admin/login/").headers
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Cache-Control"] == "no-store"

    def test_secret_is_generated_then_reused(self, tmp_path):
        path = tmp_path / ".admin.secrets"
        secret = load_admin_secret(str(path))
        assert len(secret) >= 24
        assert load_admin_secret(str(path)) == secret


class TestDashboard:
    def test_kpis(self, admin, world, ctx):
        with ctx():
            factories.make_user("gone", deleted=True)
            factories.make_message(world.group, world.member)
            factories.make_bug_report(world.member)
            factories.make_bug_report(world.member, status="resolved")
            factories.make_suggestion(world.admin)
            kpis = stats.get_kpis()
            top = stats.top_groups()
        assert (kpis["users_total"], kpis["users_active"], kpis["users_disabled"]) == (5, 4, 1)
        assert kpis["users_new_7d"] == 5
        assert (kpis["groups_total"], kpis["groups_avg_members"]) == (2, 1.5)
        assert (kpis["messages_total"], kpis["messages_7d"]) == (1, 1)
        assert (kpis["bugs_open"], kpis["bugs_resolved"], kpis["suggestions_total"]) == (1, 1, 1)
        assert [(g.id, n_messages, n_members) for g, n_messages, n_members in top][0] == (world.group.id, 1, 2)

        page = admin.get("/admin/").text
        assert "Crash" in page and "Qui dort le plus ?" in page and "member" in page

    def test_empty_database(self, admin):
        assert admin.get("/admin/").status_code == 200

    def test_profile_pictures(self, admin, admin_app, ctx, world):
        import os
        os.makedirs(admin_app.config["UPLOAD_FOLDER"], exist_ok=True)
        with open(os.path.join(admin_app.config["UPLOAD_FOLDER"], "pic.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        with ctx():
            db.session.get(UserModel, world.member.id).profile_picture = "pic.png"
            db.session.commit()
        assert "/admin/uploads/pic.png" in admin.get("/admin/users/").text
        assert admin.get("/admin/uploads/pic.png").status_code == 200
        assert admin.get("/admin/uploads/../app.py").status_code == 404


class TestUsers:
    def test_list(self, admin, world):
        page = admin.get("/admin/users/").text
        assert world.member.email in page
        assert f"/admin/users/toggle/{world.member.id}/" in page
        assert admin.get("/admin/users/?search=outsider").status_code == 200

    def test_toggle_deactivates_then_reactivates(self, admin, world, ctx, login_as):
        api = login_as(world.member)
        assert api.get("/api/groups/user/").status_code == 200

        token = csrf(admin, "/admin/users/")
        response = admin.post(f"/admin/users/toggle/{world.member.id}/", data={"csrf_token": token, "url": "/admin/users/"})
        assert response.headers["Location"] == "/admin/users/"
        with ctx():
            user = db.session.get(UserModel, world.member.id)
            assert (user.deleted, user.session_version) == (True, 1)
        assert api.get("/api/groups/user/").status_code == 401

        admin.post(f"/admin/users/toggle/{world.member.id}/", data={"csrf_token": token})
        with ctx():
            user = db.session.get(UserModel, world.member.id)
            assert (user.deleted, user.session_version) == (False, 2)
        assert login_as(world.member, session_version=2).get("/api/groups/user/").status_code == 200

    def test_toggle_requires_csrf(self, admin, world, ctx):
        admin.post(f"/admin/users/toggle/{world.member.id}/", data={"url": "/admin/users/"})
        with ctx():
            assert db.session.get(UserModel, world.member.id).deleted is False

    def test_toggle_unknown_user(self, admin):
        assert admin.post("/admin/users/toggle/1/", data={"csrf_token": csrf(admin, "/admin/users/")}).status_code == 404

    def test_bulk_actions(self, admin, world, ctx):
        ids = [str(world.member.id), str(world.outsider.id)]
        token = csrf(admin, "/admin/users/")
        admin.post("/admin/users/action/", data={"csrf_token": token, "action": "disable", "rowid": ids})
        with ctx():
            assert {u.username for u in UserModel.query.filter_by(deleted=True)} == {"member", "outsider"}
        admin.post("/admin/users/action/", data={"csrf_token": token, "action": "enable", "rowid": ids})
        with ctx():
            assert UserModel.query.filter_by(deleted=True).count() == 0

    def test_no_create_or_delete(self, admin, world):
        assert admin.get("/admin/users/new/").status_code in (302, 403, 404)
        assert admin.post("/admin/users/delete/", data={"id": world.member.id}).status_code in (302, 403, 404)
        assert admin.get(f"/admin/users/details/?id={world.member.id}").status_code == 200


class TestFeedback:
    def test_suggestions_show_their_author(self, admin, world, ctx):
        with ctx():
            factories.make_suggestion(world.member, "Qui ronfle ?")
        page = admin.get("/admin/suggestions/").text
        assert "Qui ronfle ?" in page and world.member.email in page
        assert admin.get("/admin/suggestions/?search=member").status_code == 200

    def test_delete_suggestion(self, admin, world, ctx):
        with ctx():
            suggestion_id = factories.make_suggestion(world.member)
        admin.post("/admin/suggestions/delete/", data={"id": suggestion_id, "csrf_token": csrf(admin, "/admin/suggestions/")})
        with ctx():
            assert SuggestionModel.query.count() == 0

    def test_bug_list_and_details(self, admin, world, ctx):
        with ctx():
            bug_id = factories.make_bug_report(world.member, "Vote KO", description="Line 1\nLine 2")
        page = admin.get("/admin/bugs/").text
        assert "Vote KO" in page and world.member.email in page
        details = admin.get(f"/admin/bugs/details/?id={bug_id}").text
        assert "Line 1\nLine 2" in details and "Ouvert" in details

    def test_inline_status_update(self, admin, world, ctx):
        with ctx():
            bug_id = factories.make_bug_report(world.member)
        response = admin.post("/admin/bugs/ajax/update/", data={
            "list_form_pk": bug_id, "status": "in_progress", "csrf_token": csrf(admin, "/admin/bugs/")})
        assert response.status_code == 200
        with ctx():
            assert db.session.get(BugReportModel, bug_id).status == "in_progress"

    def test_invalid_status_is_rejected(self, admin, world, ctx):
        with ctx():
            bug_id = factories.make_bug_report(world.member)
        admin.post(f"/admin/bugs/edit/?id={bug_id}", data={"status": "lost", "csrf_token": csrf(admin, "/admin/bugs/")})
        with ctx():
            assert db.session.get(BugReportModel, bug_id).status == "open"
            with pytest.raises(ValueError):
                BugReportModel(status="lost")

    @pytest.mark.parametrize("url", ["/admin/bugs/", "/admin/suggestions/"])
    def test_author_filter(self, admin, world, ctx, url):
        with ctx():
            for user in (world.member, world.outsider):
                factories.make_bug_report(user, f"bug-{user.username}")
                factories.make_suggestion(user, f"idea-{user.username}")
        arg = re.search(r'"Auteur": \[\{"arg": "(\d+)"', admin.get(url).text).group(1)
        page = admin.get(f"{url}?flt0_{arg}=outs").text
        assert "-outsider" in page and "-member" not in page

    def test_bulk_status(self, admin, world, ctx):
        with ctx():
            ids = [str(factories.make_bug_report(world.member)) for _ in range(2)]
        token = csrf(admin, "/admin/bugs/")
        for action, expected in [("mark_resolved", "resolved"), ("mark_in_progress", "in_progress"), ("mark_open", "open")]:
            admin.post("/admin/bugs/action/", data={"csrf_token": token, "action": action, "rowid": ids})
            with ctx():
                assert {b.status for b in BugReportModel.query} == {expected}


class TestDatabaseBrowser:
    def test_every_table_is_browsable(self, admin, world, ctx):
        with ctx():
            question = factories.make_question(world.group)
            factories.make_vote(question, world.member, [world.admin])
            factories.make_message(world.group, world.member)
            factories.make_invitation(world.group)
            factories.make_item(world.member, world.group)
        for model in DATABASE_MODELS:
            url = f"/admin/db/{model.__tablename__}/"
            response = admin.get(url)
            assert response.status_code == 200, url
            assert "pbkdf2" not in response.text
            match = re.search(r'href="(/admin/db/[^"]+/details/\?id=[^"&]+)', response.text)
            if match:
                assert admin.get(match.group(1).replace("&amp;", "&")).status_code == 200

    def test_read_only(self, admin, world):
        assert admin.get(f"/admin/db/groups/edit/?id={world.group.id}").status_code in (302, 403, 404)

    def test_search_and_filters(self, admin, world):
        assert admin.get("/admin/db/users/?search=member").status_code == 200
        assert admin.get("/admin/db/chat_messages/?flt0_0=hello").status_code == 200


class TestLanguages:
    def test_french_by_default(self, admin, world):
        page = admin.get("/admin/users/").text
        assert "Utilisateurs" in page and "Déconnexion" in page and "Ajouter un filtre" in page

    def test_browser_language_is_used(self, admin, world):
        page = admin.get("/admin/users/", headers={"Accept-Language": "en-US,en;q=0.9"}).text
        assert "Logout" in page and "Add Filter" in page

    def test_switch_to_english_and_back(self, admin, world, ctx):
        response = admin.get("/admin/login/language/en/?next=/admin/users/")
        assert response.headers["Location"] == "/admin/users/"
        page = admin.get("/admin/users/").text
        assert "Users" in page and "Logout" in page and "Signed up" in page and "Add Filter" in page
        assert "Utilisateurs" not in page

        token = csrf(admin, "/admin/users/")
        admin.post(f"/admin/users/toggle/{world.member.id}/", data={"csrf_token": token})
        assert "member&#39;s account disabled." in admin.get("/admin/users/").text

        admin.get("/admin/login/language/fr/")
        assert "Utilisateurs" in admin.get("/admin/users/").text

    @pytest.mark.parametrize("url", ["/admin/", "/admin/bugs/", "/admin/suggestions/", "/admin/db/users/"])
    def test_pages_render_in_english(self, admin, world, ctx, url):
        with ctx():
            bug_id = factories.make_bug_report(world.member)
            factories.make_suggestion(world.member)
        admin.get("/admin/login/language/en/")
        page = admin.get(url).text
        assert "Add Filter" in page or "Active users" in page
        assert admin.get(f"/admin/bugs/details/?id={bug_id}").text.count("Open") >= 1

    def test_unknown_language_is_ignored(self, admin):
        admin.get("/admin/login/language/de/")
        assert "Déconnexion" in admin.get("/admin/").text

    def test_language_survives_login_and_logout(self, anon_admin):
        anon_admin.get("/admin/login/language/en/")
        assert "Sign in" in anon_admin.get("/admin/login/").text
        login(anon_admin)
        assert "Logout" in anon_admin.get("/admin/").text
        anon_admin.get("/admin/login/logout/")
        assert "Sign in" in anon_admin.get("/admin/login/").text

    def test_no_open_redirect(self, anon_admin):
        assert anon_admin.get("/admin/login/language/en/?next=//evil.example").headers["Location"] == "/admin/"


class TestSchemaUpgrade:
    def test_adds_missing_columns_once(self, ctx):
        with ctx():
            db.session.execute(text("ALTER TABLE bug_reports DROP COLUMN status"))
            db.session.commit()
            assert upgrade_schema() == ["bug_reports.status"]
            assert upgrade_schema() == []
            columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(bug_reports)"))]
            assert "status" in columns


class TestEntrypoint:
    def test_refuses_a_public_host(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["admin", "--host", "0.0.0.0"])
        with pytest.raises(SystemExit):
            admin_main.main()

    def test_refuses_a_missing_database(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["admin", "--db", str(tmp_path / "nope.db")])
        with pytest.raises(SystemExit):
            admin_main.main()

    def test_runs_on_localhost(self, monkeypatch, tmp_path, app):
        db_file = tmp_path / "local.db"
        db_file.touch()
        calls = []
        monkeypatch.setattr(admin_main, "create_admin_app", lambda config: type("App", (), {
            "run": lambda self, **kwargs: calls.append((config, kwargs))})())
        monkeypatch.setattr(sys, "argv", ["admin", "--db", str(db_file), "--port", "9000"])
        admin_main.main()
        assert calls[0][0]["SQLALCHEMY_DATABASE_URI"].endswith("local.db")
        assert calls[0][1]["host"] == "127.0.0.1" and calls[0][1]["port"] == 9000
