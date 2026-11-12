"""Regression tests: the database password never appears in pytest output.

Written again from the backend's test (#6). Each test runs pytest in a
subprocess on a scratch test folder that reuses the fixtures of
`tests/db/conftest.py`, with a marker password, and checks that the marker is
nowhere in the output. `--showlocals` is on, so even the local variables of
the traceback frames are printed.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL

from demobank.db.startup import make_engine
from tests.db.support import DEMOBANK_DIR, TEST_DATABASE_URL

SCRATCH_CONFTEST = "from tests.db.conftest import *  # noqa: F403\n"
SCRATCH_INI = "[pytest]\nmarkers =\n    db: needs PostgreSQL\n"

FAILING_TESTS = """
import pytest
from sqlalchemy import text

from demobank.db.startup import make_engine

pytestmark = pytest.mark.db


def test_fails_with_empty_database(empty_database_url):
    assert empty_database_url is None


def test_fails_with_engine(engine):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 2


def test_driver_error_in_the_middle_of_a_test(empty_database_url):
    engine = make_engine(empty_database_url.set(database="demobank_does_not_exist"))
    with engine.connect():
        pass
"""


def run_scratch_pytest(tmp_path: Path, test_database_url: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "conftest.py").write_text(SCRATCH_CONFTEST)
    (tmp_path / "pytest.ini").write_text(SCRATCH_INI)
    (tmp_path / "test_scratch.py").write_text(FAILING_TESTS)
    environment = dict(os.environ)
    environment[TEST_DATABASE_URL] = test_database_url
    environment["PYTHONPATH"] = str(DEMOBANK_DIR)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            "--showlocals",
            "-rA",
            "-vv",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def marker_password() -> str:
    return f"MARKERpw{secrets.token_hex(6)}"


def test_rejected_server_url_does_not_print_the_password(tmp_path: Path) -> None:
    """A server that refuses the connection: no PostgreSQL needed (port 1 is closed)."""
    marker = marker_password()
    result = run_scratch_pytest(tmp_path, f"postgresql://demobank:{marker}@127.0.0.1:1/postgres")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "3 error" in output
    assert "TEST_DATABASE_URL server: " in output
    assert marker not in output


@pytest.mark.db
def test_wrong_password_does_not_print_the_password(server_url: URL, tmp_path: Path) -> None:
    marker = marker_password()
    wrong = server_url.set(password=marker).render_as_string(hide_password=False)
    result = run_scratch_pytest(tmp_path, wrong)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "3 error" in output
    assert "password authentication failed" in output
    assert marker not in output


@pytest.mark.db
def test_failing_db_tests_do_not_print_the_password(server_url: URL, tmp_path: Path) -> None:
    role = f"demobank_marker_{secrets.token_hex(4)}"
    marker = marker_password()
    admin = make_engine(server_url).execution_options(isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            can_create_roles = connection.execute(
                text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
            if not can_create_roles:
                pytest.skip("the TEST_DATABASE_URL user cannot create a marker role")
            connection.execute(text(f"CREATE ROLE {role} LOGIN CREATEDB PASSWORD '{marker}'"))
        try:
            url = server_url.set(username=role, password=marker)
            result = run_scratch_pytest(tmp_path, url.render_as_string(hide_password=False))
        finally:
            with admin.connect() as connection:
                connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
    finally:
        admin.dispose()
    output = result.stdout + result.stderr

    assert "3 failed" in output, "the scratch tests did not run to their failure"
    assert marker not in output
