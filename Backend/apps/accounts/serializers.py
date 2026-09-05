from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.permissions import PermissionResolver


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
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = serializers.ChoiceField(
        choices=["FEMALE", "MALE", "INTERSEX", "UNKNOWN"], required=False, default="UNKNOWN"
    )

    def validate_password(self, value: str) -> str:
        from django.contrib.auth.password_validation import validate_password

        validate_password(value)
        return value
