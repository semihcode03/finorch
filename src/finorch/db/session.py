"""Veritabani baglantisi ve oturum yonetimi."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from finorch.config import settings
from finorch.db.models import Base

_engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """pgvector uzantisini kurar ve tablolari olusturur."""
    with _engine.begin() as conn:
        # pgvector ileriki fazlarda embedding icin kullanilacak
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    """Baglanti saglik kontrolu."""
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
