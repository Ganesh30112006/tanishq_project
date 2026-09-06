from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    AI_USE,
    LAB_PATIENT_IDENTITY_READ_MIN,
    PATIENT_READ_ASSIGNED,
    PATIENT_READ_OWN,
    PATIENT_REGISTER,
    STAFF_MANAGE,
    USERS_MANAGE,
    PermissionResolver,
)
from apps.ai.summary import build_patient_summary
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.enums import Role
from apps.common.errors import AccessDenied, ResourceNotFound, ValidationFailed
from apps.patients import presentation
from apps.patients.models import Patient
from apps.patients.serializers import (
    AiPatientSummarySerializer,
    PatientAccountLinkSerializer,
    PatientMinimalIdentitySerializer,
    PatientProfileSerializer,
    PatientRegisterSerializer,
    PatientSerializer,
    TimelineEventSerializer,
)
from apps.patients.services import PatientService
from apps.patients.timeline import build_timeline
from apps.risk.interpretation import viewer_sees_raw_output

_READ_PERMISSIONS = (PATIENT_READ_OWN, PATIENT_READ_ASSIGNED, LAB_PATIENT_IDENTITY_READ_MIN)
#: Clinical read - anything beyond identity fields.
_CLINICAL_READ = (PATIENT_READ_OWN, PATIENT_READ_ASSIGNED)
#: Administrative work that needs to *find* a record without reading inside it:
#: linking a login to a record, registering one, resolving duplicate identities.
_IDENTITY_ADMIN = (PATIENT_REGISTER, USERS_MANAGE)
_VALID_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
_VALID_STATUSES = frozenset({"STABLE", "MONITORING", "REVIEW_REQUIRED"})


class PatientViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Read access to patients, scoped to the caller's relationships.

    The queryset is narrowed *before* any row is returned (spec section 6);
    the object-level permission then re-checks the specific resource.
    """

    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        if PermissionResolver.has_any(user, *_READ_PERMISSIONS):
            qs = visible_patient_queryset(user).order_by("family_name", "given_name")
        elif PermissionResolver.has_any(user, *_IDENTITY_ADMIN):
            # An administrator has to find a record to attach a login to it, or
            # to see that one already exists before registering a duplicate.
            # That is an identity lookup, not clinical access: the rows come
            # back through PatientMinimalIdentitySerializer below, so finding a
            # record still never means reading inside it.
            qs = Patient.objects.filter(is_active=True).order_by("family_name", "given_name")
        else:
            raise AccessDenied(details={"required_permission": list(_READ_PERMISSIONS)})
        params = self.request.query_params
        risk = params.get("risk") or None
        status = params.get("status") or None
        if risk is not None and risk not in _VALID_RISK_LEVELS:
            risk = None
        if status is not None and status not in _VALID_STATUSES:
            status = None
        return presentation.filter_patients(qs, risk=risk, status=status, search=params.get("search") or None)

    def get_serializer_class(self):
        user = self.request.user
        # Schema generation (drf-spectacular) builds a fake view without a
        # real authenticated user; fall back to the default shape rather
        # than fail schema generation.
        if user is not None and getattr(user, "is_authenticated", False):
            # Decided by permission, not by role: anyone without clinical read -
            # a laboratory technician labelling a sample, an administrator
            # linking an account - sees identity fields and nothing else.
            if not PermissionResolver.has_any(user, *_CLINICAL_READ):
                return PatientMinimalIdentitySerializer
        if self.action == "retrieve":
            return PatientProfileSerializer
        return PatientSerializer

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        audit_service.record(
            audit.PATIENT_ACCESS,
            actor=request.user,
            resource=self.get_object(),
            metadata={"view": "detail"},
        )
        return response

    # -- registration ------------------------------------------------
    def create(self, request: Request) -> Response:
        """Register a new patient identity (admins and clinicians)."""
        PermissionResolver.require(request.user, PATIENT_REGISTER)
        data = PatientRegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = dict(data.validated_data)
        assign_doctor_id = payload.pop("assign_doctor_id", None)
        phone = payload.pop("phone", "")

        patient = PatientService().create_patient(created_by=request.user, **payload)
        if phone:
            patient.phone = phone
            patient.save(update_fields=["phone", "updated_at"])

        # A patient nobody is assigned to is invisible to every clinician, so
        # let the registering doctor take them onto their own caseload.
        assignment = self._maybe_assign(request.user, patient, assign_doctor_id)

        audit_service.record(
            audit.PATIENT_REGISTER,
            actor=request.user,
            resource=patient,
            metadata={"mrn": patient.mrn, "assigned": bool(assignment)},
        )
        return Response(PatientSerializer(patient).data, status=201)

    @staticmethod
    def _maybe_assign(actor, patient, assign_doctor_id):
        from apps.doctors.models import Doctor
        from apps.doctors.services import AssignmentService

        doctor = None
        if assign_doctor_id:
            if not PermissionResolver.has_any(actor, STAFF_MANAGE, USERS_MANAGE):
                raise AccessDenied(details={"required_permission": STAFF_MANAGE})
            doctor = Doctor.objects.filter(public_id=assign_doctor_id, is_active=True).first()
        else:
            # A clinician registering a patient is admitting them.
            doctor = Doctor.objects.filter(user_id=actor.pk, is_active=True).first()
        if doctor is None:
            return None
        return AssignmentService().assign(
            doctor, patient, assigned_by=actor, reason="Assigned at registration"
        )

    @action(detail=True, methods=["post"], url_path="link-account")
    def link_account(self, request: Request, public_id=None) -> Response:
        """Attach a login to this record.

        Deliberately admin-only and audited: connecting an account to a medical
        record is the moment a person gains access to that record's data, so it
        is never inferred from a name match (spec section 19).
        """
        PermissionResolver.require(request.user, USERS_MANAGE)
        # Deliberately NOT self.get_object(): that resolves through the
        # clinical queryset, and an administrator holds no clinical read
        # permission. Managing which login owns a record must not require -
        # or grant - the ability to read what is inside it.
        patient = Patient.objects.filter(public_id=public_id, is_active=True).first()
        if patient is None:
            raise ResourceNotFound("Patient not found.")
        data = PatientAccountLinkSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        from apps.accounts.models import User

        user = User.objects.filter(email__iexact=data.validated_data["user_email"]).first()
        if user is None:
            raise ResourceNotFound("No account exists with that email address.")
        if not user.has_role(Role.PATIENT):
            raise ValidationFailed("Only an account holding the PATIENT role can be linked.")
        clash = Patient.objects.filter(user=user).exclude(pk=patient.pk).first()
        if clash is not None:
            raise ValidationFailed("That account is already linked to another patient record.")

        patient.user = user
        patient.save(update_fields=["user", "updated_at"])
        audit_service.record(
            audit.PATIENT_ACCOUNT_LINK,
            actor=request.user,
            resource=patient,
            metadata={"linked_user": user.email},
        )
        return Response(PatientSerializer(patient).data)

    @action(detail=True, methods=["get"])
    def timeline(self, request: Request, public_id=None) -> Response:
        """Chronological events for one patient (spec section 21)."""
        patient = self.get_object()
        try:
            limit = int(request.query_params.get("limit", 8))
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 50))
        events = build_timeline(
            patient, limit=limit, show_scores=viewer_sees_raw_output(request.user)
        )
        return Response(TimelineEventSerializer(events, many=True).data)

    @action(detail=True, methods=["get"], url_path="ai-summary")
    def ai_summary(self, request: Request, public_id=None) -> Response:
        """An explainable AI summary of the patient's authorized record
        (spec sections 36-38). Every fetch is a fresh, audited AI interaction -
        see ``apps.ai.summary``."""
        patient = self.get_object()
        PermissionResolver.require(request.user, AI_USE)
        authorize(request.user, Action.USE_AI, patient)
        summary = build_patient_summary(
            actor=request.user, patient=patient, correlation_id=getattr(request, "request_id", "")
        )
        if summary is None:
            return Response(
                {"status": "blocked", "outcome": "INSUFFICIENT_DATA",
                 "message": "There is no authorized information available to summarize."},
                status=200,
            )
        body = AiPatientSummarySerializer(summary).data
        if not summary["ok"]:
            return Response({"status": "blocked", "outcome": "REVIEW_REQUIRED", **body}, status=200)
        return Response(body)
