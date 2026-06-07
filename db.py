import os
from contextlib import contextmanager

import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


class DuplicatePerfumeError(Exception):
    pass


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
            cur.execute(
                """
                ALTER TABLE perfume
                ADD COLUMN IF NOT EXISTS size INT DEFAULT 0;
                """
            )
            cur.execute(
                """
                DO $$
                DECLARE
                    rec record;
                BEGIN
                    FOR rec IN
                        SELECT con.conname
                        FROM pg_constraint con
                        JOIN pg_class rel ON rel.oid = con.conrelid
                        JOIN pg_attribute attr
                          ON attr.attrelid = rel.oid
                         AND attr.attname = 'size'
                        WHERE rel.relname = 'perfume'
                          AND con.contype = 'c'
                          AND attr.attnum = ANY(con.conkey)
                    LOOP
                        EXECUTE 'ALTER TABLE perfume DROP CONSTRAINT ' || quote_ident(rec.conname);
                    END LOOP;

                    ALTER TABLE perfume
                    ADD CONSTRAINT perfume_size_check CHECK (size >= 0 AND size <= 3);
                END $$;
                """
            )
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION prevent_duplicate_perfume_insert()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock(hashtext(NEW.name), hashtext(NEW.brand));

                    IF EXISTS (
                        SELECT 1
                        FROM perfume
                        WHERE name = NEW.name
                          AND brand = NEW.brand
                    ) THEN
                        RAISE EXCEPTION 'Perfume already exists: % by %', NEW.name, NEW.brand
                            USING ERRCODE = 'unique_violation';
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS perfume_prevent_duplicate_insert ON perfume;

                CREATE TRIGGER perfume_prevent_duplicate_insert
                BEFORE INSERT ON perfume
                FOR EACH ROW
                EXECUTE FUNCTION prevent_duplicate_perfume_insert();
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS wishlist (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    brand VARCHAR NOT NULL,
                    pyramid_data TEXT,
                    creation_date DATE DEFAULT CURRENT_DATE,
                    original_address VARCHAR
                );
                """
            )
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION prevent_duplicate_wishlist_insert()
                RETURNS trigger AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock(hashtext(NEW.name), hashtext(NEW.brand));

                    IF EXISTS (
                        SELECT 1
                        FROM wishlist
                        WHERE name = NEW.name
                          AND brand = NEW.brand
                    ) THEN
                        RAISE EXCEPTION 'Wishlist perfume already exists: % by %', NEW.name, NEW.brand
                            USING ERRCODE = 'unique_violation';
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS wishlist_prevent_duplicate_insert ON wishlist;

                CREATE TRIGGER wishlist_prevent_duplicate_insert
                BEFORE INSERT ON wishlist
                FOR EACH ROW
                EXECUTE FUNCTION prevent_duplicate_wishlist_insert();
                """
            )


def add_perfume(
    name: str,
    brand: str,
    pyramid_data: str,
    original_address: str,
    description: str = "",
    size: int = 0,
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO perfume (
                        name,
                        brand,
                        pyramid_data,
                        description,
                        original_address,
                        size
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        "like",
                        description,
                        creation_date,
                        original_address,
                        size;
                    """,
                    (name, brand, pyramid_data, description, original_address, size),
                )
                return dict(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


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
                    original_address,
                    size
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
                    original_address,
                    size;
                """,
                (perfume_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_note(perfume_id: int, note: str) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET description = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    "like",
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (note, perfume_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_size(perfume_id: int, size: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET size = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    "like",
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (size, perfume_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_perfume(perfume_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM perfume WHERE id = %s;", (perfume_id,))
            return cur.rowcount > 0


def add_to_wishlist(
    name: str,
    brand: str,
    pyramid_data: str,
    original_address: str,
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO wishlist (
                        name,
                        brand,
                        pyramid_data,
                        original_address
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        creation_date,
                        original_address;
                    """,
                    (name, brand, pyramid_data, original_address),
                )
                return dict(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


def get_wishlist() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    brand,
                    pyramid_data,
                    creation_date,
                    original_address
                FROM wishlist
                ORDER BY creation_date DESC, id DESC;
                """
            )
            return [dict(row) for row in cur.fetchall()]


def move_to_library(wishlist_id: int) -> dict | None:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        brand,
                        pyramid_data,
                        original_address
                    FROM wishlist
                    WHERE id = %s
                    FOR UPDATE;
                    """,
                    (wishlist_id,),
                )
                wishlist_row = cur.fetchone()
                if not wishlist_row:
                    return None

                cur.execute(
                    """
                    INSERT INTO perfume (
                        name,
                        brand,
                        pyramid_data,
                        original_address
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        "like",
                        description,
                        creation_date,
                        original_address,
                        size;
                    """,
                    (
                        wishlist_row["name"],
                        wishlist_row["brand"],
                        wishlist_row["pyramid_data"],
                        wishlist_row["original_address"],
                    ),
                )
                perfume_row = cur.fetchone()

                cur.execute("DELETE FROM wishlist WHERE id = %s;", (wishlist_id,))
                return dict(perfume_row)
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


def delete_from_wishlist(wishlist_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wishlist WHERE id = %s;", (wishlist_id,))
            return cur.rowcount > 0
