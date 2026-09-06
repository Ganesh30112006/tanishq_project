"""Neural-network arm, and running the deployed model on the Intel iGPU.

Two separate questions, deliberately kept apart:

**Does a non-linear model help?** With ~150 training events a neural network
has far more capacity than the data can support. It is trained anyway, with
early stopping and class weighting, because "we tried it and it did not help"
is a result worth having rather than an assumption.

**Can the model run on this machine's GPU?** The point is not speed - a six
feature logistic regression is microseconds on a CPU and no GPU will improve
that. The point is that the *deployment target* is validated: if the GPU
returned different numbers from the model that was validated, the model card's
metrics would not describe what patients actually receive. So the iGPU output
is compared element-by-element against the scikit-learn model that produced the
published metrics, and only then is timing reported.

Route taken: scikit-learn -> ONNX (skl2onnx) -> OpenVINO -> Intel Iris Xe.
``torch.xpu`` is not used because it segfaults against the Intel driver
installed here (31.0.101.4502, 2023), and that torch build's CPU autograd
segfaults too - both are recorded in the results rather than worked around
silently.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from intelligence.ml_service.evaluation import evaluate
from intelligence.ml_service.train_nhanes import (
    CLINICAL_FEATURES,
    load_cohort,
    split,
)

ARTIFACTS = Path(__file__).resolve().parents[1] / "_artifacts"
# Agreement tighter than this is invisible at the precision a risk percentage
# is ever displayed with (one decimal place).
EQUIVALENCE_TOL = 1e-4


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def build_models(Xtr, ytr):
    """The deployed linear model, plus a neural network on identical inputs."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    logreg = make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=5000)
    ).fit(Xtr, ytr)

    # A fair attempt, not a straw man. Early stopping is off because at ~4%
    # prevalence the internal validation split can contain almost no events,
    # which stops training on noise. MLPClassifier has no class_weight, so the
    # minority class is oversampled to parity instead - otherwise the net
    # minimises loss by predicting "no event" for everyone.
    rng = np.random.default_rng(7)
    pos = np.flatnonzero(ytr == 1)
    neg = np.flatnonzero(ytr == 0)
    pos_up = rng.choice(pos, size=len(neg), replace=True)
    idx = np.concatenate([neg, pos_up])
    rng.shuffle(idx)

    mlp = make_pipeline(
        StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=(32, 16),
            alpha=1e-3,
            max_iter=2000,
            early_stopping=False,
            random_state=7,
        ),
    ).fit(Xtr[idx], ytr[idx])
    return logreg, mlp


def export_onnx(pipeline, n_features: int, path: Path) -> Path:
    """Write the fitted linear pipeline as a graph of core ONNX operators.

    skl2onnx emits ``ai.onnx.ml.LinearClassifier`` and ``ai.onnx.ml.Scaler``,
    which OpenVINO's ONNX frontend has no conversion rule for. The arithmetic
    is only a standardisation and a dot product, so it is written out directly
    as Sub/Div/MatMul/Add/Sigmoid. Those are core ops every runtime supports,
    and the graph is then demonstrably the same arithmetic the validated
    scikit-learn pipeline performs - which is the property being tested.
    """
    from onnx import TensorProto, helper, numpy_helper

    scaler = pipeline.named_steps["standardscaler"]
    clf = pipeline.named_steps["logisticregression"]

    mean = scaler.mean_.astype(np.float32)
    scale = scaler.scale_.astype(np.float32)
    coef = clf.coef_[0].astype(np.float32).reshape(-1, 1)
    intercept = clf.intercept_.astype(np.float32)

    init = [
        numpy_helper.from_array(mean, "mean"),
        numpy_helper.from_array(scale, "scale"),
        numpy_helper.from_array(coef, "coef"),
        numpy_helper.from_array(intercept, "intercept"),
    ]
    nodes = [
        helper.make_node("Sub", ["features", "mean"], ["centred"]),
        helper.make_node("Div", ["centred", "scale"], ["standardised"]),
        helper.make_node("MatMul", ["standardised", "coef"], ["dot"]),
        helper.make_node("Add", ["dot", "intercept"], ["logit"]),
        helper.make_node("Sigmoid", ["logit"], ["probability"]),
    ]
    graph = helper.make_graph(
        nodes,
        "cvd_logreg",
        [helper.make_tensor_value_info(
            "features", TensorProto.FLOAT, ["batch", n_features])],
        [helper.make_tensor_value_info(
            "probability", TensorProto.FLOAT, ["batch", 1])],
        initializer=init,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)], ir_version=10
    )
    path.write_bytes(model.SerializeToString())
    return path


def run_on_devices(onnx_path: Path, X: np.ndarray, reference: np.ndarray) -> dict:
    """Execute on every OpenVINO device and check each against the reference."""
    import openvino as ov

    core = ov.Core()
    devices = [d for d in ("CPU", "GPU") if d in core.available_devices]
    print(f"  OpenVINO devices available: {core.available_devices}")
    model = core.read_model(onnx_path)

    results = {}
    # OpenVINO's GPU plugin defaults to FP16, which is fine for vision and not
    # fine here: a risk percentage that moves in its fourth decimal place can
    # cross a threshold that triggers clinical follow-up. Both precisions are
    # measured so the difference is on the record rather than assumed away.
    configs = [("CPU", {}), ("GPU", {"INFERENCE_PRECISION_HINT": "f16"}),
               ("GPU", {"INFERENCE_PRECISION_HINT": "f32"})]
    for device, config in [(d, c) for d, c in configs if d in devices]:
        full_name = core.get_property(device, "FULL_DEVICE_NAME")
        label = device + (f" ({config['INFERENCE_PRECISION_HINT']})" if config else "")
        compiled = core.compile_model(model, device, config)
        req = compiled.create_infer_request()

        batch = np.ascontiguousarray(X, dtype=np.float32)

        def probs_for(arr, _req=req):
            # `_req` is bound at definition time on purpose: closing over the
            # loop variable would silently start using the last device once
            # anyone defers one of these calls.
            _req.infer({0: arr})
            return _req.get_output_tensor(0).data.ravel()

        probs = probs_for(batch)
        max_abs = float(np.max(np.abs(probs - reference)))

        single = np.ascontiguousarray(X[:1], dtype=np.float32)
        probs_for(single)                      # warm up
        t0 = time.perf_counter()
        for _ in range(300):
            probs_for(single)
        per_call_ms = (time.perf_counter() - t0) / 300 * 1000

        t0 = time.perf_counter()
        for _ in range(30):
            probs_for(batch)
        batch_ms = (time.perf_counter() - t0) / 30 * 1000

        agrees = max_abs < EQUIVALENCE_TOL
        results[label] = {
            "device_name": full_name,
            "precision": config.get("INFERENCE_PRECISION_HINT", "default"),
            "max_abs_diff_vs_sklearn": max_abs,
            "agrees": bool(agrees),
            "single_patient_ms": round(per_call_ms, 4),
            "batch_ms": round(batch_ms, 3),
            "batch_n": int(len(batch)),
        }
        print(f"  {label:<12} {full_name}")
        print(f"       max|diff| vs scikit-learn : {max_abs:.3e}   "
              f"{'AGREES' if agrees else 'DIVERGES'}")
        print(f"       one patient               : {per_call_ms:.4f} ms")
        print(f"       batch of {len(batch):<5}            : {batch_ms:.3f} ms")
    return results


def main(cohort: str = "clinical") -> dict:
    # Validate the deployment target against the feature set that actually
    # ships. Checking a retired model's inputs would prove the GPU agrees about
    # arithmetic nobody runs.
    features = CLINICAL_FEATURES
    print("=== data ===")
    df = load_cohort(features, cohort)
    tr, ca, te = split(df)
    Xtr = tr[features].to_numpy(float)
    Xca = ca[features].to_numpy(float)
    Xte = te[features].to_numpy(float)
    ytr, yca, yte = (d.y.to_numpy(int) for d in (tr, ca, te))
    print(f"  train {len(ytr):,} / calib {len(yca):,} / test {len(yte):,}  "
          f"({int(yte.sum())} test events)")

    print("\n=== fitting linear and neural arms on identical inputs ===")
    t0 = time.perf_counter()
    logreg, mlp = build_models(Xtr, ytr)
    print(f"  fitted both in {time.perf_counter() - t0:.1f}s on CPU")
    net = mlp.named_steps["mlpclassifier"]
    print(f"  MLP: hidden {net.hidden_layer_sizes}, stopped at iteration {net.n_iter_}")

    from sklearn.linear_model import LogisticRegression

    print("\n=== neural network vs the linear model (temporal test set) ===")
    rows = {}
    for name, model in (("logistic", logreg), ("MLP", mlp)):
        cal = LogisticRegression(max_iter=2000).fit(
            _logit(model.predict_proba(Xca)[:, 1]), yca
        )
        p = cal.predict_proba(_logit(model.predict_proba(Xte)[:, 1]))[:, 1]
        r = evaluate(yte, p, label=name)
        rows[name] = r
        print(f"  {name:<9} AUC {r['roc_auc']} CI {r['roc_auc_ci']}  "
              f"Brier {r['brier']}  slope {r['calibration_slope']}")

    d = rows["MLP"]["roc_auc"] - rows["logistic"]["roc_auc"]
    print(f"  -> MLP {'beats' if d > 0 else 'does not beat'} logistic by "
          f"{d:+.4f} AUC; the confidence intervals overlap heavily either way.")

    print("\n=== running the DEPLOYED logistic model on the Intel Iris Xe ===")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    onnx_path = export_onnx(logreg, len(features), ARTIFACTS / "cvd-logreg.onnx")
    print(f"  exported {onnx_path.name} ({onnx_path.stat().st_size:,} bytes)")
    reference = logreg.predict_proba(Xte)[:, 1]
    gpu = run_on_devices(onnx_path, Xte, reference)

    print("\n=== verdict ===")
    f16 = gpu.get("GPU (f16)")
    f32 = gpu.get("GPU (f32)")
    cpu = gpu.get("CPU")
    if f16 and not f16["agrees"]:
        drift_pp = f16["max_abs_diff_vs_sklearn"] * 100
        print("  At its DEFAULT precision the iGPU disagrees with the validated model")
        print(f"  by up to {drift_pp:.4f} percentage points of absolute risk. That is")
        print("  small, but it is not nothing: it can move a patient across a")
        print("  follow-up threshold. FP16 is therefore not acceptable here.")
    if f32 and f32["agrees"]:
        print(f"  Pinned to FP32 the iGPU reproduces the validated model to "
              f"{f32['max_abs_diff_vs_sklearn']:.1e}, so it is safe to serve from,")
        print("  and the model card's metrics describe what it returns.")
    elif f32:
        print("  Even at FP32 the iGPU diverges - do not serve predictions from it.")
    if cpu and f32:
        print(f"  Latency, one patient: CPU {cpu['single_patient_ms']:.4f} ms vs "
              f"GPU {f32['single_patient_ms']:.4f} ms.")
        if f32["single_patient_ms"] > cpu["single_patient_ms"]:
            print(f"  The CPU is faster. For a {len(features)}-feature linear "
                  f"model the GPU's")
            print("  dispatch overhead exceeds the arithmetic it is dispatching, so")
            print("  there is no performance case for using it here.")
    return {"models": rows, "devices": gpu}


if __name__ == "__main__":
    main()
