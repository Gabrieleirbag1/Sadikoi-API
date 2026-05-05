import json
import os
import sys
import traceback
from typing import Any, Callable

import app as app_module
from models import GroupModel, UserModel


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_NAME = "data-test"
DB_FILE = os.path.join(BASE_DIR, f"{DB_NAME}.db")


def _safe_json(response) -> Any:
    try:
        return response.get_json()
    except Exception:
        return response.data.decode("utf-8", errors="ignore")


def _record_result(results, name: str, ok: bool, details: str = "") -> None:
    results.append({"name": name, "ok": ok, "details": details})


def _request_json(client, method: str, url: str, payload: dict | None = None):
    return client.open(url, method=method, json=payload)


def _request_form(client, method: str, url: str, payload: dict | None = None):
    return client.open(url, method=method, data=payload, content_type="application/x-www-form-urlencoded")


def _run_step(results, name: str, fn: Callable[[], Any], expected_statuses: set[int]) -> Any:
    try:
        response = fn()
        status = response.status_code
        if status in expected_statuses:
            _record_result(results, name, True, f"status={status}")
        else:
            body = _safe_json(response)
            _record_result(results, name, False, f"status={status} body={body}")
        return response
    except Exception as exc:
        details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _record_result(results, name, False, f"exception={details}")
        return None


def _print_summary(results) -> int:
    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    print("\n=== API Test Summary ===")
    for item in results:
        marker = "OK" if item["ok"] else "FAIL"
        details = f" ({item['details']})" if item["details"] else ""
        print(f"- {marker}: {item['name']}{details}")

    print(f"\nPassed: {len(passed)}  Failed: {len(failed)}")
    return 0 if not failed else 1


def main() -> int:
    os.chdir(BASE_DIR)
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    app_module.main(DB_NAME)
    app_module.app.testing = True

    results = []

    with app_module.app.app_context():
        client = app_module.app.test_client()

        user_payload = {"email": "test@example.com", "username": "testuser", "password": "pass1234"}
        _run_step(
            results,
            "POST /register",
            lambda: _request_json(client, "POST", "/register", user_payload),
            {201},
        )

        user2_payload = {"email": "test2@example.com", "username": "testuser2", "password": "pass1234"}
        _run_step(
            results,
            "POST /register (user2)",
            lambda: _request_json(client, "POST", "/register", user2_payload),
            {201},
        )

        user3_payload = {"email": "test3@example.com", "username": "testuser3", "password": "pass1234"}
        _run_step(
            results,
            "POST /register (user3)",
            lambda: _request_json(client, "POST", "/register", user3_payload),
            {201},
        )

        user = UserModel.query.filter_by(username="testuser").first()
        if not user:
            _record_result(results, "Fetch user after register", False, "user not found")
            return _print_summary(results)
        _record_result(results, "Fetch user after register", True, f"user_id={user.id}")

        user2 = UserModel.query.filter_by(username="testuser2").first()
        if not user2:
            _record_result(results, "Fetch user2 after register", False, "user not found")
            return _print_summary(results)
        _record_result(results, "Fetch user2 after register", True, f"user_id={user2.id}")

        user3 = UserModel.query.filter_by(username="testuser3").first()
        if not user3:
            _record_result(results, "Fetch user3 after register", False, "user not found")
            return _print_summary(results)
        _record_result(results, "Fetch user3 after register", True, f"user_id={user3.id}")

        update_payload = {"email": "updated@example.com", "username": "testuser"}
        _run_step(
            results,
            "PUT /register/<user_id>",
            lambda: _request_json(client, "PUT", f"/register/{user.id}/", update_payload),
            {200},
        )

        _run_step(
            results,
            "GET /account/<user_id>",
            lambda: _request_json(client, "GET", f"/account/{user.id}/"),
            {200},
        )

        login_payload = {"username_or_email": "testuser", "password": "pass1234", "remember": "true"}
        _run_step(
            results,
            "POST /login",
            lambda: _request_form(client, "POST", "/login", login_payload),
            {200},
        )

        group_payload = {"username": "testuser", "name": "group1", "description": "test group"}
        _run_step(
            results,
            "POST /groups",
            lambda: _request_json(client, "POST", "/groups", group_payload),
            {201},
        )

        group2_payload = {"username": "testuser2", "name": "group2", "description": "test group 2"}
        _run_step(
            results,
            "POST /groups (group2)",
            lambda: _request_json(client, "POST", "/groups", group2_payload),
            {201},
        )

        group = GroupModel.query.filter_by(name="group1").first()
        if not group:
            _record_result(results, "Fetch group after create", False, "group not found")
            return _print_summary(results)
        _record_result(results, "Fetch group after create", True, f"group_id={group.id}")

        group2 = GroupModel.query.filter_by(name="group2").first()
        if not group2:
            _record_result(results, "Fetch group2 after create", False, "group not found")
            return _print_summary(results)
        _record_result(results, "Fetch group2 after create", True, f"group_id={group2.id}")

        _run_step(
            results,
            "PUT /groups/<group_id>",
            lambda: _request_json(client, "PUT", f"/groups/{group.id}/", {"description": "updated"}),
            {200},
        )

        _run_step(
            results,
            "POST /groups/<group_id>/<user_id>",
            lambda: _request_json(client, "POST", f"/groups/{group2.id}/{user.id}/", {}),
            {200},
        )

        _run_step(
            results,
            "DELETE /groups/<group_id>/<user_id>",
            lambda: _request_json(client, "DELETE", f"/groups/{group2.id}/{user.id}/", {}),
            {200},
        )

        _run_step(
            results,
            "POST /groups/<group_id>/messages",
            lambda: _request_json(
                client,
                "POST",
                f"/groups/{group.id}/messages",
                {"content": "hello", "user_id": user.id},
            ),
            {201},
        )

        _run_step(
            results,
            "GET /groups/<group_id>/messages",
            lambda: _request_json(client, "GET", f"/groups/{group.id}/messages"),
            {200},
        )

        _run_step(
            results,
            "GET /question/<group_id>",
            lambda: _request_json(client, "GET", f"/question/{group.id}"),
            {200},
        )

        _run_step(
            results,
            "GET /question/<group_id> (group2)",
            lambda: _request_json(client, "GET", f"/question/{group2.id}"),
            {200},
        )

        _run_step(
            results,
            "POST /question/<group_id>/vote",
            lambda: _request_json(
                client,
                "POST",
                f"/question/{group.id}/vote",
                {"username": "testuser", "votedUsers": [user2.id, user3.id]},
            ),
            {200},
        )

        _run_step(
            results,
            "POST /question/<group_id>/vote with written answer",
            lambda: _request_json(
                client,
                "POST",
                f"/question/{group2.id}/vote",
                {"username": "testuser2", "writtenAnswer": "my answer"},
            ),
            {400},
        )

        _run_step(
            results,
            "DELETE /groups/<group_id>",
            lambda: _request_json(client, "DELETE", f"/groups/{group.id}/"),
            {200},
        )

        _run_step(
            results,
            "DELETE /register/<user_id>",
            lambda: _request_json(client, "DELETE", f"/register/{user.id}/", {}),
            {200},
        )

        _run_step(
            results,
            "DELETE /register/<user_id> (user2)",
            lambda: _request_json(client, "DELETE", f"/register/{user2.id}/", {}),
            {200},
        )

        _run_step(
            results,
            "DELETE /register/<user_id> (user3)",
            lambda: _request_json(client, "DELETE", f"/register/{user3.id}/", {}),
            {200},
        )

    return _print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
