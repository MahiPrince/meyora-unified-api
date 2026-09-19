from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    role: str
    domain: str
    connectors: tuple[str, ...]
    connector_modes: dict[str, str]
    oid: str | None = None
    username: str | None = None

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("oid", None)
        data.pop("username", None)
        data["connectors"] = list(self.connectors)
        return data


def _load_registry() -> list[Principal]:
    raw = os.environ.get("MEYORA_PRINCIPALS_JSON", "[]")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MEYORA_PRINCIPALS_JSON is invalid JSON") from exc
    if not isinstance(parsed, list):
        raise RuntimeError("MEYORA_PRINCIPALS_JSON must be a JSON array")

    out: list[Principal] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        match = item.get("match") or {}
        connectors = tuple(item.get("connectors") or [])
        modes = dict(item.get("connector_modes") or {})
        out.append(
            Principal(
                principal_id=str(item["principal_id"]),
                display_name=str(item.get("display_name") or item["principal_id"]),
                role=str(item.get("role") or "User"),
                domain=str(item["domain"]),
                connectors=connectors,
                connector_modes=modes,
                oid=(str(match.get("oid")).strip() if match.get("oid") else None),
                username=(str(match.get("username")).strip().lower() if match.get("username") else None),
            )
        )
    return out


def resolve_principal(claims: dict[str, Any]) -> Principal | None:
    oid = str(claims.get("oid") or "").strip()
    username = str(claims.get("preferred_username") or "").strip().lower()
    registry = _load_registry()

    if oid:
        for principal in registry:
            if principal.oid and principal.oid == oid:
                return principal

    if username:
        for principal in registry:
            if principal.username and principal.username == username:
                return principal
    return None
