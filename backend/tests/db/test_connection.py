"""Opening a session on a real PostgreSQL database."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from ledgerlens.db.session import make_engine

pytestmark = pytest.mark.db


def test_select_one(empty_database_url: str) -> None:
    engine = make_engine(empty_database_url)
    try:
        with Session(engine) as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
