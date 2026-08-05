from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as connection:
            try:
                connection.execute(
                    text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS source_blocks_fts "
                        "USING fts5(block_id UNINDEXED, project_id UNINDEXED, text, tokenize='trigram')"
                    )
                )
            except Exception:
                connection.execute(
                    text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS source_blocks_fts "
                        "USING fts5(block_id UNINDEXED, project_id UNINDEXED, text)"
                    )
                )


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
