from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

SALES_URL = os.environ.get("SALES_BACKEND_URL", "https://cloudaiapi01.onrender.com").rstrip("/")
FIELD_URL = os.environ.get("FIELD_BACKEND_URL", "https://meyora-field-demo-api.onrender.com").rstrip("/")

TRANSIENT_EDGE_STATUSES = {502, 503, 504}


def _non_json_payload(response: httpx.Response) -> dict[str, Any]:
    text = (response.text or "").strip()
    preview = "HTML gateway response" if text.lower().startswith(("<!doctype html", "<html")) else text[:240]
    return {
        "error": "non_json_downstream_response",
        "status": response.status_code,
        "message": "Downstream service returned a non-JSON response.",
        "body_preview": preview,
    }


async def request_json(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    bearer: str | None = None,
    timeout: float = 75.0,
    retry_transient: bool = False,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    attempts = 3 if retry_transient else 1
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, headers=headers, json=json_body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            if retry_transient and attempt < attempts - 1:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            return 503, {
                "error": "downstream_unavailable",
                "message": "Downstream service is temporarily unavailable.",
                "type": type(exc).__name__,
            }
        except httpx.TimeoutException as exc:
            return 504, {
                "error": "downstream_timeout",
                "message": "Downstream service took too long to respond. Please retry.",
                "type": type(exc).__name__,
            }
        except httpx.RequestError as exc:
            return 503, {
                "error": "downstream_request_error",
                "message": "Could not reach the downstream service.",
                "type": type(exc).__name__,
            }

        try:
            data = response.json()
        except Exception:
            data = _non_json_payload(response)

        retryable = (
            response.status_code in TRANSIENT_EDGE_STATUSES
            and isinstance(data, dict)
            and data.get("error") == "non_json_downstream_response"
        )
        if retry_transient and attempt < attempts - 1 and retryable:
            await asyncio.sleep(2.0 * (attempt + 1))
            continue

        return response.status_code, data

    return 503, {
        "error": "downstream_unavailable",
        "message": "Downstream service is temporarily unavailable.",
    }


async def sales(method: str, path: str, *, body: Any = None, bearer: str | None = None, timeout: float = 75.0):
    return await request_json(
        method,
        f"{SALES_URL}{path}",
        json_body=body,
        bearer=bearer,
        timeout=timeout,
        retry_transient=False,
    )


async def field(method: str, path: str, *, body: Any = None, timeout: float = 75.0):
    # Safe retry scope: read-only GETs and conversational /chat requests.
    # Governed confirm/cancel writes are deliberately never retried automatically.
    retry_transient = method.upper() == "GET" or path == "/chat"
    return await request_json(
        method,
        f"{FIELD_URL}{path}",
        json_body=body,
        timeout=timeout,
        retry_transient=retry_transient,
    )
