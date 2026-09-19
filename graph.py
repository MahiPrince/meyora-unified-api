from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


def enabled() -> bool:
    return os.environ.get("GRAPH_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


async def obo_token(user_assertion: str) -> str:
    if not enabled():
        raise RuntimeError("Microsoft Graph is not enabled")
    tenant = os.environ["ENTRA_TENANT_ID"]
    client_id = os.environ["ENTRA_API_CLIENT_ID"]
    client_secret = os.environ["ENTRA_API_CLIENT_SECRET"]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "requested_token_use": "on_behalf_of",
                "assertion": user_assertion,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    if not response.is_success:
        raise RuntimeError(f"Graph OBO failed: {response.status_code} {response.text[:800]}")
    return response.json()["access_token"]


async def graph_get(user_assertion: str, path: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    token = await obo_token(user_assertion)
    h = {"Authorization": f"Bearer {token}"}
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{GRAPH_ROOT}{path}", params=params or {}, headers=h)
    if not response.is_success:
        raise RuntimeError(f"Graph GET {path} failed: {response.status_code} {response.text[:800]}")
    return response.json()


async def unread_mail(user_assertion: str, top: int = 10) -> dict[str, Any]:
    top = max(1, min(int(top), 25))
    return await graph_get(
        user_assertion,
        "/me/messages",
        params={
            "$filter": "isRead eq false",
            "$orderby": "receivedDateTime desc",
            "$top": str(top),
            "$select": "id,subject,from,receivedDateTime,isRead,importance,bodyPreview,webLink",
        },
    )


async def calendar_window(user_assertion: str, start: datetime, end: datetime, timezone_name: str = "UTC") -> dict[str, Any]:
    return await graph_get(
        user_assertion,
        "/me/calendarView",
        params={
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,location,organizer,isOnlineMeeting,onlineMeeting,webLink",
        },
        headers={"Prefer": f'outlook.timezone="{timezone_name}"'},
    )


async def calendar_today_utc(user_assertion: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return await calendar_window(user_assertion, start, start + timedelta(days=1), "UTC")
