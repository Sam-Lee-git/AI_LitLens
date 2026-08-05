from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="content-agent-tests-"))
os.environ["CONTENT_AGENT_PROVIDER"] = "mock"
os.environ["CONTENT_AGENT_DATA_DIR"] = str(TEST_ROOT)
os.environ["CONTENT_AGENT_DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import Base, engine, init_db
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS source_blocks_fts"))
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS source_blocks_fts"))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
