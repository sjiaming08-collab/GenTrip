"""Identity records used by local multi-tenant authentication."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    user_id: str
    email: str
    display_name: str
    password_hash: str
    is_active: bool = True


class TenantMembership(BaseModel):
    tenant_id: str
    user_id: str
    role: str = Field(pattern=r"^(owner|member)$")
    tenant_name: str = ""


class AuthIdentity(BaseModel):
    user: AuthUser
    membership: TenantMembership


class TenantMember(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str = Field(pattern=r"^(owner|member)$")
