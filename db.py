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
                    rating INT DEFAULT 0,
                    description TEXT,
                    creation_date DATE DEFAULT CURRENT_DATE,
                    original_address VARCHAR
                );
                """
            )
            cur.execute(
                """
                ALTER TABLE perfume
                DROP COLUMN IF EXISTS "like";
                """
            )
            cur.execute(
                """
                ALTER TABLE perfume
                ADD COLUMN IF NOT EXISTS rating INT DEFAULT 0;
                """
            )
            cur.execute(
                """
                ALTER TABLE perfume
                ALTER COLUMN rating TYPE INT USING GREATEST(0, LEAST(5, COALESCE(rating, 0))),
                ALTER COLUMN rating SET DEFAULT 0;
                """
            )
            cur.execute(
                """
                UPDATE perfume
                SET rating = 0
                WHERE rating IS NULL OR rating < 0 OR rating > 5;
                """
            )
            cur.execute(
                """
                ALTER TABLE perfume
                ALTER COLUMN rating SET NOT NULL;
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
                         AND attr.attname = 'rating'
                        WHERE rel.relname = 'perfume'
                          AND con.contype = 'c'
                          AND attr.attnum = ANY(con.conkey)
                    LOOP
                        EXECUTE 'ALTER TABLE perfume DROP CONSTRAINT ' || quote_ident(rec.conname);
                    END LOOP;

                    ALTER TABLE perfume
                    ADD CONSTRAINT perfume_rating_check CHECK (rating >= 0 AND rating <= 5);
                END $$;
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
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    keycloak_uuid VARCHAR(36) NOT NULL UNIQUE
                );
                """
            )
            cur.execute(
                """
                ALTER TABLE perfume
                ADD COLUMN IF NOT EXISTS user_id INT;
                """
            )
            cur.execute(
                """
                ALTER TABLE wishlist
                ADD COLUMN IF NOT EXISTS user_id INT;
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
                    original_address VARCHAR,
                    user_id INT
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS fragrantica_note_profiles (
                    note_id      TEXT PRIMARY KEY,
                    note_name    TEXT NOT NULL,
                    note_url     TEXT NOT NULL,
                    odor_profile TEXT,
                    source       TEXT DEFAULT 'fragrantica',
                    fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )


def get_or_create_user(keycloak_uuid: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE keycloak_uuid = %s;",
                (keycloak_uuid,),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            cur.execute(
                "INSERT INTO users (keycloak_uuid) VALUES (%s) RETURNING id;",
                (keycloak_uuid,),
            )
            return cur.fetchone()[0]


def add_perfume(
    name: str,
    brand: str,
    pyramid_data: str,
    original_address: str,
    user_id: int,
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
                        size,
                        user_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        rating,
                        description,
                        creation_date,
                        original_address,
                        size;
                    """,
                    (name, brand, pyramid_data, description, original_address, size, user_id),
                )
                return dict(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


def get_all_perfumes(user_id: int) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size
                FROM perfume
                WHERE user_id = %s AND size != 3
                ORDER BY creation_date DESC, id DESC;
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def get_archived_perfumes(user_id: int) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size
                FROM perfume
                WHERE user_id = %s AND size = 3
                ORDER BY creation_date DESC, id DESC;
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def update_rating(perfume_id: int, rating: int, user_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET rating = %s
                WHERE id = %s AND user_id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (rating, perfume_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_note(perfume_id: int, note: str, user_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET description = %s
                WHERE id = %s AND user_id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (note, perfume_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_size(perfume_id: int, size: int, user_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET size = %s
                WHERE id = %s AND user_id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (size, perfume_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_perfume_details(
    perfume_id: int,
    name: str,
    brand: str,
    pyramid_data: str,
    user_id: int,
) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perfume
                SET name = %s,
                    brand = %s,
                    pyramid_data = %s
                WHERE id = %s AND user_id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    rating,
                    description,
                    creation_date,
                    original_address,
                    size;
                """,
                (name, brand, pyramid_data, perfume_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_perfume(perfume_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM perfume WHERE id = %s AND user_id = %s;",
                (perfume_id, user_id),
            )
            return cur.rowcount > 0


def add_to_wishlist(
    name: str,
    brand: str,
    pyramid_data: str,
    original_address: str,
    user_id: int,
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
                        original_address,
                        user_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        creation_date,
                        original_address;
                    """,
                    (name, brand, pyramid_data, original_address, user_id),
                )
                return dict(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


def get_wishlist(user_id: int) -> list[dict]:
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
                WHERE user_id = %s
                ORDER BY creation_date DESC, id DESC;
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def update_wishlist_details(
    wishlist_id: int,
    name: str,
    brand: str,
    pyramid_data: str,
    user_id: int,
) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE wishlist
                SET name = %s,
                    brand = %s,
                    pyramid_data = %s
                WHERE id = %s AND user_id = %s
                RETURNING
                    id,
                    name,
                    brand,
                    pyramid_data,
                    creation_date,
                    original_address;
                """,
                (name, brand, pyramid_data, wishlist_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def move_to_library(wishlist_id: int, user_id: int) -> dict | None:
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
                    WHERE id = %s AND user_id = %s
                    FOR UPDATE;
                    """,
                    (wishlist_id, user_id),
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
                        original_address,
                        user_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        name,
                        brand,
                        pyramid_data,
                        rating,
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
                        user_id,
                    ),
                )
                perfume_row = cur.fetchone()

                cur.execute("DELETE FROM wishlist WHERE id = %s;", (wishlist_id,))
                return dict(perfume_row)
    except errors.UniqueViolation as exc:
        raise DuplicatePerfumeError from exc


def delete_from_wishlist(wishlist_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM wishlist WHERE id = %s AND user_id = %s;",
                (wishlist_id, user_id),
            )
            return cur.rowcount > 0


def get_note_profile(note_id: str) -> dict | None:
    """Return cached note profile by note_id, or None if not present."""
    if not note_id:
        return None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT note_id, note_name, note_url, odor_profile, source,
                       fetched_at, updated_at
                FROM fragrantica_note_profiles
                WHERE note_id = %s;
                """,
                (note_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_note_profiles(note_ids: list[str]) -> dict[str, dict]:
    """Bulk fetch note profiles; returns a dict keyed by note_id."""
    if not note_ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT note_id, note_name, note_url, odor_profile, source,
                       fetched_at, updated_at
                FROM fragrantica_note_profiles
                WHERE note_id = ANY(%s);
                """,
                (list(note_ids),),
            )
            return {row["note_id"]: dict(row) for row in cur.fetchall()}


def upsert_note_profile(
    note_id: str,
    note_name: str,
    note_url: str,
    odor_profile: str,
    source: str = "fragrantica",
) -> None:
    """Insert or update a cached note profile."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fragrantica_note_profiles (
                    note_id, note_name, note_url, odor_profile, source,
                    fetched_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (note_id) DO UPDATE
                SET note_name = EXCLUDED.note_name,
                    note_url = EXCLUDED.note_url,
                    odor_profile = EXCLUDED.odor_profile,
                    source = EXCLUDED.source,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (note_id, note_name, note_url, odor_profile, source),
            )
