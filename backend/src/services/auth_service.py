"""Password verification and signed access-token issuance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import uuid

import jwt
from fastapi import HTTPException
from pwdlib import PasswordHash

from ..config import settings
from ..models.auth import AuthIdentity, AuthUser, TenantMember, TenantMembership
from ..runtime.store import RuntimeStore

_PASSWORD_HASH = PasswordHash.recommended()
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEV_SECRET = "gentrip-local-development-secret-change-before-production"


class AuthService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    @staticmethod
    def normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise HTTPException(status_code=422, detail="invalid_email")
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if not 12 <= len(password) <= 128:
            raise HTTPException(status_code=422, detail="password_length_must_be_12_to_128")

    async def register(self, email: str, password: str, display_name: str, tenant_name: str) -> AuthIdentity:
        if not settings.auth_allow_registration:
            raise HTTPException(status_code=403, detail="registration_disabled")
        normalized = self.normalize_email(email)
        self.validate_password(password)
        existing = await self._store.load_auth_user_by_email(normalized)
        if existing is not None:
            raise HTTPException(status_code=409, detail="email_already_registered")
        user = AuthUser(
            user_id=str(uuid.uuid4()),
            email=normalized,
            display_name=(display_name.strip() or normalized.split("@", 1)[0])[:80],
            password_hash=_PASSWORD_HASH.hash(password),
        )
        membership = TenantMembership(
            tenant_id=str(uuid.uuid4()),
            user_id=user.user_id,
            role="owner",
            tenant_name=(tenant_name.strip() or f"{user.display_name} workspace")[:80],
        )
        await self._store.create_auth_identity(user, membership)
        return AuthIdentity(user=user, membership=membership)

    async def authenticate(self, email: str, password: str, tenant_id: str | None = None) -> AuthIdentity:
        normalized = self.normalize_email(email)
        user = await self._store.load_auth_user_by_email(normalized)
        if user is None or not user.is_active or not _PASSWORD_HASH.verify(password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        membership = await self._store.load_auth_membership(user.user_id, tenant_id)
        if membership is None:
            raise HTTPException(status_code=403, detail="tenant_membership_not_found")
        return AuthIdentity(user=user, membership=membership)

    async def load_identity(self, user_id: str, tenant_id: str) -> AuthIdentity:
        """Re-check the database so disabled users and removed memberships lose access."""
        user = await self._store.load_auth_user_by_id(user_id)
        membership = await self._store.load_auth_membership(user_id, tenant_id)
        if user is None or not user.is_active or membership is None:
            raise HTTPException(status_code=401, detail="identity_no_longer_active")
        return AuthIdentity(user=user, membership=membership)

    async def list_workspaces(self, user_id: str) -> list[TenantMembership]:
        return await self._store.list_auth_memberships(user_id)

    async def list_members(self, tenant_id: str) -> list[TenantMember]:
        return await self._store.list_tenant_members(tenant_id)

    async def add_member(self, tenant_id: str, email: str, role: str) -> TenantMember:
        user = await self._store.load_auth_user_by_email(self.normalize_email(email))
        if user is None or not user.is_active:
            raise HTTPException(status_code=404, detail="user_not_found")
        try:
            await self._store.add_tenant_member(tenant_id, user.user_id, role)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return TenantMember(user_id=user.user_id, email=user.email, display_name=user.display_name, role=role)

    async def update_member_role(self, tenant_id: str, user_id: str, role: str) -> None:
        outcome = await self._store.update_tenant_member_role(tenant_id, user_id, role)
        if outcome == "membership_not_found":
            raise HTTPException(status_code=404, detail=outcome)
        if outcome == "last_owner":
            raise HTTPException(status_code=422, detail="tenant_requires_owner")

    async def remove_member(self, tenant_id: str, user_id: str) -> None:
        outcome = await self._store.remove_tenant_member(tenant_id, user_id)
        if outcome == "membership_not_found":
            raise HTTPException(status_code=404, detail=outcome)
        if outcome == "last_owner":
            raise HTTPException(status_code=422, detail="tenant_requires_owner")

    @staticmethod
    def _secret() -> str:
        return settings.auth_jwt_secret or _DEV_SECRET

    async def issue_access_token(self, identity: AuthIdentity) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.auth_access_token_minutes)
        session_id = str(uuid.uuid4())
        await self._store.create_auth_session(
            session_id, identity.user.user_id, identity.membership.tenant_id, expires_at.isoformat()
        )
        return jwt.encode(
            {
                "sub": identity.user.user_id,
                "tenant_id": identity.membership.tenant_id,
                "role": identity.membership.role,
                "jti": session_id,
                "exp": expires_at,
                "iat": datetime.now(timezone.utc),
            },
            self._secret(),
            algorithm="HS256",
        )

    async def validate_access_session(self, session_id: str, user_id: str, tenant_id: str) -> None:
        session = await self._store.get_auth_session(session_id)
        if session is None or session["user_id"] != user_id or session["tenant_id"] != tenant_id:
            raise HTTPException(status_code=401, detail="invalid_access_session")
        expires_at = session["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if session.get("revoked_at") is not None or expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="access_session_revoked")


def decode_access_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, AuthService._secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_access_token") from exc
    user_id, tenant_id, role, session_id = payload.get("sub"), payload.get("tenant_id"), payload.get("role"), payload.get("jti")
    if not isinstance(user_id, str) or not isinstance(tenant_id, str) or not isinstance(session_id, str) or role not in {"owner", "member"}:
        raise HTTPException(status_code=401, detail="invalid_access_token")
    return {"user_id": user_id, "tenant_id": tenant_id, "role": role, "session_id": session_id}
