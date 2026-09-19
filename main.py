from __future__ import annotations

import hashlib
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from action_handles import create_handle, decode_handle
from auth import authenticated_request
from graph import calendar_today_utc, enabled as graph_enabled, unread_mail
from principals import Principal, resolve_principal
from proxy import FIELD_URL, SALES_URL, field, sales

app = FastAPI(title="Meyora Unified API", version="0.1.0")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="mobile", min_length=1, max_length=120)
    history: list[dict[str, Any]] | None = None
    client_context: dict[str, Any] | None = None


class ActionRequest(BaseModel):
    handle: str = Field(min_length=10)


def _principal_or_403(claims: dict[str, Any]) -> Principal:
    principal = resolve_principal(claims)
    if not principal:
        raise HTTPException(status_code=403, detail="meyora_principal_not_registered")
    return principal


def _namespace_session(principal: Principal, session_id: str) -> str:
    digest = hashlib.sha256(principal.principal_id.encode("utf-8")).hexdigest()[:10]
    clean = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_:")[:80] or "mobile"
    return f"{digest}:{clean}"


def _base_response(data: dict[str, Any], principal: Principal) -> dict[str, Any]:
    result = dict(data)
    result["domain"] = principal.domain
    result["principal"] = principal.public()
    return result


def _normalize_sales_actions(data: dict[str, Any], claims: dict[str, Any], principal: Principal) -> dict[str, Any]:
    token = data.pop("confirmation_token", None)
    raw_actions = data.get("pending_actions") or []
    if not token:
        return data

    handle = create_handle(
        claims=claims,
        domain="sales",
        payload={"kind": "salesforce_confirmation", "confirmation_token": token},
    )
    data["pending_actions"] = [{
        "id": "salesforce-write-group",
        "action_type": "salesforce_write",
        "source": "Salesforce",
        "preview": {"kind": "salesforce", "changes": raw_actions},
        "handle": handle,
        "confirm_label": "Confirm changes",
    }]
    data["confirmation_required"] = True
    return data


def _normalize_field_actions(data: dict[str, Any], claims: dict[str, Any], principal: Principal, namespaced_session: str) -> dict[str, Any]:
    normalized = []
    for raw in data.get("pending_actions") or []:
        action_id = raw.get("id")
        if not action_id:
            continue
        handle = create_handle(
            claims=claims,
            domain="field_service",
            payload={
                "kind": "field_action",
                "action_id": action_id,
                "session_id": namespaced_session,
            },
        )
        item = dict(raw)
        item.pop("id", None)
        item["id"] = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:12]
        item["handle"] = handle
        normalized.append(item)
    data["pending_actions"] = normalized
    data["confirmation_required"] = bool(normalized)
    return data


@app.get("/")
def root():
    return {
        "name": "Meyora Unified API",
        "version": "0.1.0",
        "architecture": "identity + policy facade over proven Sales and Field Service backends",
        "sales_backend": SALES_URL,
        "field_backend": FIELD_URL,
    }


@app.get("/health")
async def health():
    sales_status, sales_data = await sales("GET", "/health", timeout=20)
    field_status, field_data = await field("GET", "/health", timeout=20)
    return {
        "ok": 200 <= sales_status < 500 and 200 <= field_status < 500,
        "version": "0.1.0",
        "sales": {
            "reachable": sales_status < 500,
            "status": sales_status,
            "version": sales_data.get("version") if isinstance(sales_data, dict) else None,
        },
        "field_service": {
            "reachable": field_status < 500,
            "status": field_status,
            "ok": field_data.get("ok") if isinstance(field_data, dict) else None,
        },
        "graph_enabled": graph_enabled(),
    }


@app.get("/me")
async def me(request: Request):
    _, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    return {
        "authenticated": True,
        "principal": principal.public(),
        "entra": {
            "name": claims.get("name"),
            "username": claims.get("preferred_username"),
            "oid": claims.get("oid"),
            "tenant_id": claims.get("tid"),
        },
    }


@app.get("/connectors")
async def connectors(request: Request):
    _, claims = authenticated_request(request)
    principal = _principal_or_403(claims)

    if principal.domain == "field_service":
        status, data = await field("GET", "/connectors", timeout=30)
        if status >= 400:
            raise HTTPException(status_code=502, detail={"downstream": "field_service", "response": data})
        connections = []
        for item in data.get("connections") or []:
            x = dict(item)
            x["mode"] = "mock"
            connections.append(x)
        return {"domain": principal.domain, "connections": connections}

    connections = [
        {"display_name": "Salesforce", "connector_id": "salesforce", "status": "connected", "mode": "real"}
    ]
    for name, cid in [("Microsoft Outlook", "outlook"), ("Outlook Calendar", "calendar")]:
        connections.append({
            "display_name": name,
            "connector_id": cid,
            "status": "connected" if graph_enabled() else "not_configured",
            "mode": "real",
        })
    connections.append({
        "display_name": "Microsoft Teams",
        "connector_id": "teams",
        "status": "planned",
        "mode": "real",
    })
    return {"domain": principal.domain, "connections": connections}


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    token, claims = authenticated_request(request)
    principal = _principal_or_403(claims)

    if principal.domain == "sales":
        payload: dict[str, Any] = {"message": body.message}
        if body.history is not None:
            payload["history"] = body.history
        if body.client_context is not None:
            payload["client_context"] = body.client_context
        status, data = await sales("POST", "/chat", body=payload, bearer=token, timeout=120)
        if status >= 400:
            raise HTTPException(
                status_code=status if status < 500 else 502,
                detail={"downstream": "sales", "response": data},
            )
        data = _normalize_sales_actions(dict(data), claims, principal)
        return _base_response(data, principal)

    if principal.domain == "field_service":
        namespaced = _namespace_session(principal, body.session_id)
        status, data = await field(
            "POST",
            "/chat",
            body={"message": body.message, "session_id": namespaced},
            timeout=120,
        )
        if status >= 400:
            raise HTTPException(
                status_code=status if status < 500 else 502,
                detail={"downstream": "field_service", "response": data},
            )
        data = _normalize_field_actions(dict(data), claims, principal, namespaced)
        data["session_id"] = body.session_id
        return _base_response(data, principal)

    raise HTTPException(status_code=403, detail="unsupported_domain")


@app.post("/actions/confirm")
async def confirm_action(body: ActionRequest, request: Request):
    token, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    try:
        decoded = decode_handle(body.handle, claims)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_action_handle: {exc}") from exc

    if decoded.get("domain") != principal.domain:
        raise HTTPException(status_code=403, detail="action_domain_mismatch")

    payload = decoded.get("payload") or {}

    if payload.get("kind") == "salesforce_confirmation" and principal.domain == "sales":
        status, data = await sales(
            "POST",
            "/confirm",
            body={"confirmation_token": payload["confirmation_token"]},
            bearer=token,
            timeout=90,
        )
    elif payload.get("kind") == "field_action" and principal.domain == "field_service":
        status, data = await field(
            "POST",
            f"/actions/{payload['action_id']}/confirm",
            body={"session_id": payload["session_id"]},
            timeout=90,
        )
    else:
        raise HTTPException(status_code=400, detail="unsupported_action_handle")

    if status >= 400:
        raise HTTPException(status_code=status if status < 500 else 502, detail=data)
    return {"ok": True, "domain": principal.domain, "result": data}


@app.post("/actions/cancel")
async def cancel_action(body: ActionRequest, request: Request):
    _, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    try:
        decoded = decode_handle(body.handle, claims)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_action_handle: {exc}") from exc

    if decoded.get("domain") != principal.domain:
        raise HTTPException(status_code=403, detail="action_domain_mismatch")

    payload = decoded.get("payload") or {}

    if payload.get("kind") == "salesforce_confirmation" and principal.domain == "sales":
        return {"ok": True, "domain": "sales", "status": "canceled"}

    if payload.get("kind") == "field_action" and principal.domain == "field_service":
        status, data = await field(
            "POST",
            f"/actions/{payload['action_id']}/cancel",
            body={"session_id": payload["session_id"]},
            timeout=60,
        )
        if status >= 400:
            raise HTTPException(status_code=status if status < 500 else 502, detail=data)
        return {"ok": True, "domain": "field_service", "result": data}

    raise HTTPException(status_code=400, detail="unsupported_action_handle")


@app.get("/salesforce/me")
async def salesforce_me(request: Request):
    token, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    if principal.domain != "sales":
        raise HTTPException(status_code=403, detail="sales_capability_not_allowed")
    status, data = await sales("GET", "/salesforce/me", bearer=token, timeout=45)
    if status >= 400:
        raise HTTPException(status_code=status if status < 500 else 502, detail=data)
    return data


@app.get("/field/my-day")
async def field_my_day(request: Request):
    _, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    if principal.domain != "field_service":
        raise HTTPException(status_code=403, detail="field_service_capability_not_allowed")
    status, data = await field("GET", "/my-day", timeout=45)
    if status >= 400:
        raise HTTPException(status_code=502, detail=data)
    return data


@app.get("/m365/mail/unread")
async def m365_unread_mail(request: Request, top: int = 10):
    token, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    if "outlook" not in principal.connectors:
        raise HTTPException(status_code=403, detail="outlook_capability_not_allowed")
    try:
        return await unread_mail(token, top=top)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/m365/calendar/today")
async def m365_calendar_today(request: Request):
    token, claims = authenticated_request(request)
    principal = _principal_or_403(claims)
    if "calendar" not in principal.connectors:
        raise HTTPException(status_code=403, detail="calendar_capability_not_allowed")
    try:
        return await calendar_today_utc(token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
