"""Tenant identity resolution with a safe production mode and local fallback."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request

from ..config import settings
from ..runtime.store import DEFAULT_TENANT_ID
from ..services.auth_service import decode_access_token

_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _configured_keys() -> dict[str, str]:
    raw = settings.tenant_api_keys_json.strip()
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TENANT_API_KEYS_JSON must be a JSON object") from exc
    if not isinstance(mapping, dict):
        raise RuntimeError("TENANT_API_KEYS_JSON must be a JSON object")
    result = {str(key): str(value) for key, value in mapping.items() if key and value}
    if not all(_TENANT_PATTERN.fullmatch(tenant) for tenant in result.values()):
        raise RuntimeError("TENANT_API_KEYS_JSON contains an invalid tenant id")
    return result


@dataclass(frozen=True)
class RequestIdentity:
    tenant_id: str
    user_id: str | None = None
    role: str | None = None
    session_id: str | None = None
    method: str = "insecure"


def resolve_identity(request: Request, requested_tenant: str | None = None) -> RequestIdentity:
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="invalid_authorization_header")
        payload = decode_access_token(token)
        return RequestIdentity(**payload, method="bearer")

    cookie_token = request.cookies.get("gentrip_access_token")
    if cookie_token:
        payload = decode_access_token(cookie_token)
        return RequestIdentity(**payload, method="cookie")

    configured = _configured_keys()
    if configured:
        provided = request.headers.get("x-api-key", "")
        for api_key, tenant_id in configured.items():
            if secrets.compare_digest(provided, api_key):
                return RequestIdentity(tenant_id=tenant_id, method="api_key")
        raise HTTPException(status_code=401, detail="invalid_api_key")

    if settings.auth_enabled:
        raise HTTPException(status_code=401, detail="authentication_required")
    if not settings.allow_insecure_tenant_id:
        raise HTTPException(status_code=503, detail="tenant_auth_not_configured")
    return RequestIdentity(tenant_id=(requested_tenant or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID)


def resolve_tenant(request: Request, requested_tenant: str | None = None) -> str:
    """Compatibility helper for endpoints that only need the tenant scope."""
    return resolve_identity(request, requested_tenant).tenant_id
