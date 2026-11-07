"""The clean-up before OCR: it must fix the page's look and never fail a report."""
from __future__ import annotations

import pytest

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from intelligence.document.ocr import preprocess  # noqa: E402


def ruled_page(width: int = 1200, height: int = 1600) -> Image.Image:
    """Dark rows on white paper: enough for the row-finding to work on."""
    page = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(page)
    for y in range(120, height - 120, 44):
        for x in range(120, width - 120, 70):
            draw.rectangle((x, y, x + 50, y + 14), fill=20)
    return page


@pytest.mark.parametrize("angle", [-9.0, -3.0, -1.0, 1.0, 3.0, 9.0])
def test_tilt_is_found_either_way(angle):
    tilted = ruled_page().rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    # Turning by what was found undoes the tilt, so the sign is the opposite.
    assert preprocess.tilt_of(tilted) == pytest.approx(-angle, abs=0.25)


def test_a_level_page_is_left_alone():
    page = ruled_page()
    assert preprocess.straighten(page) is page


def test_a_blank_page_does_not_fail():
    blank = Image.new("L", (800, 1100), 255)
    assert preprocess.tilt_of(blank) == 0.0
    assert preprocess.prepare(blank).size[0] >= 800


def test_a_small_page_is_enlarged_but_not_without_limit():
    assert max(preprocess.prepare(ruled_page(600, 800)).size) == round(800 * preprocess.MAX_ENLARGE)
    assert max(preprocess.prepare(ruled_page(1200, 1650)).size) == preprocess.TARGET_LONG_SIDE


def test_a_large_page_keeps_its_size():
    assert preprocess.prepare(ruled_page(2500, 3500)).size == (2500, 3500)


def test_a_shadow_is_evened_out():
    page = np.asarray(ruled_page(), dtype=np.float32)
    shade = np.linspace(1.0, 0.4, page.shape[1])[None, :]
    shadowed = Image.fromarray((page * shade).astype(np.uint8))
    paper_left = np.asarray(shadowed)[40:80, 40:80].mean()
    paper_right = np.asarray(shadowed)[40:80, -80:-40].mean()
    assert paper_left - paper_right > 100

    fixed = np.asarray(preprocess._even_out_light(shadowed))
    assert abs(float(fixed[40:80, 40:80].mean()) - float(fixed[40:80, -80:-40].mean())) < 25


def test_faint_print_gets_its_contrast_back():
    page = np.asarray(ruled_page(), dtype=np.float32)
    faint = Image.fromarray((180 + page * 0.25).clip(0, 255).astype(np.uint8))
    assert np.asarray(faint).min() >= 180
    assert np.asarray(preprocess._even_out_light(faint)).min() < 60


def test_turning_keeps_the_whole_page():
    page = ruled_page(1000, 1400)
    assert preprocess.turned(page, 1).size == (1400, 1000)
    assert preprocess.turned(page, 2).size == (1000, 1400)
    assert preprocess.turned(page, 0) is page


def test_noise_is_quietened_only_on_a_grainy_page():
    clean = ruled_page()
    assert preprocess._quieten_noise(clean) is clean
    grain = np.random.default_rng(1).normal(0, 20, (1600, 1200))
    noisy = Image.fromarray(np.clip(np.asarray(clean, dtype=np.float32) + grain, 0, 255).astype(np.uint8))
    assert preprocess._quieten_noise(noisy) is not noisy
