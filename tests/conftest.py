"""Shared fixtures for the test suite.

Every test runs against a throwaway database in the pytest temporary
directory, so the tests never touch the lab dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import load_settings  # noqa: E402
from data.duckdb_repo import DuckDbRepo  # noqa: E402
from data.etl import run_etl  # noqa: E402
from data.seed import seed_all  # noqa: E402
from data.sqlite_repo import SqliteRepo  # noqa: E402
from services import Services  # noqa: E402


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory) -> Path:
    """A small seeded SQLite database, built once for the whole session."""
    directory = tmp_path_factory.mktemp("lab")
    db_path = directory / "oltp.sqlite"
    seed_all(scale="small", seed=7, db_path=db_path, csv_dir=directory / "csv", quiet=True)
    return db_path


@pytest.fixture(scope="session")
def olap_db(seeded_db: Path, tmp_path_factory) -> Path:
    """The analytical database, built from the same seeded data."""
    olap_path = tmp_path_factory.mktemp("olap") / "olap.duckdb"
    run_etl(oltp_path=seeded_db, olap_path=olap_path, export=False, quiet=True)
    return olap_path


@pytest.fixture()
def repo(seeded_db: Path) -> SqliteRepo:
    connection = SqliteRepo(seeded_db)
    yield connection
    connection.close()


@pytest.fixture()
def duck(olap_db: Path) -> DuckDbRepo:
    repository = DuckDbRepo(olap_db)
    yield repository
    repository.close()


@pytest.fixture()
def services(repo: SqliteRepo, duck: DuckDbRepo) -> Services:
    container = Services(repo=repo, duck=duck)
    yield container


@pytest.fixture()
def client(seeded_db: Path, olap_db: Path):
    """A test client on the throwaway database, not on the lab dataset."""
    from fastapi.testclient import TestClient

    from app import create_app

    settings = load_settings()
    settings.oltp_path = seeded_db
    settings.olap_path = olap_db
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
