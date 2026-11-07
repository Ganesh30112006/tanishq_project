from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.permissions import PermissionResolver
from apps.patients.validators import validate_date_of_birth
from apps.privacy.models import ConsentPurpose


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class TokenSerializer(serializers.Serializer):
    access_token = serializers.CharField(read_only=True)
    token_type = serializers.CharField(read_only=True, default="Bearer")
    expires_at = serializers.DateTimeField(read_only=True)


class UserSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "is_active", "date_joined", "roles"]
        read_only_fields = fields

    def get_roles(self, obj: User) -> list[str]:
        return sorted(obj.role_codes)


class MeSerializer(UserSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "permissions"]
        read_only_fields = fields

    def get_permissions(self, obj: User) -> list[str]:
        return sorted(PermissionResolver.permission_codes(obj))


class AdminUserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=12)

    class Meta:
        model = User
        fields = ["email", "full_name", "is_active", "password"]

    def create(self, validated_data: dict) -> User:
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save()
        return user

    def update(self, instance: User, validated_data: dict) -> User:
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.full_clean(exclude=["password"])
        instance.save()
        return instance


class SelfRegisterSerializer(serializers.Serializer):
    """Public sign-up for a patient-facing login.

    Sign-up creates the person's *own* record and nothing else. It never
    attaches the account to a pre-existing record belonging to someone else -
    that is an identity decision staff make after verification (spec section
    19). Date of birth and sex are collected here because they are model
    inputs: without an age the risk engine has to block rather than guess.
    """

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=200)
    password = serializers.CharField(write_only=True, min_length=12, max_length=128)
    date_of_birth = serializers.DateField(
        required=False, allow_null=True, validators=[validate_date_of_birth]
    )
    sex = serializers.ChoiceField(
        choices=["FEMALE", "MALE", "INTERSEX", "UNKNOWN"], required=False, default="UNKNOWN"
    )
    #: Self-sign-up is for adults. Under India's DPDP Act a child's data needs
    #: verifiable consent from a parent, and nothing here can verify a parent,
    #: so a child is refused rather than signed up on their own say-so.
    confirms_adult = serializers.BooleanField()
    #: Consent purposes the person ticked, each against the wording published
    #: for it (GET /privacy/consent/documents). Recorded with the account.
    consents = serializers.ListField(
        child=serializers.ChoiceField(choices=ConsentPurpose.choices),
        required=False, default=list,
    )

    def validate_confirms_adult(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "CareSense is for people aged 18 and over."
            )
        return value

    def validate_date_of_birth(self, value):
        # Runs after the field's shared plausibility validator (the module-level
        # function of the same name); this adds only the sign-up age floor.
        if value is None:
            return value
        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError(
                "CareSense is for people aged 18 and over. We cannot create an "
                "account for anyone younger."
            )
        return value

    def validate_consents(self, value: list[str]) -> list[str]:
        from apps.privacy.services import privacy_service

        chosen = list(dict.fromkeys(value))
        for doc in privacy_service.published_documents():
            if doc["is_essential"] and doc["purpose"] not in chosen:
                raise serializers.ValidationError(
                    f"Please agree to \"{doc['label']}\". We cannot keep your "
                    f"reports without it."
                )
        return chosen

    def validate_password(self, value: str) -> str:
        from django.contrib.auth.password_validation import validate_password

        validate_password(value)
        return value
