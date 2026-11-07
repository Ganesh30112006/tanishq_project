"""Getting back into an account after forgetting the password.

There is no staff member to call, so without this a forgotten password loses
the person every report they ever uploaded.

* Asking always gets the same answer, whether or not the email has an account,
  so the form cannot be used to find out who is registered.
* The link carries the account's public id, never its sequential primary key,
  and a token that stops working once the password changes (so it is
  single-use) or after ``PASSWORD_RESET_TIMEOUT``.
* Setting a new password ends every session the account had, so whoever knew
  the old one is signed out too.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.services import AccountService
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import AuditResult
from apps.common.errors import ValidationFailed

_INVALID_LINK = "This link has expired or has already been used. Please ask for a new one."


class _RequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class _ConfirmSerializer(serializers.Serializer):
    uid = serializers.UUIDField()
    token = serializers.CharField(max_length=200)
    password = serializers.CharField(write_only=True, min_length=12, max_length=128)


def reset_link(user: User) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    token = default_token_generator.make_token(user)
    return f"{base}/reset-password?uid={user.public_id}&token={token}"


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        payload = _RequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        email = payload.validated_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None and user.has_usable_password():
            send_mail(
                subject="Reset your CareSense password",
                message=(
                    "Someone asked to reset the password for your CareSense account.\n\n"
                    f"To choose a new password, open this link within the next hour:\n"
                    f"{reset_link(user)}\n\n"
                    "If you did not ask for this, you can ignore this email. Your "
                    "password has not been changed.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )
        audit_service.record(
            audit.PASSWORD_RESET_REQUEST,
            actor=user,
            result=AuditResult.SUCCESS if user else AuditResult.DENIED,
            metadata={"email_domain": email.split("@")[-1]},
        )
        return Response(
            {"detail": "If an account uses that email, we have sent it a link to reset the password."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        payload = _ConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = User.objects.filter(
            public_id=payload.validated_data["uid"], is_active=True
        ).first()
        if user is None or not default_token_generator.check_token(
            user, payload.validated_data["token"]
        ):
            raise ValidationFailed(_INVALID_LINK)

        password = payload.validated_data["password"]
        try:
            validate_password(password, user=user)
        except Exception as exc:  # noqa: BLE001 - Django's ValidationError, reported as ours
            raise ValidationFailed(
                " ".join(getattr(exc, "messages", [str(exc)])), details={"field": "password"}
            ) from exc

        with transaction.atomic():
            user.set_password(password)
            user.save(update_fields=["password", "updated_at"])
            AccountService().revoke_all_for_user(user)
        audit_service.record(audit.PASSWORD_RESET, actor=user, resource=user)
        return Response(
            {"detail": "Your password has been changed. Please sign in with the new one."},
            status=status.HTTP_200_OK,
        )
