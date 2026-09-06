"""A registered model version means one specific model, forever.

``register_model`` used to ``update_or_create`` with ``lifecycle_state=DRAFT``
in the defaults. Re-running it on an existing version therefore reset that
version's state and overwrote its weights, domain, metrics and model card.

Two separate things were broken by that, and both are the kind that leave no
trace:

* **RETIRED stopped being terminal.** The governance table says a retired model
  has nowhere to go, because withdrawing a clinical model from service has to
  mean something. Re-registering it put it back in DRAFT, from where it could be
  walked all the way to serving patients again. This is not hypothetical - it
  happened here, when ``seed_demo`` re-registered the synthetic demonstration
  model and quietly took the cvd task away from the real one.
* **A version identifier stopped meaning anything.** Every ``RiskAssessment``
  row, every audit entry and every clinician's note refers to a model by
  ``model_id:version``. If that row can be rewritten to describe a different
  model - different features, different validated domain, different numbers -
  then a historical clinical decision can no longer be reconstructed. An audit
  trail that can be edited from outside is not an audit trail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.common.enums import ModelLifecycleState
from apps.risk.models import FeatureSchema, ModelVersion

pytestmark = pytest.mark.django_db

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"


@pytest.fixture
def card():
    for name in ("cvd-3.0.0.meta.json", "cvd-2.4.0.meta.json", "cvd-1.0.0.meta.json"):
        path = ARTIFACTS / name
        if path.exists():
            return json.loads(path.read_text())
    pytest.skip("no model artifact built in this checkout")
    return None


def _write(tmp_path, card, **changes):
    body = {**card, **changes}
    path = tmp_path / f"{body['model_id']}-{body['model_version']}.meta.json"
    path.write_text(json.dumps(body))
    return str(path)


def _register(tmp_path, card, **changes):
    call_command("register_model", meta=_write(tmp_path, card, **changes))


def test_a_fresh_version_registers_as_draft(tmp_path, card):
    _register(tmp_path, card, model_version="9.9.9")
    mv = ModelVersion.objects.get(model_id=card["model_id"], version="9.9.9")
    assert mv.lifecycle_state == ModelLifecycleState.DRAFT


def test_a_draft_may_still_be_corrected(tmp_path, card):
    """Iterating on a draft is the whole point of the draft state."""
    _register(tmp_path, card, model_version="9.9.9", limitations="first attempt")
    _register(tmp_path, card, model_version="9.9.9", limitations="second attempt")

    mv = ModelVersion.objects.get(model_id=card["model_id"], version="9.9.9")
    assert mv.limitations == "second attempt"
    assert mv.lifecycle_state == ModelLifecycleState.DRAFT


@pytest.mark.parametrize(
    "state",
    [
        ModelLifecycleState.RETIRED,
        ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW,
        ModelLifecycleState.VALIDATION,
    ],
)
def test_a_version_past_draft_cannot_be_overwritten(tmp_path, card, state):
    _register(tmp_path, card, model_version="9.9.9")
    ModelVersion.objects.filter(version="9.9.9").update(lifecycle_state=state)

    with pytest.raises(CommandError) as excinfo:
        _register(tmp_path, card, model_version="9.9.9",
                  limitations="a different model wearing the same number")

    assert "immutable" in str(excinfo.value)
    mv = ModelVersion.objects.get(version="9.9.9")
    assert mv.lifecycle_state == state
    assert "different model" not in mv.limitations


def test_re_registering_a_retired_version_does_not_resurrect_it(tmp_path, card):
    """The exact failure that put a synthetic model in front of patients."""
    _register(tmp_path, card, model_version="9.9.9")
    ModelVersion.objects.filter(version="9.9.9").update(
        lifecycle_state=ModelLifecycleState.RETIRED
    )

    _register(tmp_path, card, model_version="9.9.9")  # byte-identical: a no-op

    mv = ModelVersion.objects.get(version="9.9.9")
    assert mv.lifecycle_state == ModelLifecycleState.RETIRED


def test_an_identical_re_registration_is_a_safe_no_op(tmp_path, card):
    """Provisioning scripts re-run. That must not be a hazard or an error."""
    _register(tmp_path, card, model_version="9.9.9")
    ModelVersion.objects.filter(version="9.9.9").update(
        lifecycle_state=ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW
    )
    _register(tmp_path, card, model_version="9.9.9")

    mv = ModelVersion.objects.get(version="9.9.9")
    assert mv.lifecycle_state == ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW


def test_the_validated_domain_of_an_approved_version_cannot_be_widened(
    tmp_path, card
):
    """The domain gate is what refuses to score a patient the model never saw.

    It lives in the FeatureSchema rather than on the ModelVersion, so it needs
    checking in its own right - an attacker or an accident that widens ``age``
    to 18-99 would not change a single field on the model row while making the
    model score children.
    """
    _register(tmp_path, card, model_version="9.9.9")
    ModelVersion.objects.filter(version="9.9.9").update(
        lifecycle_state=ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW
    )
    mv = ModelVersion.objects.get(version="9.9.9")
    before = FeatureSchema.objects.get(pk=mv.feature_schema_id).definition

    widened = {**card["domain"], "age": {"min": 18.0, "max": 99.0}}
    with pytest.raises(CommandError) as excinfo:
        _register(tmp_path, card, model_version="9.9.9", domain=widened)

    assert "feature_schema.definition" in str(excinfo.value)
    after = FeatureSchema.objects.get(pk=mv.feature_schema_id).definition
    assert after == before
    assert after["valid_domain"]["age"] != {"min": 18.0, "max": 99.0}


# --- the seeding path that actually caused this -------------------------
def test_seeding_refuses_to_take_a_task_from_a_real_model(
    tmp_path, card, settings, django_user_model
):
    """``seed_demo`` must never point the cvd task at the synthetic model.

    It used to activate the demonstration model unconditionally, so re-seeding a
    development database silently replaced the NHANES-trained model with one
    fitted on invented data - and every risk assessment afterwards came from a
    model that had never seen a real patient, while looking entirely normal in
    the UI. That is how a 31-year-old outside any validated age range got scored
    at 13.8% instead of being refused.
    """
    from apps.risk.governance import ModelGovernanceService
    from apps.risk.models import RiskModel

    settings.DEBUG = True
    approver = django_user_model.objects.create_user(
        email="approver@example.test", password="not-a-real-password"  # noqa: S106
    )

    _register(tmp_path, card, model_id="real-model", model_version="9.9.9")
    real = ModelVersion.objects.get(model_id="real-model", version="9.9.9")
    governance = ModelGovernanceService()
    for state in (
        ModelLifecycleState.VALIDATION,
        ModelLifecycleState.APPROVED_FOR_EVALUATION,
        ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW,
    ):
        real = governance.transition(
            model_version=real, to_state=state, actor=approver,
            reason="test fixture: a real model reaching the clinic",
        )
    governance.activate_for_task(task="cvd", model_version=real, actor=approver)

    call_command("seed_demo")

    live = RiskModel.objects.get(task="cvd")
    assert live.active_version.model_id == "real-model"
    assert live.active_version.version == "9.9.9"
