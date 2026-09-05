from __future__ import annotations

from rest_framework import serializers

from apps.patients import presentation
from apps.patients.models import Patient, PatientIdentityCandidate, PatientMergeRecord, Sex

_COMPUTED_FIELDS = [
    "initials", "age", "risk_level", "risk_label", "risk_score", "trend",
    "status", "last_updated", "latest_alert",
]


class PatientSerializer(serializers.ModelSerializer):
    """Patient identity plus a role-authorized "card" view: a risk band and
    workflow status computed from the caller's already-authorized risk
    assessments and alerts (spec section 2 - Django owns business/workflow
    state), never a new clinical fact.
    """

    id = serializers.UUIDField(source="public_id", read_only=True)
    full_name = serializers.CharField(read_only=True)
    initials = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    risk_level = serializers.SerializerMethodField()
    risk_label = serializers.SerializerMethodField()
    risk_score = serializers.SerializerMethodField()
    trend = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    last_updated = serializers.SerializerMethodField()
    latest_alert = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "id",
            "mrn",
            "given_name",
            "family_name",
            "full_name",
            "date_of_birth",
            "sex",
            "phone",
            "is_active",
            "created_at",
            *_COMPUTED_FIELDS,
        ]
        read_only_fields = ["id", "full_name", "is_active", "created_at", *_COMPUTED_FIELDS]

    def _card_context(self, obj: Patient) -> presentation.PatientCardContext:
        # Computed once per patient per serialization pass (a list response
        # asks for eight fields off the same instance) rather than once per
        # SerializerMethodField.
        cache = self.__dict__.setdefault("_card_context_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = presentation.build_card_context(obj)
        return cache[obj.pk]

    def get_initials(self, obj: Patient) -> str:
        return presentation.initials(obj.given_name, obj.family_name)

    def get_age(self, obj: Patient) -> int | None:
        return presentation.age_years(obj.date_of_birth)

    def get_risk_level(self, obj: Patient) -> str | None:
        return self._card_context(obj).risk.level

    def get_risk_label(self, obj: Patient) -> str:
        """The band in words, from the same source the result card uses."""
        from apps.risk.interpretation import band_label

        return band_label(self._card_context(obj).risk.level)

    def get_risk_score(self, obj: Patient) -> int | None:
        """The figure, but only for a viewer the model card supports giving it to.

        The patient list is another surface for the same number the result card
        governs. Suppressing it there and printing it here would leave the
        control in name only, so both ask the same question.
        """
        from apps.risk.interpretation import interpret, viewer_sees_raw_output

        context = self._card_context(obj)
        if context.risk.assessment is None:
            return None
        request = self.context.get("request")
        reading = interpret(
            context.risk.assessment,
            for_clinician=viewer_sees_raw_output(getattr(request, "user", None)),
        )
        if not reading or not reading["show_score"]:
            return None
        return context.risk.score

    def get_trend(self, obj: Patient) -> str:
        return self._card_context(obj).risk.trend

    def get_status(self, obj: Patient) -> str:
        return self._card_context(obj).status

    def get_last_updated(self, obj: Patient):
        return self._card_context(obj).last_updated

    def get_latest_alert(self, obj: Patient) -> str | None:
        alert = self._card_context(obj).alert
        return alert.title if alert is not None else None


class PatientProfileSerializer(PatientSerializer):
    """Full profile: adds the record summary shown on the patient detail page.
    Every list here is scoped to this one patient and limited to
    currently-active / trustworthy rows - it is a read view over data the
    caller is already authorized to see, not a new source of truth.
    """

    care_team = serializers.SerializerMethodField()
    conditions = serializers.SerializerMethodField()
    allergies = serializers.SerializerMethodField()
    medications = serializers.SerializerMethodField()
    measurements = serializers.SerializerMethodField()

    class Meta(PatientSerializer.Meta):
        fields = [*PatientSerializer.Meta.fields, "care_team", "conditions", "allergies", "medications", "measurements"]
        read_only_fields = fields

    def get_care_team(self, obj: Patient) -> str | None:
        from apps.doctors.models import DoctorPatientAssignment

        assignment = (
            DoctorPatientAssignment.objects.filter(
                patient=obj, status=DoctorPatientAssignment.Status.ACTIVE
            )
            .select_related("doctor__user")
            .order_by("-assigned_at")
            .first()
        )
        if assignment is None:
            return None
        doctor = assignment.doctor
        name = doctor.user.full_name or doctor.user.email
        return f"Dr. {name} · {doctor.specialty}" if doctor.specialty else f"Dr. {name}"

    def get_conditions(self, obj: Patient) -> list[str]:
        from apps.medical_records.models import Condition

        return list(
            Condition.objects.filter(patient=obj, clinical_status=Condition.ClinicalStatus.ACTIVE)
            .order_by("-created_at")
            .values_list("label", flat=True)[:20]
        )

    def get_allergies(self, obj: Patient) -> list[str]:
        from apps.medical_records.models import Allergy

        return list(
            Allergy.objects.filter(patient=obj, status=Allergy.Status.ACTIVE)
            .order_by("-created_at")
            .values_list("substance", flat=True)[:20]
        )

    def get_medications(self, obj: Patient) -> list[str]:
        from apps.medical_records.models import Medication

        return list(
            Medication.objects.filter(patient=obj, status=Medication.Status.ACTIVE)
            .order_by("-created_at")
            .values_list("name", flat=True)[:20]
        )

    def get_measurements(self, obj: Patient) -> list[dict]:
        from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES
        from apps.health.models import HealthMeasurement, MeasurementKind
        from apps.health.reference_ranges import measurement_status

        rows = HealthMeasurement.objects.filter(
            patient=obj, state__in=TRUSTWORTHY_CLINICAL_STATES
        ).order_by("kind", "-observed_at")
        latest_by_kind: dict[str, HealthMeasurement] = {}
        for row in rows:
            latest_by_kind.setdefault(row.kind, row)
        return [
            {
                "label": MeasurementKind(row.kind).label,
                "value": str(row.value_num) if row.value_num is not None else None,
                "unit": row.unit,
                "recorded_at": row.observed_at,
                "status": measurement_status(row.kind, row.value_num),
            }
            for row in latest_by_kind.values()
        ]


class PatientMinimalIdentitySerializer(serializers.ModelSerializer):
    """Minimum-necessary identity, for confirming *who* a record belongs to.

    Used where someone must find or label a record without being allowed to
    read inside it: a laboratory technician labelling a sample, an
    administrator attaching a login to the right person. Deliberately excludes
    phone and every clinical field.

    ``full_name`` and ``age`` are shown because they are the two things a human
    actually matches a person on; both are computed from identity fields
    already in this response, so neither discloses anything new.
    """

    id = serializers.UUIDField(source="public_id", read_only=True)
    full_name = serializers.CharField(read_only=True)
    age = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "id", "mrn", "given_name", "family_name", "full_name",
            "date_of_birth", "age", "sex",
        ]
        read_only_fields = fields

    def get_age(self, obj: Patient) -> int | None:
        return presentation.age_years(obj.date_of_birth)


class PatientIdentityCandidateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_a = PatientMinimalIdentitySerializer(read_only=True)
    patient_b = PatientMinimalIdentitySerializer(read_only=True)
    reconciliation_event_id = serializers.UUIDField(
        source="reconciliation_event.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = PatientIdentityCandidate
        fields = [
            "id", "patient_a", "patient_b", "score", "tier", "signals",
            "status", "reconciliation_event_id", "reviewed_at", "review_note", "created_at",
        ]
        read_only_fields = fields


class TimelineEventSerializer(serializers.Serializer):
    """Serializes :class:`apps.patients.timeline.TimelineEvent` dataclasses."""

    id = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    type = serializers.CharField()


class AiPatientSummarySerializer(serializers.Serializer):
    summary = serializers.CharField()
    generated_at = serializers.DateTimeField()
    context = serializers.CharField()
    disclaimer = serializers.CharField()
    highlights = serializers.ListField(child=serializers.CharField())


class PatientMergeRecordSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    surviving_patient_id = serializers.UUIDField(source="surviving_patient.public_id", read_only=True)
    merged_patient_id = serializers.UUIDField(source="merged_patient.public_id", read_only=True)
    candidate_id = serializers.UUIDField(source="candidate.public_id", read_only=True)

    class Meta:
        model = PatientMergeRecord
        fields = [
            "id", "candidate_id", "surviving_patient_id", "merged_patient_id",
            "moved_counts", "note", "created_at",
        ]
        read_only_fields = fields


class PatientRegisterSerializer(serializers.Serializer):
    """Staff-facing patient registration.

    Creates an identity only. No clinical finding is accepted here: conditions,
    medications and measurements each have their own validated, provenance
    tracked write path (spec sections 7, 14).
    """

    mrn = serializers.CharField(max_length=64)
    given_name = serializers.CharField(max_length=100)
    family_name = serializers.CharField(max_length=100)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = serializers.ChoiceField(choices=Sex.choices, default=Sex.UNKNOWN)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    # Optional: immediately give the new record a care team.
    assign_doctor_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_mrn(self, value: str) -> str:
        value = value.strip()
        if Patient.objects.filter(mrn__iexact=value).exists():
            raise serializers.ValidationError("A patient with this MRN already exists.")
        return value


class PatientAccountLinkSerializer(serializers.Serializer):
    """Attach an existing login to an existing patient record."""

    user_email = serializers.EmailField()
