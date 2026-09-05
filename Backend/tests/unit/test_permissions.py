from __future__ import annotations

import pytest

from apps.accounts.permissions import (
    LAB_RESULT_ENTER,
    PATIENT_READ_ASSIGNED,
    PATIENT_READ_OWN,
    RISK_REQUEST,
    PermissionResolver,
)
from apps.common.enums import Role

pytestmark = pytest.mark.django_db


def test_patient_role_maps_to_self_scope_permissions(make_user):
    patient_user = make_user(Role.PATIENT)
    codes = PermissionResolver.permission_codes(patient_user)
    assert PATIENT_READ_OWN in codes
    assert PATIENT_READ_ASSIGNED not in codes
    assert RISK_REQUEST not in codes


def test_doctor_role_can_request_risk_but_not_enter_lab_results(make_user):
    doctor_user = make_user(Role.DOCTOR)
    assert PermissionResolver.has(doctor_user, RISK_REQUEST)
    assert not PermissionResolver.has(doctor_user, LAB_RESULT_ENTER)


def test_permission_cache_is_per_instance_and_invalidated_on_role_change(make_user):
    from apps.accounts.services import AccountService

    user = make_user()
    assert PermissionResolver.permission_codes(user) == frozenset()
    AccountService().assign_role(user, Role.LAB_TECHNICIAN)
    assert PermissionResolver.has(user, LAB_RESULT_ENTER)


def test_unauthenticated_user_has_no_permissions():
    class Anon:
        is_authenticated = False

    assert PermissionResolver.permission_codes(Anon()) == frozenset()
