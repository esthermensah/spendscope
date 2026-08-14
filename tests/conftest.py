import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from spendscope.database.connection import create_sqlite_engine
from spendscope.database.migrations import migrate_database

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def database_engine(tmp_path: Path) -> Iterator[Engine]:
    database_path = tmp_path / "expenses.db"
    migrate_database(database_path)
    engine = create_sqlite_engine(database_path)
    yield engine
    engine.dispose()
