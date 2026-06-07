import json
from datetime import date
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from db import (
    DuplicatePerfumeError,
    add_perfume,
    add_to_wishlist,
    delete_from_wishlist,
    delete_perfume,
    get_all_perfumes,
    get_wishlist,
    move_to_library,
    run_migrations,
    toggle_like,
    update_note,
    update_size,
)
from scraper import extract_perfume_data, fetch_page


load_dotenv()

app = Flask(__name__)


def _json_ready(row: dict) -> dict:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, date):
            result[key] = value.isoformat()
    return result


def _is_valid_fragrantica_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and (hostname == "fragrantica.com" or hostname.endswith(".fragrantica.com"))
        and "/perfume/" in parsed.path
    )


@app.route("/")
def index():
    return render_template("index.html", page="library")


@app.route("/wishlist")
def wishlist():
    return render_template("index.html", page="wishlist")


@app.get("/get_all_perfume")
def get_all_perfume():
    perfumes = [_json_ready(row) for row in get_all_perfumes()]
    return jsonify(perfumes)


@app.get("/get_wishlist")
def get_wishlist_api():
    wishlist_entries = [_json_ready(row) for row in get_wishlist()]
    return jsonify(wishlist_entries)


@app.post("/add_perfume")
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

    try:
        row = add_perfume(
            name=data.get("name", ""),
            brand=data.get("brand", ""),
            pyramid_data=json.dumps(data.get("pyramid", {})),
            original_address=url,
        )
    except DuplicatePerfumeError:
        return jsonify({"error": "A perfume with the same name and brand already exists"}), 409

    return jsonify(_json_ready(row)), 201


@app.post("/add_to_wishlist")
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

    try:
        row = add_to_wishlist(
            name=data.get("name", ""),
            brand=data.get("brand", ""),
            pyramid_data=json.dumps(data.get("pyramid", {})),
            original_address=url,
        )
    except DuplicatePerfumeError:
        return jsonify({"error": "A wishlist item with the same name and brand already exists"}), 409

    return jsonify(_json_ready(row)), 201


@app.put("/perfume/<int:perfume_id>/like")
def toggle_like_api(perfume_id: int):
    row = toggle_like(perfume_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/perfume/<int:perfume_id>/note")
def update_note_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    note = str(payload.get("note", ""))

    row = update_note(perfume_id, note)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.put("/perfume/<int:perfume_id>/size")
def update_size_api(perfume_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        size = int(payload.get("size"))
    except (TypeError, ValueError):
        return jsonify({"error": "Size must be 0, 1, 2, or 3"}), 400

    if size not in {0, 1, 2, 3}:
        return jsonify({"error": "Size must be 0, 1, 2, or 3"}), 400

    row = update_size(perfume_id, size)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


@app.delete("/perfume/<int:perfume_id>")
def delete_perfume_api(perfume_id: int):
    if not delete_perfume(perfume_id):
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify({"success": True})


@app.post("/wishlist/<int:wishlist_id>/move")
def move_wishlist_item_api(wishlist_id: int):
    try:
        row = move_to_library(wishlist_id)
    except DuplicatePerfumeError:
        return jsonify({"error": "A perfume with the same name and brand already exists"}), 409

    if not row:
        return jsonify({"error": "Wishlist item not found"}), 404
    return jsonify(_json_ready(row))


@app.delete("/wishlist/<int:wishlist_id>")
def delete_wishlist_item_api(wishlist_id: int):
    if not delete_from_wishlist(wishlist_id):
        return jsonify({"error": "Wishlist item not found"}), 404
    return jsonify({"success": True})


def create_app() -> Flask:
    run_migrations()
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
