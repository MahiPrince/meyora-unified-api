from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
API_CLIENT_ID = os.environ.get("ENTRA_API_CLIENT_ID", "").strip()
REQUIRED_SCOPE = os.environ.get("ENTRA_REQUIRED_SCOPE", "access_as_user").strip()


def _require_config() -> None:
    if not TENANT_ID or not API_CLIENT_ID:
        raise RuntimeError("ENTRA_TENANT_ID and ENTRA_API_CLIENT_ID must be configured")


@lru_cache(maxsize=1)
def jwks_client() -> PyJWKClient:
    _require_config()
    return PyJWKClient(
        f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
    )


def verify_access_token(token: str) -> dict[str, Any]:
    _require_config()
    key = jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],
        audience=API_CLIENT_ID,
        issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
    )
    scopes = set((claims.get("scp") or "").split())
    if REQUIRED_SCOPE and REQUIRED_SCOPE not in scopes:
        raise ValueError(f"Required scope {REQUIRED_SCOPE} is missing")
    return claims


def bearer_from_request(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    return header.split(" ", 1)[1].strip()


def authenticated_request(request: Request) -> tuple[str, dict[str, Any]]:
    token = bearer_from_request(request)
    try:
        claims = verify_access_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid_token: {exc}") from exc
    return token, claims
