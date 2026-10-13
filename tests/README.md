# Running the backend tests

All commands are run from `Sadikoi-API/` using the project's virtual environment.

```bash
cd Sadikoi-API
source venv/bin/activate          # or prefix commands with venv/bin/python -m
pip install -r requirements-dev.txt   # once only (pytest + pytest-cov)
```

> `pytest.ini` sets `addopts = -q` (compact output by default). As a result, `-v` by itself is **cancelled out** by `-q`.
> Use `-vv`, or `-o addopts=""` to start with a clean configuration.

## 1. Running the test suite

| Need | Command |
|---|---|
| Run everything (compact output) | `python -m pytest` |
| Verbose: one test per line (PASSED / FAILED) | `python -m pytest -vv` |
| Verbose without `pytest.ini`'s `-q` | `python -m pytest -o addopts="" -v` |
| Very quiet (summary only) | `python -m pytest -qq` |
| Stop at the first failure | `python -m pytest -x` |
| Stop after N failures | `python -m pytest --maxfail=3` |
| Rerun only tests that failed last time | `python -m pytest --lf` |
| Failed tests first, then the rest | `python -m pytest --ff` |
| Display `print()` output / logs live | `python -m pytest -s` |

## 2. Targeting tests

### By file

| Area | Command |
|---|---|
| Registration / login / account | `python -m pytest tests/test_auth_register_login.py` |
| Auth security (OTP, devices, forgot password, reports) | `python -m pytest tests/test_auth_security.py` |
| Session guard (`before_request`) | `python -m pytest tests/test_session_guard.py` |
| Groups (CRUD, roles, invitations) | `python -m pytest tests/test_groups.py` |
| Chat | `python -m pytest tests/test_chat.py` |
| Questions & votes | `python -m pytest tests/test_questions_votes.py` |
| Feedback (bugs / suggestions) | `python -m pytest tests/test_feedback.py` |
| Security (rate limiting, headers, CORS, size) | `python -m pytest tests/test_security.py` |
| Socket.IO | `python -m pytest tests/test_sockets.py` |
| Unit tests (pure functions, models) | `python -m pytest tests/test_unit.py` |
| Route coverage (end of suite) | `python -m pytest tests/test_zz_route_coverage.py` |

Multiple files: `python -m pytest tests/test_chat.py tests/test_groups.py`

### By class or specific test

```bash
python -m pytest tests/test_groups.py::TestPromote
python -m pytest tests/test_groups.py::TestPromote::test_cannot_promote_yourself
python -m pytest "tests/test_groups.py::TestCreateGroup::test_invalid_payloads[change3]"   # parametrized case
```

### By keyword (`-k`, on the file / class / test name)

```bash
python -m pytest -k "vote"                       # everything containing "vote"
python -m pytest -k "expired or previous_day"    # OR
python -m pytest -k "vote and not written"       # AND / NOT
python -m pytest tests/test_chat.py -k "non_member"
```

### By marker

```bash
python -m pytest -m ratelimit                    # rate-limit tests only (real limiter)
python -m pytest -m "not ratelimit"              # everything except those
```

## 3. Understanding what is being run

| Need | Command |
|---|---|
| List tests without running them | `python -m pytest --collect-only -q` |
| List tests from a file / filter | `python -m pytest tests/test_chat.py --collect-only -q` |
| Show the 10 slowest tests | `python -m pytest --durations=10` |
| Reasons for `xfail` / `skip` | `python -m pytest -rxs` |
| Full summary (failures, xfail, skip, errors) | `python -m pytest -ra` |
| List markers and fixtures | `python -m pytest --markers` / `python -m pytest --fixtures` |

## 4. Debugging a failure

| Need | Command |
|---|---|
| Short traceback | `python -m pytest --tb=short` |
| One-line traceback | `python -m pytest --tb=line` |
| Full traceback with local variables | `python -m pytest --tb=long -l` |
| No traceback (list only) | `python -m pytest --tb=no` |
| Open `pdb` on the first failure | `python -m pytest -x --pdb` |
| Last failure only, highly detailed | `python -m pytest --lf -vv -l --tb=long` |
| Run the test as if it were not `xfail` | `python -m pytest --runxfail tests/test_groups.py -k unknown_user` |

## 5. Code coverage

```bash
python -m pytest --cov=src                                   # summary by file
python -m pytest --cov=src --cov-report=term-missing         # + uncovered lines
python -m pytest --cov=src --cov-report=html                 # report in htmlcov/index.html
python -m pytest --cov=src --cov-fail-under=85               # fails below 85%
python -m pytest tests/test_chat.py --cov=src/chat.py --cov-report=term-missing
```

## 6. Known bugs (`xfail`)

Tests using `@pytest.mark.xfail(strict=True)` describe the **expected behavior** of a bug that is still present in the API. *(None for now: the 6 initial bugs have been fixed.)*

```bash
python -m pytest -rx                       # list xfail tests and the reason
python -m pytest --runxfail -k "duplicate" # see the actual failure
```

When the bug is fixed, the test becomes an **error** (`XPASS(strict)`): remove the `xfail` decorator.

## 7. Quick recipes

```bash
python -m pytest -x -vv --lf                       # fix loop: rerun what broke, with details
python -m pytest -m ratelimit -vv                  # check rate limits
python -m pytest -q --cov=src --cov-report=term-missing --cov-fail-under=85   # "CI" check
python -m pytest tests/test_security.py tests/test_session_guard.py -vv        # all security-related tests
```

## 8. Where tests run

- **Temporary** SQLite database, recreated for every test: `instance/` and `uploads/` are never touched.
- Network, email, Turnstile, and Socket.IO are mocked (the `externals` fixture in `conftest.py`).
- No environment variables are required; `FLASK_DEBUG` has no effect on the tests.

## 9. CI (GitHub Actions)

The `.github/workflows/tests.yml` workflow is triggered for every pull request to `main`, every push to `main`, and on demand (*Actions → Tests → Run workflow*). It fails if any test fails **or** if code coverage drops below 85%.

To exactly replicate the CI locally:

```bash
python -m pytest -ra --cov=src --cov-report=term-missing --cov-report=xml --cov-fail-under=85 --junitxml=junit.xml
```

The `coverage.xml` and `junit.xml` reports are retained for 7 days as run artifacts, and the code coverage table is displayed in the job summary.

Translated with DeepL.com (free version)
