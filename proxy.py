from __future__ import annotations

import os
from typing import Any

import httpx

SALES_URL = os.environ.get("SALES_BACKEND_URL", "https://cloudaiapi01.onrender.com").rstrip("/")
FIELD_URL = os.environ.get("FIELD_BACKEND_URL", "https://meyora-field-demo-api.onrender.com").rstrip("/")


async def request_json(method: str, url: str, *, json_body: Any = None, bearer: str | None = None, timeout: float = 75.0) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=headers, json=json_body)
    try:
        data = response.json()
    except Exception:
        data = {"error": "non_json_downstream_response", "body": response.text[:2000]}
    return response.status_code, data


async def sales(method: str, path: str, *, body: Any = None, bearer: str | None = None, timeout: float = 75.0):
    return await request_json(method, f"{SALES_URL}{path}", json_body=body, bearer=bearer, timeout=timeout)


async def field(method: str, path: str, *, body: Any = None, timeout: float = 75.0):
    return await request_json(method, f"{FIELD_URL}{path}", json_body=body, timeout=timeout)
