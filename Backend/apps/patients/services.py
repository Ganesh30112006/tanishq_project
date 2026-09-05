from __future__ import annotations

from django.db import transaction

from apps.common.services import BaseService
from apps.patients.models import Patient


class PatientService(BaseService):
    @transaction.atomic
    def create_patient(
        self,
        *,
        mrn: str,
        given_name: str,
        family_name: str,
        date_of_birth=None,
        sex: str = "UNKNOWN",
        created_by=None,
    ) -> Patient:
        patient = Patient(
            mrn=mrn,
            given_name=given_name,
            family_name=family_name,
            date_of_birth=date_of_birth,
            sex=sex,
            created_by=created_by,
        )
        patient.full_clean()
        patient.save()
        return patient
