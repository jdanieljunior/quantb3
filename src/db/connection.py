"""
QuantB3 — Conexão com o banco de dados (Supabase/PostgreSQL)
"""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


def get_db_url() -> str:
    """Retorna a URL de conexão do banco de dados."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError(
            "DATABASE_URL não configurada. "
            "Defina a variável de ambiente ou crie um arquivo .env"
        )
    return url


def get_engine():
    """Cria e retorna o engine SQLAlchemy."""
    url = get_db_url()
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"sslmode": "require"} if "supabase" in url else {},
    )


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context manager para conexão psycopg2 direta."""
    url = get_db_url()
    conn = psycopg2.connect(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor() -> Generator[RealDictCursor, None, None]:
    """Context manager para cursor com retorno como dict."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
        finally:
            cursor.close()


def test_connection() -> bool:
    """Testa a conexão com o banco de dados."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            logger.info("Conexão com banco de dados OK")
            return result is not None
    except Exception as e:
        logger.error(f"Erro na conexão com banco de dados: {e}")
        return False
