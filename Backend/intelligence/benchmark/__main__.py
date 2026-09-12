"""Report how far off each benchmark is, layer by layer.

    python -m intelligence.benchmark
    python -m intelligence.benchmark --write-handbook
    python -m intelligence.benchmark --extraction-corpus extraction.json
    python -m intelligence.benchmark --reasoning-corpus reports.json \
        --outputs system.json --json scores.json

Never one number. A caller has to be able to see which layer is the obstacle,
because the two are fixed by completely different work: one needs parser
changes, the other needs clinician time.

With no corpus this prints the readiness answer, which today is "there isn't
one" for both. That is the intended output: the apparatus exists, the data
does not, and every detector says so in every result it emits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from intelligence.benchmark import extraction as X
from intelligence.benchmark import reasoning as R
from intelligence.benchmark.promotion import (
    evaluate_all,
    evaluate_extraction,
    readiness,
)


def _detector_levels() -> dict[str, int]:
    from intelligence.findings import registry

    return {d.contract.code: d.contract.level.value for d in registry.all_detectors()}


def _rule(title: str) -> None:
    print()
    print(title)
    print("=" * 72)


def _print_readiness(reasoning_result, extraction_result) -> None:
    state = readiness(reasoning_result, extraction_result)

    _rule("1. Extraction   text or image -> structured evidence")
    ex = state["extraction"]
    print(f"corpus            {ex['corpus']}")
    print(f"documents         {ex['documents']} of {ex['documents_required']} required")
    print(f"ready             {'yes' if ex['ready'] else 'no'}")
    if ex["summary"] and ex["summary"] != "never measured":
        print(f"                  {ex['summary']}")
    for line in ex["blocking"]:
        print(f"  - {line}")

    _rule("2. Clinical reasoning   structured evidence -> finding or condition")
    re_ = state["reasoning"]
    print(f"corpus            {re_['corpus']}")
    print(f"reports           {re_['reports']} of {re_['reports_required']} required")
    if re_.get("measured_codes"):
        print(f"codes measured    {len(re_['measured_codes'])}")
    print(f"promotable        {len(re_['promotable_codes'])}")
    for code in re_["promotable_codes"]:
        print(f"                  {code}")
    for line in re_["blocking"]:
        print(f"  - {line}")

    print()
    print(
        "The two are never combined. A detector can reason flawlessly on a\n"
        "misread value, and perfect extraction can feed an unsafe rule; one\n"
        "score would hide both. Promotion is never automatic either - this\n"
        "prints a recommendation, and changing a detector's validation_status\n"
        "is an edit to its contract made by a person who has read the numbers."
    )


def _print_extraction_scores(result) -> None:
    _rule(f"Extraction scores for {result.corpus_id} ({result.documents} documents)")
    d = result.as_dict()["detection"]
    print(f"detection         P {d['precision']}  R {d['recall']}  F1 {d['f1']}")
    print(f"                  found {d['found']} of {d['expected']}, "
          f"invented {d['invented']}")
    print(f"fabrications      {result.fabrications}  "
          f"(rate {result.fabrication_rate})")
    print(f"refusal           {result.correctly_refused} of "
          f"{result.refusable_lines} lines that yield nothing")
    print()
    print(f"{'attribute':20s} {'n':>6s} {'accuracy':>10s}")
    print("-" * 40)
    for name, score in sorted(result.attributes.items()):
        accuracy = "   -  " if score.accuracy is None else f"{score.accuracy:6.3f}"
        print(f"{name:20s} {score.scored:6d} {accuracy:>10s}")
    for example in result.examples_of_fabrication[:10]:
        print(f"  ! {example}")


def _print_reasoning_scores(result) -> None:
    _rule(f"Reasoning scores for {result.corpus_id} ({result.reports} reports)")
    print(f"{'code':44s} {'n':>5s} {'prec':>6s} {'rec':>6s} {'F1':>6s} {'abst':>6s}")
    print("-" * 72)
    for code, score in sorted(result.codes.items()):
        def _f(value: float | None) -> str:
            return "  -  " if value is None else f"{value:5.3f}"

        print(
            f"{code:44s} {score.scored:5d} {_f(score.precision):>6s} "
            f"{_f(score.recall):>6s} {_f(score.f1):>6s} "
            f"{_f(score.abstention_rate):>6s}"
        )
        if score.out_of_scope_assertions:
            print(
                f"    ! {score.out_of_scope_assertions} assertions where no "
                f"annotator scoped this code"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m intelligence.benchmark",
        description="Report how far off each benchmark layer is.",
    )
    parser.add_argument("--extraction-corpus", type=Path, default=None)
    parser.add_argument("--reasoning-corpus", type=Path, default=None)
    parser.add_argument(
        "--outputs", type=Path, default=None,
        help="JSON mapping report id -> {code: confidence} from a prior run. "
             "Without it the reasoning corpus is validated but not scored.",
    )
    parser.add_argument(
        "--extraction-outputs", type=Path, default=None,
        help="JSON mapping document id -> [system value, ...] from a prior run.",
    )
    parser.add_argument("--json", type=Path, default=None, dest="json_out")
    parser.add_argument(
        "--write-handbook", action="store_true",
        help="regenerate docs/annotation-spec.md from the frozen definitions "
             "and exit. The handbook is generated rather than maintained, so "
             "it cannot drift from the meanings the scorer enforces.",
    )
    args = parser.parse_args(argv)

    if args.write_handbook:
        from intelligence.benchmark import spec

        target = spec.write_handbook()
        print(f"wrote {target}")
        print(f"version     {spec.ANNOTATION_SPEC_VERSION}")
        print(f"fingerprint {spec.fingerprint()}")
        return 0

    extraction_result = None
    reasoning_result = None

    try:
        if args.extraction_corpus is not None:
            corpus = X.load(args.extraction_corpus)
            problems = X.integrity_problems(corpus)
            if problems:
                print("Extraction corpus integrity problems:")
                for problem in problems:
                    print(f"  - {problem}")
            outputs = {}
            if args.extraction_outputs is not None:
                raw = json.loads(args.extraction_outputs.read_text(encoding="utf-8"))
                outputs = {
                    doc: [X.SystemValue(**v) for v in values]
                    for doc, values in raw.items()
                }
            extraction_result = X.score(corpus, outputs)

        if args.reasoning_corpus is not None:
            corpus = R.load(args.reasoning_corpus)
            problems = R.integrity_problems(corpus)
            if problems:
                print("Reasoning corpus integrity problems:")
                for problem in problems:
                    print(f"  - {problem}")
            outputs = {}
            if args.outputs is not None:
                from intelligence.findings.contracts import Confidence

                raw = json.loads(args.outputs.read_text(encoding="utf-8"))
                outputs = {
                    report_id: {c: Confidence(v) for c, v in codes.items()}
                    for report_id, codes in raw.items()
                }
            reasoning_result = R.score(corpus, outputs, levels=_detector_levels())
    except (X.CorpusError, R.CorpusError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _print_readiness(reasoning_result, extraction_result)
    if extraction_result is not None and extraction_result.documents:
        _print_extraction_scores(extraction_result)
    if reasoning_result is not None and reasoning_result.reports:
        _print_reasoning_scores(reasoning_result)

    if args.json_out is not None:
        payload = {
            "readiness": readiness(reasoning_result, extraction_result),
            "extraction": (
                None if extraction_result is None else {
                    "result": extraction_result.as_dict(),
                    "promotion": evaluate_extraction(extraction_result).as_dict(),
                }
            ),
            "reasoning": (
                None if reasoning_result is None else {
                    "result": reasoning_result.as_dict(),
                    "promotion": {
                        code: decision.as_dict()
                        for code, decision in evaluate_all(reasoning_result).items()
                    },
                }
            ),
        }
        args.json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
