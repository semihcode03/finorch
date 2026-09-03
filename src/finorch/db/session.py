"""Veritabani baglantisi ve oturum yonetimi."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateColumn

from finorch.config import settings
from finorch.db.models import Base

logger = logging.getLogger(__name__)

_engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)


def _sync_new_columns() -> None:
    """Modelde olup tabloda olmayan kolonlari ekler (ileri-yonlu hafif migrasyon).

    `create_all` yalnizca eksik tabloyu olusturur, mevcut tabloya kolon eklemez.
    Alembic getirmek yerine sema yalnizca yeni kolon eklenerek buyudugu surece bu
    yeterli. Kolon silme veya tur degistirme desteklenmez; NOT NULL kolonlarin
    dolu tabloya eklenebilmesi icin modelde `server_default` tanimli olmalidir.
    """
    inspector = inspect(_engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all zaten olusturdu
        present = {c["name"] for c in inspector.get_columns(table.name)}
        missing = [c for c in table.columns if c.name not in present]
        if not missing:
            continue
        with _engine.begin() as conn:
            for column in missing:
                ddl = CreateColumn(column).compile(dialect=_engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS {ddl}')
                )
        logger.info(
            "Yeni kolonlar eklendi (%s): %s",
            table.name,
            ", ".join(c.name for c in missing),
        )


def init_db() -> None:
    """pgvector uzantisini kurar, tablolari olusturur ve eksik kolonlari ekler."""
    with _engine.begin() as conn:
        # pgvector ileriki fazlarda embedding icin kullanilacak
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(_engine)
    _sync_new_columns()


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
