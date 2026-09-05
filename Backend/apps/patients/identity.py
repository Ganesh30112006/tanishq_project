"""Layered patient-identity resolution (spec section 19).

Resolution order, most trustworthy first:

1. exact identifiers (same MRN)
2. normalized identifiers (digits-only phone; casefolded name + DOB)
3. deterministic composite (DOB + family name + sex)
4. similarity (DOB exact + Jaro-Winkler on names, above tight thresholds)

Identities are NEVER merged automatically. Every candidate pair becomes a
``PatientIdentityCandidate`` (PENDING) plus an ``IDENTITY_CONFLICT``
reconciliation event, and a human must approve before any merge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.services import BaseService
from apps.patients.models import Patient, PatientIdentityCandidate, PatientMergeRecord
from apps.reconciliation.services import ReconciliationService

SIMILARITY_FULLNAME_MIN = 0.90
SIMILARITY_FAMILY_MIN = 0.92
SIMILARITY_GIVEN_MIN = 0.85


# -- string similarity (pure python, no dependency) ------------------
def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def jaro(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    match_dist = max(len(a), len(b)) // 2 - 1
    a_match = [False] * len(a)
    b_match = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo = max(0, i - match_dist)
        hi = min(i + match_dist + 1, len(b))
        for j in range(lo, hi):
            if not b_match[j] and ca == b[j]:
                a_match[i] = b_match[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(len(a)):
        if a_match[i]:
            while not b_match[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
    transpositions //= 2
    return (
        matches / len(a) + matches / len(b) + (matches - transpositions) / matches
    ) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_weight: float = 0.1) -> float:
    base = jaro(a, b)
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca == cb:
            prefix += 1
        else:
            break
    return base + prefix * prefix_weight * (1 - base)


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").casefold())


def _norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


@dataclass(slots=True)
class Candidate:
    other: Patient
    tier: str
    score: float
    signals: dict


class IdentityResolver(BaseService):
    def find_candidates(self, patient: Patient) -> list[Candidate]:
        pool = Patient.objects.exclude(pk=patient.pk).filter(is_active=True)
        results: dict[int, Candidate] = {}

        p_family = _norm_name(patient.family_name)
        p_given = _norm_name(patient.given_name)
        p_phone = _norm_phone(patient.phone)

        for other in pool.iterator():
            signals: dict = {}
            tier = None
            score = 0.0

            if patient.mrn and patient.mrn == other.mrn:  # pragma: no cover - MRN is unique
                tier, score = PatientIdentityCandidate.Tier.EXACT_IDENTIFIER, 1.0
                signals["mrn"] = "exact"
            elif p_phone and p_phone == _norm_phone(other.phone) and len(p_phone) >= 7:
                tier, score = PatientIdentityCandidate.Tier.NORMALIZED_IDENTIFIER, 0.97
                signals["phone"] = "normalized-match"
            elif (
                patient.date_of_birth
                and patient.date_of_birth == other.date_of_birth
                and _norm_name(other.family_name) == p_family
                and _norm_name(other.given_name) == p_given
            ):
                tier, score = PatientIdentityCandidate.Tier.NORMALIZED_IDENTIFIER, 0.96
                signals["name_dob"] = "casefolded-exact"
            elif (
                patient.date_of_birth
                and patient.date_of_birth == other.date_of_birth
                and _norm_name(other.family_name) == p_family
                and patient.sex == other.sex
                and patient.sex != "UNKNOWN"
            ):
                tier, score = PatientIdentityCandidate.Tier.DETERMINISTIC_COMPOSITE, 0.9
                signals["composite"] = "dob+family+sex"
            elif patient.date_of_birth and patient.date_of_birth == other.date_of_birth:
                full_a = f"{p_given} {p_family}"
                full_b = f"{_norm_name(other.given_name)} {_norm_name(other.family_name)}"
                fam = jaro_winkler(p_family, _norm_name(other.family_name))
                giv = jaro_winkler(p_given, _norm_name(other.given_name))
                full = jaro_winkler(full_a, full_b)
                if full >= SIMILARITY_FULLNAME_MIN or (
                    fam >= SIMILARITY_FAMILY_MIN and giv >= SIMILARITY_GIVEN_MIN
                ):
                    tier = PatientIdentityCandidate.Tier.SIMILARITY
                    score = round(max(full, (fam + giv) / 2), 4)
                    signals["similarity"] = {
                        "family_jw": round(fam, 4), "given_jw": round(giv, 4),
                        "full_jw": round(full, 4),
                        "family_levenshtein": levenshtein(p_family, _norm_name(other.family_name)),
                    }

            if tier is not None:
                results[other.pk] = Candidate(other=other, tier=tier, score=score, signals=signals)

        return list(results.values())

    @transaction.atomic
    def scan_and_record(self, patient: Patient, *, created_by=None) -> list[PatientIdentityCandidate]:
        reconciliation = ReconciliationService()
        rows: list[PatientIdentityCandidate] = []
        for cand in self.find_candidates(patient):
            a, b = sorted((patient, cand.other), key=lambda p: p.pk)
            existing = PatientIdentityCandidate.objects.filter(patient_a=a, patient_b=b).first()
            if existing is not None:
                rows.append(existing)
                continue
            event = reconciliation.open_event(
                patient=a,
                kind="IDENTITY_CONFLICT",
                summary=f"Possible duplicate identity: {a.mrn} ~ {b.mrn} ({cand.tier})",
                detected_by_workflow="identity_resolver",
                items=[
                    {"resource_type": "Patient", "resource_id": a.public_id,
                     "role_in_conflict": "A", "snapshot": _snapshot(a)},
                    {"resource_type": "Patient", "resource_id": b.public_id,
                     "role_in_conflict": "B", "snapshot": _snapshot(b)},
                ],
            )
            row = PatientIdentityCandidate.objects.create(
                patient_a=a, patient_b=b, score=Decimal(str(cand.score)),
                tier=cand.tier, signals=cand.signals, reconciliation_event=event,
            )
            audit_service.record(
                audit.RECONCILIATION_ACTION, actor=created_by, resource=row,
                metadata={"action": "identity_candidate", "tier": cand.tier},
            )
            rows.append(row)
        return rows


class IdentityMergeService(BaseService):
    # Reverse relations that should NOT be re-pointed on merge.
    _SKIP_RELATIONS = {"identity_candidates_a", "identity_candidates_b", "merge_records"}

    @transaction.atomic
    def review(
        self, *, candidate: PatientIdentityCandidate, decision: str, by, note: str = ""
    ) -> PatientIdentityCandidate:
        if decision == "distinct":
            candidate.status = PatientIdentityCandidate.Status.CONFIRMED_DISTINCT
            if candidate.reconciliation_event_id:
                ReconciliationService().resolve(
                    event=candidate.reconciliation_event, by=by, resolution="Confirmed distinct patients"
                )
        elif decision == "approve":
            candidate.status = PatientIdentityCandidate.Status.MERGE_APPROVED
        else:
            raise ValueError("decision must be 'approve' or 'distinct'")
        candidate.reviewed_by = by
        candidate.reviewed_at = timezone.now()
        candidate.review_note = note[:255]
        candidate.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
        audit_service.record(
            audit.RECONCILIATION_ACTION, actor=by, resource=candidate,
            metadata={"action": f"identity_{decision}"},
        )
        return candidate

    @transaction.atomic
    def perform_merge(
        self, *, candidate: PatientIdentityCandidate, by, surviving: Patient | None = None
    ) -> PatientMergeRecord:
        if candidate.status != PatientIdentityCandidate.Status.MERGE_APPROVED:
            raise ValueError("Candidate must be MERGE_APPROVED before a merge.")

        pair = [candidate.patient_a, candidate.patient_b]
        if surviving is None:
            surviving = min(pair, key=lambda p: p.pk)
        merged = pair[1] if surviving.pk == pair[0].pk else pair[0]

        moved: dict[str, int] = {}
        for rel in Patient._meta.related_objects:
            accessor = rel.get_accessor_name()
            if accessor in self._SKIP_RELATIONS or not rel.related_model:
                continue
            field_name = rel.field.name
            model = rel.related_model
            if rel.one_to_one:
                if not model.objects.filter(**{field_name: surviving}).exists():
                    n = model.objects.filter(**{field_name: merged}).update(**{field_name: surviving})
                    if n:
                        moved[model.__name__] = moved.get(model.__name__, 0) + n
                continue
            try:
                n = model.objects.filter(**{field_name: merged}).update(**{field_name: surviving})
            except Exception:  # noqa: BLE001 - unique clashes: move row-by-row, skip conflicts
                n = 0
                for obj in model.objects.filter(**{field_name: merged}):
                    setattr(obj, field_name, surviving)
                    try:
                        obj.save(update_fields=[field_name])
                        n += 1
                    except Exception:  # noqa: BLE001
                        continue
            if n:
                moved[model.__name__] = moved.get(model.__name__, 0) + n

        merged.is_active = False
        merged.save(update_fields=["is_active", "updated_at"])

        candidate.status = PatientIdentityCandidate.Status.MERGED
        candidate.save(update_fields=["status", "updated_at"])
        if candidate.reconciliation_event_id:
            ReconciliationService().resolve(
                event=candidate.reconciliation_event, by=by,
                resolution=f"Merged {merged.mrn} into {surviving.mrn}",
            )

        record = PatientMergeRecord.objects.create(
            candidate=candidate, surviving_patient=surviving, merged_patient=merged,
            performed_by=by, moved_counts=moved,
        )
        audit_service.record(
            audit.RECONCILIATION_ACTION, actor=by, resource=record,
            metadata={"action": "identity_merge", "surviving": surviving.mrn, "merged": merged.mrn},
        )
        return record


def _snapshot(p: Patient) -> dict:
    return {
        "mrn": p.mrn, "given_name": p.given_name, "family_name": p.family_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "sex": p.sex, "phone": p.phone,
    }
