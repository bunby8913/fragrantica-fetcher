import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


@contextmanager
def get_connection():
    conn = psycopg2.connect(_database_url())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS perfume (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    brand VARCHAR NOT NULL,
                    pyramid_data TEXT,
                    "like" BOOLEAN DEFAULT FALSE,
                    description TEXT,
                    creation_date DATE DEFAULT CURRENT_DATE,
                    original_address VARCHAR
                );
                """
            )


def add_perfume(
    name: str,
    brand: str,
    pyramid_data: str,
    description: str,
    original_address: str,
) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO perfume (
                    name,
                    brand,
                    pyramid_data,
                    description,
                    original_address
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    "like",
                    description,
                    creation_date,
                    original_address;
                """,
                (name, brand, pyramid_data, description, original_address),
            )
            return dict(cur.fetchone())


def get_all_perfumes() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    brand,
                    pyramid_data,
                    "like",
                    description,
                    creation_date,
                    original_address
                FROM perfume
                ORDER BY creation_date DESC, id DESC;
                """
            )
            return [dict(row) for row in cur.fetchall()]


def toggle_like(perfume_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET "like" = NOT COALESCE("like", FALSE)
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    "like",
                    description,
                    creation_date,
                    original_address;
                """,
                (perfume_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
