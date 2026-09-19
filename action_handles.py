from __future__ import annotations

import os
import time
from typing import Any

import jwt

SECRET = os.environ.get("APP_SIGNING_SECRET", "").strip()
ISSUER = "meyora-unified-api"
AUDIENCE = "meyora-action-handle"


def _secret() -> str:
    if not SECRET:
        raise RuntimeError("APP_SIGNING_SECRET is not configured")
    return SECRET


def create_handle(*, claims: dict[str, Any], domain: str, payload: dict[str, Any], ttl_seconds: int = 900) -> str:
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl_seconds,
        "oid": claims.get("oid"),
        "tid": claims.get("tid"),
        "domain": domain,
        "payload": payload,
    }
    return jwt.encode(body, _secret(), algorithm="HS256")


def decode_handle(handle: str, claims: dict[str, Any]) -> dict[str, Any]:
    body = jwt.decode(
        handle,
        _secret(),
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    if body.get("oid") != claims.get("oid") or body.get("tid") != claims.get("tid"):
        raise ValueError("Action handle belongs to a different signed-in principal")
    return body
