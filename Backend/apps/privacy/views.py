"""Privacy endpoints: what I agreed to, and asking to be forgotten.

These are deliberately reachable by the patient themselves. A right that can
only be exercised by writing to an administrator is not much of a right, and a
consent screen that only staff can see is not consent.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import PATIENT_IDENTITY_MANAGE, PermissionResolver
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.errors import AccessDenied, ResourceNotFound, ValidationFailed
from apps.patients.models import Patient
from apps.privacy.models import ErasureRequest, ErasureState
from apps.privacy.serializers import (
    ConsentWriteSerializer,
    ErasureRequestSerializer,
    ErasureWriteSerializer,
)
from apps.privacy.services import privacy_service


def _own_patient(request: Request) -> Patient:
    """The record belonging to the caller, or nothing.

    Consent and erasure are about *this person*, so these endpoints resolve the
    patient from the authenticated user rather than from a supplied id. There is
    no id to tamper with.
    """
    patient = Patient.objects.filter(user=request.user).first()
    if patient is None:
        raise ResourceNotFound("No patient record is linked to this account.")
    return patient


class MyConsentView(APIView):
    """What this person has been asked, and what they answered."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        patient = _own_patient(request)
        return Response(
            {
                "purposes": privacy_service.consent_summary(patient),
                "note": (
                    "You can change any of these at any time. Turning one off "
                    "stops that use of your record; it does not delete anything "
                    "already saved."
                ),
            }
        )

    def post(self, request: Request) -> Response:
        patient = _own_patient(request)
        payload = ConsentWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        grant = privacy_service.record_consent(
            patient=patient,
            purpose=payload.validated_data["purpose"],
            granted=payload.validated_data["granted"],
            recorded_by=request.user,
            self_recorded=True,
        )
        return Response(
            {
                "purpose": grant.purpose,
                "granted": grant.is_active,
                "granted_at": grant.granted_at,
                "withdrawn_at": grant.withdrawn_at,
                "document_version": grant.document.version,
            },
            status=status.HTTP_200_OK,
        )


class MyErasureView(APIView):
    """Asking to be forgotten, and seeing what happened."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        patient = _own_patient(request)
        rows = ErasureRequest.objects.filter(patient=patient)
        return Response(
            {
                "results": ErasureRequestSerializer(rows, many=True).data,
                "what_this_means": (
                    "If you ask us to erase your data, we destroy the details "
                    "that identify you - your name, date of birth, phone number "
                    "and login. Your medical readings are kept, but with nothing "
                    "linking them to you, because a treatment record has to be "
                    "kept for a period even after you leave. We will tell you "
                    "exactly what was destroyed and what was kept."
                ),
            }
        )

    def post(self, request: Request) -> Response:
        patient = _own_patient(request)
        payload = ErasureWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        req = privacy_service.request_erasure(
            patient=patient,
            requested_by=request.user,
            reason=payload.validated_data.get("reason", ""),
        )
        return Response(
            ErasureRequestSerializer(req).data, status=status.HTTP_201_CREATED
        )


class ErasureAdminView(APIView):
    """Deciding an erasure request.

    Carrying one out destroys identifiers irreversibly, so it is never
    automatic and never self-service: a named person decides, and the decision
    is audited.
    """

    permission_classes = [IsAuthenticated]

    def _require_manage(self, request: Request) -> None:
        if not PermissionResolver.has_any(request.user, PATIENT_IDENTITY_MANAGE):
            raise AccessDenied(details={"required_permission": [PATIENT_IDENTITY_MANAGE]})

    def get(self, request: Request) -> Response:
        self._require_manage(request)
        rows = ErasureRequest.objects.filter(
            state__in=[ErasureState.REQUESTED, ErasureState.UNDER_REVIEW]
        )
        return Response({"results": ErasureRequestSerializer(rows, many=True).data})

    def post(self, request: Request, public_id=None) -> Response:
        self._require_manage(request)
        req = ErasureRequest.objects.filter(public_id=public_id).first()
        if req is None:
            raise ResourceNotFound("Erasure request not found.")

        decision = (request.data or {}).get("decision")
        note = (request.data or {}).get("note", "")

        if decision == "execute":
            req = privacy_service.execute_erasure(req, decided_by=request.user)
        elif decision == "refuse":
            req = privacy_service.refuse_erasure(
                req, decided_by=request.user, note=note
            )
        else:
            raise ValidationFailed("decision must be 'execute' or 'refuse'.")

        audit_service.record(
            audit.ERASURE_EXECUTE if decision == "execute" else audit.ERASURE_REQUEST,
            actor=request.user,
            resource=req.patient,
            metadata={"decision": decision, "request": str(req.public_id)},
        )
        return Response(ErasureRequestSerializer(req).data)
