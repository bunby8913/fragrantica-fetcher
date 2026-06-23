-- Adds normalized note group caching for Fragrantica note pages.
-- This migration is intentionally idempotent because run_migrations()
-- executes SQL migration files on every app startup.

CREATE TABLE IF NOT EXISTS note_group (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS note_group_name_lower_unique
ON note_group (LOWER(name));

ALTER TABLE fragrantica_note_profiles
ADD COLUMN IF NOT EXISTS group_name TEXT;

ALTER TABLE fragrantica_note_profiles
ADD COLUMN IF NOT EXISTS note_group_id INT REFERENCES note_group(id);
