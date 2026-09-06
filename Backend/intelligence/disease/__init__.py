"""Level-3 and level-4 detectors, organised by body system.

A level-3 detector proposes a *condition likelihood* from a combination of
lower-level findings and measurements. It is never a diagnosis: the contract
refuses a code that is not hedged, refuses fewer than two pieces of evidence,
and forces human review on every result.

A level-4 detector is a governed risk model. It cannot be created here at all -
the contract requires ``CLINICALLY_APPROVED``, which in this system means an
approved ``ModelVersion`` carried through the Django lifecycle with a named
approver and an evidence dossier. The cardiovascular model is the only one, and
it stays independent and frozen.

Categories the framework must eventually express - endocrine, renal, hepatic,
gastrointestinal, respiratory, infectious, neurological, musculoskeletal,
reproductive, oncology, immune, nutritional - are deliberately empty. Two of
them carry standing prohibitions:

* **Oncology.** No detector may map a tumour marker to a cancer. "CEA high ->
  cancer", "CA-125 high -> ovarian cancer", "PSA high -> prostate cancer" are
  the exact shapes that must not be built.
* **Infectious disease.** A generic abnormal blood count must never become
  "infection detected".
"""
from __future__ import annotations
