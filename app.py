import json
import os
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory

from auth import (
    exchange_code_for_tokens,
    keycloak_config,
    refresh_access_token,
    require_auth,
    revoke_token,
)
from db import (
    DuplicatePerfumeError,
    add_perfume,
    add_to_wishlist,
    delete_from_wishlist,
    delete_perfume,
    get_all_perfumes,
    get_archived_perfumes,
    get_note_profile,
    get_or_create_user,
    get_wishlist,
    move_to_library,
    run_migrations,
    update_perfume_details,
    update_rating,
    update_note,
    update_size,
    update_wishlist_details,
)
from enricher import (
    backfill_note_profiles,
    collect_unique_note_ids,
    enrich_notes_with_odor_profiles,
    enrich_single_note,
    missing_note_ids,
)
from scraper import extract_perfume_data, fetch_page


load_dotenv()

app = Flask(__name__)


def _json_ready(row: dict) -> dict:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, date):
            result[key] = value.isoformat()
        elif isinstance(value, Decimal):
            result[key] = int(value) if value == value.to_integral_value() else float(value)
    return result


def _is_valid_fragrantica_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and (hostname == "fragrantica.com" or hostname.endswith(".fragrantica.com"))
        and "/perfume/" in parsed.path
    )


def _get_user_id() -> int:
    keycloak_uuid = request.keycloak_user.get("sub", "")
    return get_or_create_user(keycloak_uuid)


def _parse_pyramid_data(pyramid_data) -> dict:
    if not pyramid_data:
        return {}
    if isinstance(pyramid_data, dict):
        return pyramid_data
    try:
        return json.loads(pyramid_data)
    except (TypeError, ValueError):
        return {}


def _all_user_pyramids(user_id: int) -> list[dict]:
    pyramids: list[dict] = []
    for row in get_all_perfumes(user_id):
        pyramid = _parse_pyramid_data(row.get("pyramid_data"))
        if pyramid:
            pyramids.append(pyramid)
    for row in get_wishlist(user_id):
        pyramid = _parse_pyramid_data(row.get("pyramid_data"))
        if pyramid:
            pyramids.append(pyramid)
    return pyramids


@app.route("/")
def index():
    return render_template("index.html", page="library")


@app.route("/wishlist")
def wishlist():
    return render_template("index.html", page="wishlist")


@app.route("/archive")
def archive():
    return render_template("index.html", page="archive")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/callback")
def callback():
    return render_template("callback.html")


@app.get("/assets/<path:filename>")
def assets(filename: str):
    return send_from_directory(os.path.join(app.root_path, "assets"), filename)


@app.get("/auth/config")
def auth_config():
    config = keycloak_config()
    return jsonify(
        {
            "keycloakUrl": config["keycloak_url"],
            "realm": config["realm"],
            "clientId": config["client_id"],
        }
    )


@app.post("/auth/token")
def auth_token():
    payload = request.get_json(silent=True) or {}
    grant_type = str(payload.get("grant_type", ""))

    if grant_type == "authorization_code":
        code = str(payload.get("code", ""))
        code_verifier = str(payload.get("code_verifier", ""))
        redirect_uri = str(payload.get("redirect_uri", ""))
        if not code or not code_verifier or not redirect_uri:
            return jsonify({"error": "Missing code, code_verifier, or redirect_uri"}), 400
        data, status = exchange_code_for_tokens(code, code_verifier, redirect_uri)
    elif grant_type == "refresh_token":
        refresh_token_str = str(payload.get("refresh_token", ""))
        if not refresh_token_str:
            return jsonify({"error": "Missing refresh_token"}), 400
        data, status = refresh_access_token(refresh_token_str)
    else:
        return jsonify({"error": "Invalid grant_type"}), 400

    if status >= 400:
        error_msg = data.get("error_description") or data.get("error") or "Token request failed"
        return jsonify({"error": error_msg}), status
    return jsonify(data), status


@app.post("/auth/logout")
def auth_logout():
    payload = request.get_json(silent=True) or {}
    refresh_token_str = str(payload.get("refresh_token", ""))
    if refresh_token_str:
        revoke_token(refresh_token_str)
    return jsonify({"success": True})


@app.get("/get_all_perfume")
@require_auth
def get_all_perfume():
    user_id = _get_user_id()
    perfumes = [_json_ready(row) for row in get_all_perfumes(user_id)]
    return jsonify(perfumes)


@app.get("/get_archived_perfumes")
@require_auth
def get_archived_perfumes_api():
    user_id = _get_user_id()
    perfumes = [_json_ready(row) for row in get_archived_perfumes(user_id)]
    return jsonify(perfumes)


@app.get("/get_wishlist")
@require_auth
def get_wishlist_api():
    user_id = _get_user_id()
    wishlist_entries = [_json_ready(row) for row in get_wishlist(user_id)]
    return jsonify(wishlist_entries)


@app.post("/add_perfume")
@require_auth
def add_perfume_api():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    if not _is_valid_fragrantica_url(url):
        return jsonify({"error": "URL must be a fragrantica.com perfume page"}), 400

    try:
        html = fetch_page(url)
        data = extract_perfume_data(html, url)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch perfume data: {exc}"}), 502

    if not data.get("name"):
        return jsonify({"error": "Could not extract perfume name from page"}), 422

    pyramid = data.get("pyramid", {}) or {}
    try:
        enrich_notes_with_odor_profiles(pyramid)
    except Exception:
        for level in ("top_notes", "middle_notes", "base_notes"):
            for note in pyramid.get(level, []) or []:
                note.setdefault("odor_profile", "")

    try:
        user_id = _get_user_id()
        row = add_perfume(
            name=data.get("name", ""),
            brand=data.get("brand", ""),
            pyramid_data=json.dumps(pyramid),
            original_address=url,
            user_id=user_id,
        )
    except DuplicatePerfumeError:
        return jsonify({"error": "A perfume with the same name and brand already exists"}), 409

    return jsonify(_json_ready(row)), 201


@app.post("/add_to_wishlist")
@require_auth
def add_to_wishlist_api():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    if not _is_valid_fragrantica_url(url):
        return jsonify({"error": "URL must be a fragrantica.com perfume page"}), 400

    try:
        html = fetch_page(url)
        data = extract_perfume_data(html, url)
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch perfume data: {exc}"}), 502

    if not data.get("name"):
        return jsonify({"error": "Could not extract perfume name from page"}), 422

    pyramid = data.get("pyramid", {}) or {}
    try:
        enrich_notes_with_odor_profiles(pyramid)
    except Exception:
        for level in ("top_notes", "middle_notes", "base_notes"):
            for note in pyramid.get(level, []) or []:
                note.setdefault("odor_profile", "")

    try:
        user_id = _get_user_id()
        row = add_to_wishlist(
            name=data.get("name", ""),
            brand=data.get("brand", ""),
            pyramid_data=json.dumps(pyramid),
            original_address=url,
            user_id=user_id,
        )
    except DuplicatePerfumeError:
        return jsonify({"error": "A wishlist item with the same name and brand already exists"}), 409

    return jsonify(_json_ready(row)), 201


@app.put("/perfume/<int:perfume_id>/rating")
@require_auth
def update_rating_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    rating_value = payload.get("rating")
    if isinstance(rating_value, bool) or (
        isinstance(rating_value, float) and not rating_value.is_integer()
    ):
        return jsonify({"error": "Rating must be a whole number from 0 to 5"}), 400

    try:
        rating = int(rating_value)
    except (TypeError, ValueError):
        return jsonify({"error": "Rating must be a whole number from 0 to 5"}), 400

    if rating not in {0, 1, 2, 3, 4, 5}:
        return jsonify({"error": "Rating must be a whole number from 0 to 5"}), 400

    user_id = _get_user_id()
    row = update_rating(perfume_id, rating, user_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/perfume/<int:perfume_id>/note")
@require_auth
def update_note_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    note = str(payload.get("note", ""))

    user_id = _get_user_id()
    row = update_note(perfume_id, note, user_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/perfume/<int:perfume_id>/size")
@require_auth
def update_size_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        size = int(payload.get("size"))
    except (TypeError, ValueError):
        return jsonify({"error": "Size must be 0, 1, 2, or 3"}), 400

    if size not in {0, 1, 2, 3}:
        return jsonify({"error": "Size must be 0, 1, 2, or 3"}), 400

    user_id = _get_user_id()
    row = update_size(perfume_id, size, user_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/perfume/<int:perfume_id>/details")
@require_auth
def update_perfume_details_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    brand = str(payload.get("brand", "")).strip()
    pyramid_data = payload.get("pyramid_data", {})

    if not name or not brand:
        return jsonify({"error": "Name and brand are required"}), 400
    if not isinstance(pyramid_data, str):
        pyramid_data = json.dumps(pyramid_data)

    user_id = _get_user_id()
    row = update_perfume_details(perfume_id, name, brand, pyramid_data, user_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.delete("/perfume/<int:perfume_id>")
@require_auth
def delete_perfume_api(perfume_id: int):
    user_id = _get_user_id()
    if not delete_perfume(perfume_id, user_id):
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify({"success": True})


@app.post("/wishlist/<int:wishlist_id>/move")
@require_auth
def move_wishlist_item_api(wishlist_id: int):
    user_id = _get_user_id()
    try:
        row = move_to_library(wishlist_id, user_id)
    except DuplicatePerfumeError:
        return jsonify({"error": "A perfume with the same name and brand already exists"}), 409

    if not row:
        return jsonify({"error": "Wishlist item not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/wishlist/<int:wishlist_id>/details")
@require_auth
def update_wishlist_details_api(wishlist_id: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    brand = str(payload.get("brand", "")).strip()
    pyramid_data = payload.get("pyramid_data", {})

    if not name or not brand:
        return jsonify({"error": "Name and brand are required"}), 400
    if not isinstance(pyramid_data, str):
        pyramid_data = json.dumps(pyramid_data)

    user_id = _get_user_id()
    row = update_wishlist_details(wishlist_id, name, brand, pyramid_data, user_id)
    if not row:
        return jsonify({"error": "Wishlist item not found"}), 404
    return jsonify(_json_ready(row))


@app.delete("/wishlist/<int:wishlist_id>")
@require_auth
def delete_wishlist_item_api(wishlist_id: int):
    user_id = _get_user_id()
    if not delete_from_wishlist(wishlist_id, user_id):
        return jsonify({"error": "Wishlist item not found"}), 404
    return jsonify({"success": True})


@app.get("/note_profile/<note_id>")
@require_auth
def get_note_profile_api(note_id: str):
    profile = get_note_profile(note_id)
    if not profile:
        return jsonify({"note_id": note_id, "odor_profile": ""}), 200
    return jsonify(_json_ready(profile))


@app.post("/enrich_note")
@require_auth
def enrich_note_api():
    payload = request.get_json(silent=True) or {}
    note_id = str(payload.get("note_id", "")).strip()
    note_name = str(payload.get("note_name", "")).strip()
    note_url = str(payload.get("note_url", "")).strip()

    if not note_id:
        return jsonify({"error": "note_id is required"}), 400

    odor_profile = enrich_single_note(
        note_id=note_id,
        note_name=note_name,
        note_url=note_url,
    )
    return jsonify({"note_id": note_id, "odor_profile": odor_profile})


@app.get("/note_profiles/missing")
@require_auth
def get_missing_note_ids_api():
    user_id = _get_user_id()
    pyramids = _all_user_pyramids(user_id)
    return jsonify({"missing": missing_note_ids(pyramids)})


@app.post("/backfill_note_profiles")
@require_auth
def backfill_note_profiles_api():
    user_id = _get_user_id()
    pyramids = _all_user_pyramids(user_id)
    note_ids = collect_unique_note_ids(pyramids)
    added = backfill_note_profiles(pyramids)
    return jsonify({"checked": len(note_ids), "added": added})


def create_app() -> Flask:
    run_migrations()
    return app


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    create_app().run(host="0.0.0.0", port=5000, debug=debug)
