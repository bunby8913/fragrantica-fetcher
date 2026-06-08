import os
import time
from functools import wraps

import jwt
import requests
from flask import jsonify, request
from jwt import PyJWKClient


_JWKS_CLIENT = None
_JWKS_CLIENT_EXPIRES_AT = 0
_JWKS_CACHE_SECONDS = 3600


def keycloak_config() -> dict:
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://192.168.0.49:8080").rstrip("/")
    realm = os.getenv("KEYCLOAK_REALM", "Bobarlie")
    client_id = os.getenv("KEYCLOAK_CLIENT_ID", "web_login")
    return {
        "keycloak_url": keycloak_url,
        "realm": realm,
        "client_id": client_id,
        "issuer": f"{keycloak_url}/realms/{realm}",
    }


def public_key_client() -> PyJWKClient:
    global _JWKS_CLIENT, _JWKS_CLIENT_EXPIRES_AT

    now = time.time()
    if _JWKS_CLIENT and now < _JWKS_CLIENT_EXPIRES_AT:
        return _JWKS_CLIENT

    config = keycloak_config()
    jwks_url = f"{config['issuer']}/protocol/openid-connect/certs"
    requests.get(jwks_url, timeout=5).raise_for_status()
    _JWKS_CLIENT = PyJWKClient(jwks_url)
    _JWKS_CLIENT_EXPIRES_AT = now + _JWKS_CACHE_SECONDS
    return _JWKS_CLIENT


def verify_token(token: str) -> dict:
    config = keycloak_config()
    signing_key = public_key_client().get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=config["issuer"],
        options={"verify_aud": False},
    )

    audiences = payload.get("aud", [])
    if isinstance(audiences, str):
        audiences = [audiences]

    if payload.get("azp") != config["client_id"] and config["client_id"] not in audiences:
        raise jwt.InvalidAudienceError("Token was not issued for this client")

    return payload


def exchange_code_for_tokens(code: str, code_verifier: str, redirect_uri: str):
    config = keycloak_config()
    token_url = f"{config['issuer']}/protocol/openid-connect/token"
    response = requests.post(
        token_url,
        data={
            "client_id": config["client_id"],
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    try:
        return response.json(), response.status_code
    except Exception:
        return {"error": "Invalid response from Keycloak"}, 502


def refresh_access_token(refresh_token_str: str):
    config = keycloak_config()
    token_url = f"{config['issuer']}/protocol/openid-connect/token"
    response = requests.post(
        token_url,
        data={
            "client_id": config["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_str,
        },
        timeout=10,
    )
    try:
        return response.json(), response.status_code
    except Exception:
        return {"error": "Invalid response from Keycloak"}, 502


def revoke_token(token_str: str):
    config = keycloak_config()
    revoke_url = f"{config['issuer']}/protocol/openid-connect/revoke"
    try:
        response = requests.post(
            revoke_url,
            data={
                "client_id": config["client_id"],
                "token": token_str,
                "token_type_hint": "refresh_token",
            },
            timeout=10,
        )
        return response.status_code in (200, 204)
    except requests.RequestException:
        return False


def require_auth(route):
    @wraps(route)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return jsonify({"error": "Missing bearer token"}), 401

        try:
            request.keycloak_user = verify_token(token)
        except (jwt.PyJWTError, requests.RequestException) as exc:
            return jsonify({"error": f"Invalid bearer token: {exc}"}), 401

        return route(*args, **kwargs)

    return wrapped
