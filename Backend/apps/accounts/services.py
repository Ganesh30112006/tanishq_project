"""Account, RBAC and token services (spec sections 5, 7, 55)."""
from __future__ import annotations

import datetime as dt
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.authentication import LOCAL_TOKEN_PREFIX, hash_token
from apps.accounts.models import (
    AccessToken,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
)
from apps.accounts.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSION_CATALOG,
    PermissionResolver,
)
from apps.common.enums import Role as RoleEnum
from apps.common.errors import AuthenticationRequired, ValidationFailed
from apps.common.services import BaseService

logger = logging.getLogger("caresense.accounts")

#: Distinct from the access-token prefix so a refresh token presented as a
#: bearer credential is rejected outright rather than merely failing lookup.
REFRESH_TOKEN_PREFIX = "cs_refresh_"  # noqa: S105 - a discriminator, not a secret


class IssuedToken:
    __slots__ = ("raw", "record")

    def __init__(self, raw: str, record: AccessToken) -> None:
        self.raw = raw
        self.record = record


class IssuedRefreshToken:
    __slots__ = ("raw", "record")

    def __init__(self, raw: str, record: RefreshToken) -> None:
        self.raw = raw
        self.record = record


class AccountService(BaseService):
    # -- authentication ---------------------------------------------------
    def authenticate_password(self, email: str, password: str) -> User:
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        # Constant-ish work whether or not the user exists.
        if user is None:
            User().set_password(password)
            raise AuthenticationRequired("Invalid credentials.")
        if not user.check_password(password):
            raise AuthenticationRequired("Invalid credentials.")
        return user

    @transaction.atomic
    def issue_local_token(
        self,
        user: User,
        *,
        client: str = "",
        ip: str | None = None,
        ttl_seconds: int | None = None,
    ) -> IssuedToken:
        if not settings.IDENTITY.get("LOCAL_DEV_TOKENS"):
            raise ValidationFailed("Local token issuance is disabled in this environment.")
        ttl = ttl_seconds or settings.IDENTITY["ACCESS_TOKEN_TTL_SECONDS"]
        raw = LOCAL_TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = AccessToken.objects.create(
            user=user,
            jti=secrets.token_hex(16),
            token_hash=hash_token(raw),
            issued_at=timezone.now(),
            expires_at=timezone.now() + dt.timedelta(seconds=ttl),
            client=client[:100],
            created_ip=ip,
        )
        return IssuedToken(raw=raw, record=record)

    # -- refresh tokens ---------------------------------------------------
    @transaction.atomic
    def issue_refresh_token(
        self,
        user: User,
        *,
        access_token: AccessToken | None = None,
        family: str = "",
        client: str = "",
        ip: str | None = None,
    ) -> IssuedRefreshToken:
        ttl = settings.IDENTITY["REFRESH_TOKEN_TTL_SECONDS"]
        raw = REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(48)
        record = RefreshToken.objects.create(
            user=user,
            family=family or secrets.token_hex(16),
            token_hash=hash_token(raw),
            access_token=access_token,
            issued_at=timezone.now(),
            expires_at=timezone.now() + dt.timedelta(seconds=ttl),
            client=client[:100],
            created_ip=ip,
        )
        return IssuedRefreshToken(raw=raw, record=record)

    def redeem_refresh_token(
        self, raw_token: str, *, client: str = "", ip: str | None = None
    ) -> tuple[IssuedToken, IssuedRefreshToken]:
        """Exchange a refresh token for a fresh pair, once.

        A token that has already been redeemed is not merely invalid: it is
        evidence that a credential leaked, because the legitimate client threw
        its copy away after using it. We cannot tell the thief from the victim,
        so the whole family goes and both must log in again.

        Note the shape: the failure is recorded and raised *after* the atomic
        block closes, never inside it. Raising within the transaction would roll
        back the family revocation we just performed - the database would end up
        exactly as it was, and the stolen token would keep working. The refusal
        has to be the thing that survives.
        """
        failure: str | None = None
        result: tuple[IssuedToken, IssuedRefreshToken] | None = None

        with transaction.atomic():
            record = (
                RefreshToken.objects.select_for_update()
                .filter(token_hash=hash_token(raw_token))
                .first()
            )
            if record is None:
                failure = "Invalid refresh token."
            elif record.used_at is not None:
                self._revoke_family(record, reason="refresh token reused")
                failure = (
                    "This session has been signed out for security. Please sign in again."
                )
            elif not record.is_redeemable():
                failure = "Your session has expired. Please sign in again."
            elif not record.user.is_active:
                failure = "This account is no longer active."
            else:
                now = timezone.now()
                record.used_at = now
                record.save(update_fields=["used_at", "updated_at"])
                # The access token it was paired with is replaced, so retire it
                # rather than leaving an unreferenced live credential behind.
                if record.access_token is not None:
                    record.access_token.revoke(now=now)

                access = self.issue_local_token(record.user, client=client, ip=ip)
                refresh = self.issue_refresh_token(
                    record.user,
                    access_token=access.record,
                    family=record.family,
                    client=client,
                    ip=ip,
                )
                result = (access, refresh)

        if failure is not None:
            raise AuthenticationRequired(failure)
        assert result is not None
        return result

    def _revoke_family(self, record: RefreshToken, *, reason: str) -> int:
        now = timezone.now()
        AccessToken.objects.filter(
            refresh_tokens__family=record.family, revoked_at__isnull=True
        ).update(revoked_at=now)
        count = RefreshToken.objects.filter(
            family=record.family, revoked_at__isnull=True
        ).update(revoked_at=now)
        logger.warning(
            "refresh_token_family_revoked",
            extra={"user_id": record.user_id, "family": record.family, "reason": reason},
        )
        return count

    def revoke_refresh_token(self, raw_token: str) -> bool:
        record = RefreshToken.objects.filter(token_hash=hash_token(raw_token)).first()
        if record is None:
            return False
        record.revoke()
        return True

    def revoke_token(self, raw_token: str) -> bool:
        record = AccessToken.objects.filter(token_hash=hash_token(raw_token)).first()
        if record is None:
            return False
        record.revoke()
        return True

    def revoke_refresh_tokens_for_user(self, user: User) -> int:
        return RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )

    def revoke_all_for_user(self, user: User) -> int:
        """Revoke every live credential this user holds, of both kinds.

        Leaving refresh tokens behind would make "revoke all sessions" a lie:
        the holder could mint a fresh access token straight afterwards.
        """
        now = timezone.now()
        RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
        return AccessToken.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=now
        )

    # -- role assignment ------------------------------------------------
    @transaction.atomic
    def assign_role(self, user: User, role_code: str, *, granted_by: User | None = None) -> UserRole:
        if role_code not in RoleEnum.values:
            raise ValidationFailed(f"Unknown role '{role_code}'.")
        role = Role.objects.get(code=role_code)
        user_role, _ = UserRole.objects.get_or_create(
            user=user, role=role, defaults={"granted_by": granted_by}
        )
        PermissionResolver.invalidate(user)
        return user_role

    @transaction.atomic
    def revoke_role(self, user: User, role_code: str) -> int:
        deleted, _ = UserRole.objects.filter(user=user, role__code=role_code).delete()
        PermissionResolver.invalidate(user)
        return deleted

    # -- catalog sync (idempotent; safe from a data migration) ----------
    @transaction.atomic
    def sync_rbac_catalog(self) -> None:
        for code, (category, description) in PERMISSION_CATALOG.items():
            Permission.objects.update_or_create(
                code=code, defaults={"category": category, "description": description}
            )
        for role_code, perm_codes in DEFAULT_ROLE_PERMISSIONS.items():
            role, _ = Role.objects.update_or_create(
                code=role_code,
                defaults={"name": RoleEnum(role_code).label, "is_system": True},
            )
            for perm_code in perm_codes:
                RolePermission.objects.get_or_create(
                    role=role, permission=Permission.objects.get(code=perm_code)
                )


def current_raw_token(request) -> str | None:
    """The raw bearer token on this request, if any (for logout / revoke)."""
    from rest_framework.authentication import get_authorization_header

    parts = get_authorization_header(request).split()
    if len(parts) == 2 and parts[0].lower() == b"bearer":
        return parts[1].decode("latin-1")
    return None
