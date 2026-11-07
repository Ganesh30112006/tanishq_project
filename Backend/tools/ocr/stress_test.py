"""How much of a report OCR recovers, for each kind of image, against its text layer.

Truth is what the reader takes from the same PDF's text layer. These images are
simulated from PDFs, so a high score here is necessary, not proof of real photos.

    python -I ocr_eval.py <label> <tune|test|all> [option=value ...]
"""
import io
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

#: Where reports, models and results live. Never inside the repository: the
#: reports may name real people.
HERE = Path(os.environ.get("CARESENSE_OCR_WORK", Path.home() / "caresense-ocr"))
OLD = HERE / "reports"
NEW = HERE / "heldout_reports"

# max_cbc is left out: its header values are not drawn in the picture, so its dated
# table cannot be read from any image of it. It says nothing about OCR.
TUNE = [OLD / f"{n}.pdf" for n in ("max_care1", "lpl_wm14", "max_cardiac")] + [
    NEW / f"{n}.pdf" for n in ("labsmart_cbc-report-format", "labsmart_kft-report-format", "labsmart_lipid-profile-report-format")
]
#: Never used to choose a setting. Other labs where possible.
TEST = [OLD / f"{n}.pdf" for n in ("max_care2", "max_wellwise_ess")] + [
    NEW / f"{n}.pdf" for n in (
        "flabs_complete-blood-count-cbc", "flabs_liver-function-tests-lft", "flabs_kidney-function-tests",
        "flabs_lipid-profile-test", "drlogy_cbc", "labsmart_lft-report-format", "lpl_wm17s",
    )
]

#: Collected after every setting was chosen: neither model nor code was tuned on these.
FRESH = sorted((HERE / "fresh_reports").glob("healthflow_*.pdf"))


def _noise(im, sd, rng):
    a = np.asarray(im, dtype=np.int16)
    n = np.random.default_rng(rng.randint(0, 10**6)).normal(0, sd, a.shape)
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8))


def _shadow(im, strength):
    a = np.asarray(im, dtype=np.float32)
    h, w = a.shape
    x = np.linspace(1.0, 1.0 - strength, w)[None, :]
    y = np.linspace(1.0 - strength / 2, 1.0, h)[:, None]
    return Image.fromarray(np.clip(a * (x * y), 0, 255).astype(np.uint8))


def _perspective(im, amount):
    w, h = im.size
    d = amount * w
    coeffs = _coeffs([(d, 0), (w - d / 2, d / 3), (w, h), (0, h - d / 2)], [(0, 0), (w, 0), (w, h), (0, h)])
    return im.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=255)


def _coeffs(src, dst):
    m = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(m, dtype=float), np.array(src, dtype=float).reshape(8)).tolist()


def _rot(im, deg):
    return im.rotate(deg, resample=Image.BICUBIC, expand=deg % 90 == 0, fillcolor=255)


VARIANTS = {
    # name: (dpi, jpeg quality, transform)
    "clean_300dpi": (300, 90, lambda im, r: im),
    "scan_200dpi": (200, 75, lambda im, r: im),
    "lowres_150dpi": (150, 60, lambda im, r: im),
    "tilt_1deg": (300, 80, lambda im, r: _rot(im, 1)),
    "tilt_3deg": (300, 80, lambda im, r: _rot(im, -3)),
    "tilt_7deg": (300, 80, lambda im, r: _rot(im, 7)),
    "turned_90": (300, 80, lambda im, r: _rot(im, 90)),
    "upside_down": (300, 80, lambda im, r: _rot(im, 180)),
    "blurred": (300, 75, lambda im, r: im.filter(ImageFilter.GaussianBlur(1.2))),
    "noisy": (300, 75, lambda im, r: _noise(im, 18, r)),
    "shadow": (300, 75, lambda im, r: _shadow(im, 0.55)),
    "faint": (300, 75, lambda im, r: ImageEnhance.Contrast(im).enhance(0.35)),
    "perspective": (300, 75, lambda im, r: _perspective(im, 0.03)),
    "colour_scan": (300, 85, lambda im, r: im),
    "colour_photo": (220, 60, lambda im, r: _rot(im, 2).filter(ImageFilter.GaussianBlur(0.6))),
    "phone_photo": (220, 55, lambda im, r: _noise(_shadow(_perspective(_rot(im, 2), 0.02), 0.35).filter(ImageFilter.GaussianBlur(0.7)), 8, r)),
}


def degraded(path, variant, seed=7):
    import pypdfium2

    dpi, quality, fn = VARIANTS[variant]
    rng = random.Random(f"{seed}{path.stem}{variant}")  # noqa: S311 - repeatable image damage
    pdf = pypdfium2.PdfDocument(str(path))
    pages = []
    for i in range(len(pdf)):
        colour = variant.startswith("colour")
        rendered = pdf[i].render(scale=dpi / 72).to_pil()
        im = fn(rendered.convert("RGB") if colour else rendered.convert("L"), rng)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        pages.append(Image.open(buf).convert("RGB" if colour else "L"))
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    return out.getvalue()


def pairs(result):
    return {(x.value.analyte, round(x.value.value, 3)) for x in result.observed_values}


def apply_options(options):
    from intelligence.document.ocr import local

    for key, value in options.items():
        if key == "TESSDATA":
            os.environ["TESSDATA_PREFIX"] = value
        else:
            setattr(local, key, type(getattr(local, key))(value) if not isinstance(getattr(local, key), bool) else value == "1")


def one(job):
    import logging

    logging.disable(logging.WARNING)
    from intelligence.document import pipeline

    path, variant, options = job
    apply_options(options)
    started = time.time()
    truth = pairs(pipeline.process_document(path.read_bytes(), declared_type="application/pdf"))
    got = pairs(pipeline.process_document(degraded(path, variant), declared_type="application/pdf"))
    right = got & truth
    keys = {a for a, _ in truth}
    wrong = sorted(g for g in got if g[0] in keys and g not in truth)
    extra = sorted(g for g in got if g[0] not in keys)
    return {
        "doc": path.stem[:24], "variant": variant, "truth": len(truth), "right": len(right),
        "wrong": [list(w) for w in wrong], "extra": [list(e) for e in extra], "secs": round(time.time() - started, 1),
    }


def main():
    label, which = sys.argv[1], sys.argv[2]
    options = dict(a.split("=", 1) for a in sys.argv[3:] if "=" in a)
    only = options.pop("variants", "")
    docs = {"tune": TUNE, "test": TEST, "fresh": FRESH, "all": TUNE + TEST}[which]
    variants = only.split(",") if only else list(VARIANTS)
    jobs = [(d, v, options) for v in variants for d in docs]
    with ProcessPoolExecutor(max_workers=10) as pool:
        rows = list(pool.map(one, jobs))
    (HERE / f"ocr_eval_{label}_{which}.json").write_text(json.dumps(rows, indent=0))
    print(f"{'kind of image':16} {'right/truth':>12} {'%':>6} {'wrong':>6} {'extra':>6}  worst report")
    total_right = total_truth = total_wrong = 0
    for v in variants:
        sub = [r for r in rows if r["variant"] == v]
        right, truth, wrong = sum(r["right"] for r in sub), sum(r["truth"] for r in sub), sum(len(r["wrong"]) for r in sub)
        extra = sum(len(r["extra"]) for r in sub)
        total_right, total_truth, total_wrong = total_right + right, total_truth + truth, total_wrong + wrong
        worst = min(sub, key=lambda r: r["right"] / max(r["truth"], 1))
        print(f"{v:16} {right:5}/{truth:<6} {100 * right / max(truth, 1):5.1f} {wrong:6} {extra:6}  {worst['doc']} {worst['right']}/{worst['truth']}")
    print(f"{'ALL':16} {total_right:5}/{total_truth:<6} {100 * total_right / max(total_truth, 1):5.1f} {total_wrong:6}")
    for r in rows:
        if r["wrong"]:
            print("WRONG", r["variant"], r["doc"], r["wrong"][:6])


if __name__ == "__main__":
    main()
