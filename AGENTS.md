# AGENTS.md

## Repo Shape
- Single Flask app: `app.py` serves `templates/index.html` and JSON APIs; `static/app.js` owns table rendering and all row interactions.
- PostgreSQL access is centralized in `db.py`; migrations run only through `create_app()`/`python app.py` via `run_migrations()`.
- `scraper.py` is both an import used by `/add_perfume` and a CLI (`python scraper.py <fragrantica perfume url>`).

## Setup And Commands
- Install deps with `pip install -r requirements.txt`; there is no package manager lockfile or test runner config.
- `.env` is loaded by `app.py`; `DATABASE_URL` is required before any DB call or migration.
- Run the web app with `python app.py` from repo root; it binds `0.0.0.0:5000` and runs migrations first.
- Focused verification currently available: `python -m compileall app.py db.py scraper.py` and `node --check static/app.js`.

## Data Model Gotchas
- The UI calls the editable `description` column “Note”; keep storing notes in PostgreSQL column `description` unless doing an explicit schema migration.
- New scraped entries must not populate `description`; `scraper.py` intentionally does not scrape page descriptions.
- `size` is stored as int `0..2`: `0` Sample, `1` Decant, `2` Full bottle.
- `pyramid_data` is JSON serialized into a text column and expected by the UI to contain `top_notes`, `middle_notes`, and `base_notes` arrays.
- SQL must quote the `like` column as `"like"`.

## Scraping Notes
- Fragrantica fetches use `curl_cffi.requests.get(..., impersonate="chrome120")`; plain `requests` may fail against the site.
- `_extract_name()` strips the scraped brand name from the perfume name with case-insensitive string matching.

## Frontend Notes
- Sorting is client-side in `static/app.js`; server still returns rows ordered by `creation_date DESC, id DESC`.
- Note textareas save on `blur`; size dropdowns and like/delete controls call row-specific APIs immediately.
- Existing stored HTML descriptions are stripped client-side before showing in the note textarea.
