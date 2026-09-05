"""Identity, RBAC and revocable access tokens.

Django is the authoritative source for identity and authorization (spec
section 2). RBAC here is *explicit* tables - ``Role``, ``Permission`` and the
join models - rather than Django's built-in group/permission system, so the
permission set is data the platform can administer and audit.
"""
from __future__ import annotations

import datetime as dt

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.enums import Role as RoleEnum
from apps.common.models import TimeStampedModel, UUIDTimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra: object):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: object):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: object):
        extra.update(is_staff=True, is_superuser=True, is_active=True)
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, UUIDTimeStampedModel):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # Subject identifier from the external IdP (OIDC ``sub``), when federated.
    external_subject = models.CharField(max_length=255, blank=True, db_index=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "accounts_user"
        indexes = [models.Index(fields=["is_active"])]

    def __str__(self) -> str:
        return self.email

    @property
    def role_codes(self) -> set[str]:
        return {ur.role.code for ur in self.user_roles.select_related("role").all()}

    def has_role(self, code: str) -> bool:
        return code in self.role_codes


class Permission(TimeStampedModel):
    """A single authorization capability, e.g. ``patient.read.assigned``."""

    code = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=50, db_index=True)
    description = models.CharField(max_length=255)

    class Meta:
        db_table = "accounts_permission"
        ordering = ["category", "code"]

    def __str__(self) -> str:
        return self.code


class Role(TimeStampedModel):
    code = models.CharField(max_length=50, unique=True, choices=RoleEnum.choices)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=True)
    permissions = models.ManyToManyField(
        Permission, through="RolePermission", related_name="roles"
    )

    class Meta:
        db_table = "accounts_role"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class RolePermission(TimeStampedModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, related_name="permission_roles"
    )

    class Meta:
        db_table = "accounts_role_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="uq_role_permission"
            )
        ]


class UserRole(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="role_users")
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    granted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "accounts_user_role"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uq_user_role")
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role_id}"


class AccessToken(TimeStampedModel):
    """A revocable bearer credential.

    Only the SHA-256 hash of the token is stored. Revocation is immediate:
    once ``revoked_at`` is set (or the token expires) authentication fails and
    the user context is no longer accepted (spec section 7).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="access_tokens")
    jti = models.CharField(max_length=64, unique=True)
    token_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    client = models.CharField(max_length=100, blank=True)
    created_ip = models.GenericIPAddressField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_access_token"
        indexes = [models.Index(fields=["user", "revoked_at"])]

    def is_valid(self, *, now: dt.datetime | None = None) -> bool:
        now = now or timezone.now()
        return self.revoked_at is None and self.expires_at > now

    def revoke(self, *, now: dt.datetime | None = None) -> None:
        if self.revoked_at is None:
            self.revoked_at = now or timezone.now()
            self.save(update_fields=["revoked_at", "updated_at"])


class RefreshToken(TimeStampedModel):
    """A long-lived, single-use credential for obtaining a new access token.

    Three properties make this safe to hold for weeks when an access token is
    only safe to hold for an hour:

    **Rotation.** Every redemption issues a new refresh token and marks this one
    used. A refresh token is therefore valid exactly once.

    **Reuse detection.** Because it is single-use, a *second* presentation of an
    already-redeemed token means two parties hold it - the legitimate client and
    somebody who copied it. There is no way to tell which one is asking, so the
    entire family is revoked and both are logged out. A forced re-login is a far
    better outcome than a silently shared session.

    **Family identity.** ``family`` is constant across a rotation chain that
    began with one password login, which is what makes the revocation above
    able to reach the stolen descendant as well as the honest one.

    Only the SHA-256 hash is stored, exactly as for access tokens.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    family = models.CharField(
        max_length=64,
        help_text="Constant across one rotation chain; revoked as a unit on reuse.",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    #: The access token this refresh token was issued alongside, so redeeming
    #: can retire it rather than leaving a live credential behind.
    access_token = models.ForeignKey(
        AccessToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refresh_tokens",
    )
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    client = models.CharField(max_length=100, blank=True)
    created_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "accounts_refresh_token"
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["family"]),
        ]

    def __str__(self) -> str:
        return f"refresh:{self.user_id}:{self.family[:8]}"

    def is_redeemable(self, *, now: dt.datetime | None = None) -> bool:
        now = now or timezone.now()
        return self.revoked_at is None and self.used_at is None and self.expires_at > now

    def revoke(self, *, now: dt.datetime | None = None) -> None:
        if self.revoked_at is None:
            self.revoked_at = now or timezone.now()
            self.save(update_fields=["revoked_at", "updated_at"])
