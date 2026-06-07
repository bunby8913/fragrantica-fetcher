import json
from datetime import date
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from db import add_perfume, get_all_perfumes, run_migrations, toggle_like
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
    return render_template("index.html")


@app.get("/get_all_perfume")
def get_all_perfume():
    perfumes = [_json_ready(row) for row in get_all_perfumes()]
    return jsonify(perfumes)


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

    row = add_perfume(
        name=data.get("name", ""),
        brand=data.get("brand", ""),
        pyramid_data=json.dumps(data.get("pyramid", {})),
        description=data.get("description", ""),
        original_address=url,
    )
    return jsonify(_json_ready(row)), 201


@app.put("/perfume/<int:perfume_id>/like")
def toggle_like_api(perfume_id: int):
    row = toggle_like(perfume_id)
    if not row:
        return jsonify({"error": "Perfume not found"}), 404
    return jsonify(_json_ready(row))


def create_app() -> Flask:
    run_migrations()
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
