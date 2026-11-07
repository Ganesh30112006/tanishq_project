"""Make a photo or scan easier to read before OCR.

Tesseract expects a flat, upright, evenly lit page at about 300 DPI. A phone photo
is none of these, and a tilt of under a degree used to lose almost every value.
Each step here only changes how the page looks to the engine: it can make a number
readable, and the checks after OCR still decide whether that number is used.

Only Pillow and NumPy are needed, and a step that cannot run leaves the page as it
was, so a failure here can never stop a report from being read.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

#: An A4 page at 300 DPI, the size Tesseract reads best. Smaller pages are enlarged.
TARGET_LONG_SIDE = 3300
MAX_ENLARGE = 3.0
#: The tilt searched for, either way. A photo tilted further than this is retaken.
MAX_TILT_DEGREES = 15.0
#: Below this tilt, rotating blurs the page by more than straightening helps.
MIN_TILT_DEGREES = 0.15


def prepare(image: Image.Image, *, drop_colour: bool = False) -> Image.Image:
    """The page, upright in its stored form, grey, enlarged, evenly lit and straight.

    ``drop_colour`` keeps only black print, removing coloured stamps and watermarks
    laid over the results. Never use it alone: many laboratories print an abnormal
    result in red, and this removes that too. It suits a second look at the page.
    """
    upright = ImageOps.exif_transpose(image)
    page = _black_print_only(upright) if drop_colour else upright.convert("L")
    page = _enlarge(page)
    page = _even_out_light(page)
    page = _quieten_noise(page)
    return straighten(page)


def has_colour(image: Image.Image) -> bool:
    """Whether any real colour is printed on the page, ignoring JPEG speckle."""
    if image.mode not in ("RGB", "RGBA", "P", "CMYK"):
        return False
    small = np.asarray(image.convert("RGB").resize((400, 400), Image.BILINEAR), dtype=np.int16)
    spread = small.max(axis=2) - small.min(axis=2)
    return float((spread > 60).mean()) > 0.001


def _black_print_only(image: Image.Image) -> Image.Image:
    """Each pixel's brightest channel: only true black stays dark in all three."""
    return Image.fromarray(np.asarray(image.convert("RGB")).max(axis=2).astype(np.uint8))


def _enlarge(page: Image.Image) -> Image.Image:
    long_side = max(page.size)
    if long_side >= TARGET_LONG_SIDE:
        return page
    scale = min(TARGET_LONG_SIDE / long_side, MAX_ENLARGE)
    return page.resize((round(page.width * scale), round(page.height * scale)), Image.LANCZOS)


def _even_out_light(page: Image.Image) -> Image.Image:
    """Divide out the paper's brightness, then stretch to full contrast.

    The paper is what stays when the print is removed, so a wide maximum filter on
    a small copy finds it. Shadows and faint print both go with this one step.
    """
    small = page.resize((max(page.width // 8, 1), max(page.height // 8, 1)), Image.BILINEAR)
    paper = small.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(12))
    paper_full = np.asarray(paper.resize(page.size, Image.BILINEAR), dtype=np.float32)
    grey = np.asarray(page, dtype=np.float32)
    flat = np.clip(grey / np.maximum(paper_full, 1.0), 0.0, 1.0)
    low, high = np.percentile(flat, (0.5, 99.5))
    if high - low < 0.02:  # a blank page: nothing to stretch
        return page
    return Image.fromarray((np.clip((flat - low) / (high - low), 0.0, 1.0) * 255).astype(np.uint8))


def _quieten_noise(page: Image.Image) -> Image.Image:
    """A small median filter, but only on a grainy page: it softens clean print."""
    grey = np.asarray(page, dtype=np.float32)
    paper = grey[grey > 200]
    if paper.size and float(paper.std()) > 6.0:
        return page.filter(ImageFilter.MedianFilter(3))
    return page


def tilt_of(page: Image.Image) -> float:
    """The tilt of the printed lines, in degrees. 0.0 if the page shows none.

    Rows of text make sharp peaks when the page is added up across each row, and the
    peaks are sharpest when the rows are level. A coarse sweep, then a fine one.
    """
    small = page.resize((max(page.width // 3, 1), max(page.height // 3, 1)), Image.BILINEAR)
    ink = Image.fromarray(((np.asarray(small) < 140) * 255).astype(np.uint8))
    if np.asarray(ink).mean() < 0.2:
        return 0.0

    def sharpness(angle: float) -> float:
        turned = np.asarray(ink.rotate(angle, resample=Image.NEAREST, fillcolor=0), dtype=np.float32)
        rows = turned.sum(axis=1)
        return float(((rows[1:] - rows[:-1]) ** 2).sum())

    def best(candidates: np.ndarray) -> float:
        return float(max(candidates, key=sharpness))

    coarse = best(np.arange(-MAX_TILT_DEGREES, MAX_TILT_DEGREES + 0.5, 1.0))
    fine = best(np.arange(coarse - 1.0, coarse + 1.01, 0.1))
    return round(fine, 2)


def straighten(page: Image.Image) -> Image.Image:
    angle = tilt_of(page)
    if abs(angle) < MIN_TILT_DEGREES:
        return page
    return page.rotate(angle, resample=Image.BICUBIC, fillcolor=255)


def turned(page: Image.Image, quarter_turns: int) -> Image.Image:
    """The page turned by whole quarter turns, without losing any of it."""
    return page.rotate(90 * quarter_turns, expand=True, fillcolor=255) if quarter_turns % 4 else page
