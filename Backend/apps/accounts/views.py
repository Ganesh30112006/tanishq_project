from __future__ import annotations

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import USERS_MANAGE, HasPermission
from apps.accounts.serializers import (
    AdminUserWriteSerializer,
    LoginSerializer,
    MeSerializer,
    SelfRegisterSerializer,
    UserSerializer,
)
from apps.accounts.services import AccountService, current_raw_token
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import AuditResult, Role
from apps.common.errors import ValidationFailed
from apps.patients.services import PatientService

account_service = AccountService()


def _session_payload(access, refresh) -> dict:
    """The single shape every endpoint that starts or continues a session returns.

    The refresh token is returned in the body rather than set as a cookie
    because the SPA lives on its own origin and calls this API with a bearer
    token; there is no cookie to attach. It must be stored where site script
    cannot be injected to read it, and it is single-use, so a stolen one is
    detectable the moment the real client next refreshes.
    """
    return {
        "access_token": access.raw,
        "token_type": "Bearer",
        "expires_at": access.record.expires_at,
        "refresh_token": refresh.raw,
        "refresh_expires_at": refresh.record.expires_at,
    }


class LoginView(APIView):
    """Exchange credentials for a bearer token.

    In a federated deployment this endpoint is replaced by the IdP's token
    endpoint; it exists here for local development and testing.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        try:
            user = account_service.authenticate_password(
                email, data.validated_data["password"]
            )
        except Exception:
            audit_service.record(
                audit.LOGIN_FAILED, result=AuditResult.DENIED, metadata={"email_domain": email.split("@")[-1]}
            )
            raise
        client = request.META.get("HTTP_USER_AGENT", "")[:100]
        ip = request.META.get("REMOTE_ADDR")
        issued = account_service.issue_local_token(user, client=client, ip=ip)
        refresh = account_service.issue_refresh_token(
            user, access_token=issued.record, client=client, ip=ip
        )
        audit_service.record(audit.LOGIN, actor=user, resource=user)
        return Response(
            _session_payload(issued, refresh),
            status=status.HTTP_201_CREATED,
        )


class RegisterView(APIView):
    """Public sign-up for a patient login.

    Creates an account holding only the PATIENT role. It is intentionally NOT
    connected to a clinical record: an unverified stranger must never be able
    to attach themselves to an existing patient's data by choosing the right
    name. Staff link the account to a record afterwards, which is audited.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        data = SelfRegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].lower().strip()

        if User.objects.filter(email__iexact=email).exists():
            # Registration is public, so a precise "already registered" reply
            # would turn this into an account-enumeration oracle.
            audit_service.record(
                audit.USER_CREATE,
                result=AuditResult.DENIED,
                metadata={"reason": "duplicate_email", "email_domain": email.split("@")[-1]},
            )
            raise ValidationFailed(
                "That account could not be created. If you already have one, sign in instead.",
                details={"field": "email"},
            )

        full_name = data.validated_data["full_name"].strip()
        given, _, family = full_name.partition(" ")

        with transaction.atomic():
            user = User(email=email, full_name=full_name)
            user.set_password(data.validated_data["password"])
            user.full_clean(exclude=["password"])
            user.save()
            account_service.assign_role(user, Role.PATIENT)

            # The person gets their own record immediately so they can upload
            # results and use the service. It is a fresh record keyed to this
            # account - never a lookup that could attach them to someone else.
            patient = PatientService().create_patient(
                mrn=_allocate_record_number(),
                given_name=given or full_name,
                family_name=family or "-",
                date_of_birth=data.validated_data.get("date_of_birth"),
                sex=data.validated_data.get("sex") or "UNKNOWN",
                created_by=user,
            )
            patient.user = user
            patient.save(update_fields=["user", "updated_at"])

        audit_service.record(
            audit.USER_CREATE, actor=user, resource=user, metadata={"self_registered": True}
        )
        audit_service.record(
            audit.PATIENT_REGISTER,
            actor=user,
            resource=patient,
            metadata={"self_registered": True},
        )
        client = request.META.get("HTTP_USER_AGENT", "")[:100]
        ip = request.META.get("REMOTE_ADDR")
        issued = account_service.issue_local_token(user, client=client, ip=ip)
        refresh = account_service.issue_refresh_token(
            user, access_token=issued.record, client=client, ip=ip
        )
        return Response(
            _session_payload(issued, refresh),
            status=status.HTTP_201_CREATED,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        raw = current_raw_token(request)
        if raw:
            account_service.revoke_token(raw)
        # Signing out has to take the refresh token with it. Revoking only the
        # access token would leave a credential that mints a new one, so the
        # session the user just ended would quietly continue.
        supplied = (request.data or {}).get("refresh_token")
        if supplied:
            account_service.revoke_refresh_token(supplied)
        else:
            account_service.revoke_refresh_tokens_for_user(request.user)
        audit_service.record(audit.LOGOUT, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshView(APIView):
    """Exchange a refresh token for a new access token.

    Unauthenticated by design: the caller's access token has usually expired,
    which is the whole reason they are here. The refresh token is the
    credential. Throttled like the other credential endpoints.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        supplied = (request.data or {}).get("refresh_token")
        if not supplied:
            raise ValidationFailed("A refresh token is required.")
        access, refresh = account_service.redeem_refresh_token(
            supplied,
            client=request.META.get("HTTP_USER_AGENT", "")[:100],
            ip=request.META.get("REMOTE_ADDR"),
        )
        audit_service.record(audit.LOGIN, actor=access.record.user, resource=access.record.user,
                             metadata={"via": "refresh"})
        return Response(_session_payload(access, refresh), status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data)


class UserAdminViewSet(viewsets.ModelViewSet):
    """User / role administration (spec section 5, ADMIN)."""

    permission_classes = [IsAuthenticated, HasPermission.of(USERS_MANAGE)]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    queryset = User.objects.all().order_by("email")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AdminUserWriteSerializer
        return UserSerializer

    def perform_create(self, serializer) -> None:
        user = serializer.save()
        audit_service.record(audit.ADMIN_CHANGE, actor=self.request.user, resource=user,
                             metadata={"change": "user.create"})

    def perform_update(self, serializer) -> None:
        user = serializer.save()
        audit_service.record(audit.ADMIN_CHANGE, actor=self.request.user, resource=user,
                             metadata={"change": "user.update"})

    def perform_destroy(self, instance: User) -> None:
        # Deactivate rather than delete so history and audit references survive.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        account_service.revoke_all_for_user(instance)
        audit_service.record(audit.ADMIN_CHANGE, actor=self.request.user, resource=instance,
                             metadata={"change": "user.deactivate"})

    @action(detail=True, methods=["post"], url_path="roles")
    @transaction.atomic
    def assign_role(self, request: Request, public_id=None) -> Response:
        user = self.get_object()
        role_code = request.data.get("role")
        account_service.assign_role(user, role_code, granted_by=request.user)
        audit_service.record(audit.ROLE_CHANGE, actor=request.user, resource=user,
                             metadata={"change": "role.assign", "role": role_code})
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["delete"], url_path=r"roles/(?P<role_code>[\w-]+)")
    @transaction.atomic
    def revoke_role(self, request: Request, public_id=None, role_code=None) -> Response:
        user = self.get_object()
        account_service.revoke_role(user, role_code)
        audit_service.record(audit.ROLE_CHANGE, actor=request.user, resource=user,
                             metadata={"change": "role.revoke", "role": role_code})
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"], url_path="revoke-tokens")
    def revoke_tokens(self, request: Request, public_id=None) -> Response:
        user = self.get_object()
        count = account_service.revoke_all_for_user(user)
        audit_service.record(audit.ADMIN_CHANGE, actor=request.user, resource=user,
                             metadata={"change": "tokens.revoke_all", "count": count})
        return Response({"revoked": count})


def _allocate_record_number() -> str:
    """Mint an opaque record number for a self-registered account.

    Self-service users have no hospital-issued MRN, so the platform issues its
    own. It is random rather than sequential so the identifier leaks neither
    enrolment order nor total user count.
    """
    import secrets

    from apps.patients.models import Patient

    for _ in range(10):
        candidate = f"CS-{secrets.token_hex(4).upper()}"
        if not Patient.objects.filter(mrn=candidate).exists():
            return candidate
    raise ValidationFailed("Could not allocate a record number. Please try again.")
