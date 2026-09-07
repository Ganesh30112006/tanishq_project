"""Score an annotated corpus, or say how far off scoring anything we are.

    python -m intelligence.benchmark
    python -m intelligence.benchmark --corpus path/to/corpus.json
    python -m intelligence.benchmark --corpus corpus.json --json out.json

Without a corpus it prints the readiness answer, which today is "there isn't
one". That is the intended output: the apparatus exists, the data does not,
and every detector says so in every result it emits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from intelligence.benchmark.corpus import CorpusError, integrity_problems, load
from intelligence.benchmark.promotion import evaluate_all, readiness
from intelligence.benchmark.scoring import BenchmarkResult, score
from intelligence.findings import registry


def _detector_levels() -> dict[str, int]:
    return {d.contract.code: d.contract.level.value for d in registry.all_detectors()}


def _print_readiness(result: BenchmarkResult | None) -> None:
    state = readiness(result)
    print("Gold-standard benchmark readiness")
    print("=" * 72)
    print(f"corpus            {state['corpus']}")
    print(f"reports           {state['reports']} of {state['reports_required']} required")
    if state.get("measured_codes"):
        print(f"codes measured    {len(state['measured_codes'])}")
    print(f"promotable        {len(state['promotable_codes'])}")
    if state["promotable_codes"]:
        for code in state["promotable_codes"]:
            print(f"                  {code}")
    print()
    print("Blocking:")
    for line in state["blocking"]:
        print(f"  - {line}")
    print()
    print(
        "Promotion is never automatic. This prints a recommendation; changing a\n"
        "detector's validation_status is an edit to its contract, made by a\n"
        "person who has read the numbers."
    )


def _print_scores(result: BenchmarkResult) -> None:
    print()
    print(f"Scores for {result.corpus_id} ({result.reports} reports)")
    print("=" * 72)
    header = f"{'code':44s} {'n':>5s} {'prec':>6s} {'rec':>6s} {'F1':>6s} {'abst':>6s}"
    print(header)
    print("-" * 72)
    for code, code_score in sorted(result.codes.items()):
        def _f(value: float | None) -> str:
            return "  -  " if value is None else f"{value:5.3f}"

        print(
            f"{code:44s} {code_score.scored:5d} {_f(code_score.precision):>6s} "
            f"{_f(code_score.recall):>6s} {_f(code_score.f1):>6s} "
            f"{_f(code_score.abstention_rate):>6s}"
        )
        if code_score.out_of_scope_assertions:
            print(
                f"    ! {code_score.out_of_scope_assertions} assertions where no "
                f"annotator scoped this code"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m intelligence.benchmark",
        description="Score the detectors against a clinician-annotated corpus.",
    )
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument(
        "--outputs", type=Path, default=None,
        help="JSON mapping report id -> {code: confidence} from a prior run. "
             "Without it the corpus is validated and its readiness reported, "
             "but nothing is scored.",
    )
    parser.add_argument("--json", type=Path, default=None, dest="json_out")
    args = parser.parse_args(argv)

    if args.corpus is None:
        _print_readiness(None)
        return 0

    try:
        corpus = load(args.corpus)
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems = integrity_problems(corpus)
    if problems:
        print("Integrity problems:")
        for problem in problems:
            print(f"  - {problem}")
        print()

    outputs: dict = {}
    if args.outputs is not None:
        from intelligence.findings.contracts import Confidence

        raw = json.loads(args.outputs.read_text(encoding="utf-8"))
        outputs = {
            report_id: {c: Confidence(v) for c, v in codes.items()}
            for report_id, codes in raw.items()
        }

    result = score(corpus, outputs, levels=_detector_levels())
    _print_readiness(result)
    _print_scores(result)

    if args.json_out is not None:
        payload = {
            "result": result.as_dict(),
            "promotion": {
                code: decision.as_dict()
                for code, decision in evaluate_all(result).items()
            },
        }
        args.json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
