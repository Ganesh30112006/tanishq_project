from __future__ import annotations

import pytest

from apps.authz.engine import Action, is_allowed
from apps.common.enums import Role

pytestmark = pytest.mark.django_db


def test_patient_can_read_only_their_own_record(make_user, make_patient):
    alice = make_user(Role.PATIENT)
    bob = make_user(Role.PATIENT)
    alice_patient = make_patient(user=alice)
    bob_patient = make_patient(user=bob)

    assert is_allowed(alice, Action.READ, alice_patient)
    # Patient A -> Patient B data MUST FAIL (spec section 54)
    assert not is_allowed(alice, Action.READ, bob_patient)


def test_doctor_reads_assigned_patient_only(make_user, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    assigned = make_patient()
    unassigned = make_patient()
    assign_patient(doctor, assigned)

    assert is_allowed(doctor.user, Action.READ, assigned)
    # Doctor -> unassigned patient MUST FAIL (spec section 54)
    assert not is_allowed(doctor.user, Action.READ, unassigned)


def test_lab_tech_needs_open_workflow_to_see_identity(make_lab_tech, make_patient, open_lab_order):
    tech = make_lab_tech()
    with_order = make_patient()
    without_order = make_patient()
    open_lab_order(tech, with_order)

    assert is_allowed(tech.user, Action.READ, with_order)
    assert not is_allowed(tech.user, Action.READ, without_order)


def test_default_deny_for_unhandled_resource(make_user):
    user = make_user(Role.ADMIN)
    assert not is_allowed(user, Action.READ, object())
