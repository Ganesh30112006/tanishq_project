from __future__ import annotations

from rest_framework import serializers

from apps.appointments.models import Appointment, AvailabilitySlot


class AvailabilitySlotSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    doctor_id = serializers.UUIDField(source="doctor.public_id", read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    specialty = serializers.CharField(source="doctor.specialty", read_only=True)
    is_booked = serializers.SerializerMethodField()

    class Meta:
        model = AvailabilitySlot
        fields = [
            "id", "doctor_id", "doctor_name", "specialty",
            "starts_at", "ends_at", "is_open", "is_booked",
        ]
        read_only_fields = fields

    def get_is_booked(self, obj: AvailabilitySlot) -> bool:
        # Annotated by the viewset where available, so the list view does not
        # issue a query per row.
        cached = getattr(obj, "active_bookings", None)
        if cached is not None:
            return bool(cached)
        return obj.appointments.filter(status__in=Appointment.ACTIVE_STATUSES).exists()


class AvailabilityCreateSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class AppointmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor_id = serializers.UUIDField(source="doctor.public_id", read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    specialty = serializers.CharField(source="doctor.specialty", read_only=True)
    starts_at = serializers.DateTimeField(source="slot.starts_at", read_only=True)
    ends_at = serializers.DateTimeField(source="slot.ends_at", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "patient_id", "patient_name", "doctor_id", "doctor_name", "specialty",
            "starts_at", "ends_at", "status", "reason", "outcome_note",
            "resolution_reason", "confirmed_at", "completed_at", "created_at",
        ]
        read_only_fields = fields


class AppointmentCreateSerializer(serializers.Serializer):
    slot_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    #: Optional link back to the risk band that prompted the booking.
    assessment_id = serializers.UUIDField(required=False, allow_null=True)


class AppointmentReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class AppointmentCompleteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=5000, required=False, allow_blank=True)
