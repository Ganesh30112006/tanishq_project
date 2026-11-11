"""Fine-tune Tesseract's LSTM on generated lab-report lines. CPU only: that is all
lstmtraining supports. Lines are made from a template, so there is no patient data,
and they are never used as accuracy evidence.

The stock model has no arrow characters, so a lab's "48 ↑" came out as "48 1" or
"48 t" and the row was refused. The character set is extended with ↑ and ↓ first,
from Tesseract's own script data (``langdata_lstm``: ``radical-stroke.txt`` and
``Latin.unicharset`` in ``$CARESENSE_OCR_WORK/langdata``).

    python train_tesseract.py <max_iterations>
"""
import os
import random
import subprocess
import sys
from pathlib import Path

#: Where reports, models and results live. Never inside the repository: the
#: reports may name real people.
HERE = Path(os.environ.get("CARESENSE_OCR_WORK", Path.home() / "caresense-ocr"))
BEST = HERE / "tessdata_best"
WORK = HERE / "ocr_training"
LANGDATA = HERE / "langdata"
BIN = Path(os.environ.get("TESSERACT_HOME", r"C:\Program Files\Tesseract-OCR"))
#: Flags some labs print beside an abnormal result, and the caret of "10^3/uL":
#: characters the stock model does not have, so it can never read them.
NEW_CHARACTERS = ["↑", "↓", "^"]
ITERATIONS = sys.argv[1] if len(sys.argv) > 1 else "3000"

FONTS_TRAIN = ["Arial", "Calibri", "Times New Roman", "Verdana", "Tahoma", "Segoe UI", "Cambria", "Consolas"]
FONTS_EVAL = ["Georgia", "Courier New"]

TESTS = [
    ("Haemoglobin", "g/dL", 8, 18, "12.0 - 15.0"), ("Hemoglobin (Hb)", "gm%", 8, 18, "13.0 - 17.0"),
    ("Total Leucocyte Count", "/cumm", 2500, 15000, "4000 - 10000"), ("TLC", "10^3/uL", 3, 15, "4.0 - 11.0"),
    ("RBC Count", "million/cumm", 3, 7, "4.5 - 5.5"), ("PCV", "%", 25, 55, "36 - 46"), ("MCV", "fL", 70, 110, "83 - 101"),
    ("MCH", "pg", 20, 36, "27 - 32"), ("MCHC", "g/dL", 28, 37, "31.5 - 34.5"), ("RDW-CV", "%", 10, 20, "11.6 - 14.0"),
    ("Platelet Count", "lakhs/cumm", 1, 5, "1.5 - 4.1"), ("Neutrophils", "%", 30, 90, "40 - 80"), ("Lymphocytes", "%", 10, 50, "20 - 40"),
    ("Monocytes", "%", 1, 12, "2 - 10"), ("Eosinophils", "%", 0, 9, "1 - 6"), ("Basophils", "%", 0, 2, "< 2"),
    ("Fasting Blood Sugar", "mg/dL", 60, 300, "70 - 100"), ("HbA1c", "%", 4, 14, "4.0 - 5.6"), ("Total Cholesterol", "mg/dL", 100, 320, "< 200"),
    ("HDL Cholesterol", "mg/dL", 20, 90, "> 40"), ("LDL Cholesterol", "mg/dL", 50, 220, "< 100"), ("Triglycerides", "mg/dL", 50, 500, "< 150"),
    ("Serum Creatinine", "mg/dL", 0, 6, "0.67 - 1.17"), ("Blood Urea", "mg/dL", 10, 120, "17 - 43"), ("Uric Acid", "mg/dL", 2, 11, "3.5 - 7.2"),
    ("eGFR", "mL/min/1.73m2", 15, 130, "> 59"), ("Sodium", "mEq/L", 120, 160, "136 - 146"), ("Potassium", "mmol/L", 2, 7, "3.5 - 5.1"),
    ("Chloride", "mEq/L", 85, 115, "101 - 109"), ("Calcium, Total", "mg/dL", 6, 13, "8.7 - 10.4"), ("SGOT (AST)", "U/L", 8, 300, "0 - 40"),
    ("SGPT (ALT)", "IU/L", 7, 300, "0 - 41"), ("Alkaline Phosphatase", "U/L", 30, 400, "30 - 120"), ("GGTP", "U/L", 5, 200, "0 - 55"),
    ("Bilirubin Total", "mg/dL", 0, 6, "0.30 - 1.20"), ("Bilirubin Direct", "mg/dL", 0, 3, "< 0.3"), ("Total Protein", "g/dL", 5, 9, "6.4 - 8.3"),
    ("Albumin", "g/dL", 2, 6, "3.5 - 5.2"), ("TSH", "uIU/mL", 0, 25, "0.27 - 4.2"), ("Free T3", "pg/mL", 1, 8, "2.0 - 4.4"),
    ("Free T4", "ng/dL", 0, 4, "0.8 - 1.8"), ("Vitamin B12", "pg/mL", 100, 1500, "211 - 911"), ("Ferritin", "ng/mL", 5, 600, "30 - 400"),
]
OTHER = [
    "Test Name Results Units Bio. Ref. Interval", "Investigation Result Reference Value Unit",
    "TEST DESCRIPTION RESULT ENTRY FLAG BIO. REF. RANGE UNIT", "Collection Date/Time : {d}/{m}/2026",
    "Date {d}/{m}/2026 {d}/{m}/25 Unit Bio Ref Interval", "COMPLETE BLOOD COUNT (CBC)", "LIVER FUNCTION TEST", "KIDNEY FUNCTION TEST",
    "LIPID PROFILE", "THYROID PROFILE", "Page 1 of 3", "End of Report",
]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def number(rng, low, high):
    value = rng.uniform(low, high)
    if high > 1000:
        return str(int(value) // 10 * 10)
    return rng.choice([str(int(value)), f"{value:.1f}", f"{value:.2f}"])


def row(rng):
    if rng.random() < 0.07:
        return rng.choice(OTHER).format(d=f"{rng.randint(1, 28):02d}", m=rng.choice(MONTHS))
    name, unit, low, high, reference = rng.choice(TESTS)
    value = number(rng, low, high)
    flag = rng.choice(["", "", "", " H", " L", " High", " Low", " ↑", " ↓", " ↑", " ↓"])
    shape = rng.randrange(4)
    if shape == 0:
        return f"{name} {value}{flag} {unit} {reference}"
    if shape == 1:
        return f"{name} {value}{flag} {reference} {unit}"
    if shape == 2:
        return f"{name}{flag} {value} {unit} {reference}"
    return f"{name} {unit} {reference} {value}"


def run(args, check=True):
    # lstmtraining only finds its files reliably on Windows when run inside WORK
    # with relative list files.
    done = subprocess.run([str(a) for a in args], capture_output=True, text=True, errors="replace", cwd=WORK)  # noqa: S603 - Tesseract tools
    if check and done.returncode != 0:
        print("FAILED", args[0], (done.stderr or done.stdout)[-400:])
        raise SystemExit(1)
    return done


def make(fonts, label, lines, seed):
    rng = random.Random(seed)  # noqa: S311 - repeatable training lines
    made = []
    for font in fonts:
        text = WORK / f"{label}_{font.replace(' ', '')}.txt"
        text.write_text("\n".join(row(rng) for _ in range(lines)), encoding="utf-8")
        base = WORK / text.stem
        done = run([BIN / "text2image.exe", f"--text={text}", f"--outputbase={base}", f"--font={font}",
                    r"--fonts_dir=C:\Windows\Fonts", "--ptsize=12", "--xsize=3400", "--ysize=4400",
                    "--max_pages=6", "--exposure=0"], check=False)
        if done.returncode != 0 or not base.with_suffix(".tif").exists():
            print("skip font", font, (done.stderr or "")[-160:].replace("\n", " "))
            continue
        run([BIN / "tesseract.exe", base.with_suffix(".tif"), base, "--tessdata-dir", BEST, "-l", "eng", "--psm", "6", BIN / "tessdata" / "configs" / "lstm.train"])
        if base.with_suffix(".lstmf").exists():
            made.append(base.with_suffix(".lstmf").name)
    listing = WORK / f"{label}.list"
    # Plain line ends: lstmtraining takes a Windows "\r" as part of the file name.
    listing.write_text("\n".join(made) + "\n", encoding="utf-8", newline="\n")
    print(label, "fonts", len(made), flush=True)
    if not made:
        raise SystemExit(f"no training data was made for {label}")
    return listing


def starter():
    """The stock character set plus the arrows, with the stock dictionaries."""
    run([BIN / "combine_tessdata.exe", "-u", BEST / "eng.traineddata", WORK / "eng."])
    for kind, name in (("word", "wordlist"), ("punc", "punc"), ("number", "numbers")):
        run([BIN / "dawg2wordlist.exe", "eng.lstm-unicharset", f"eng.lstm-{kind}-dawg", f"eng.{name}"])
    (WORK / "new.txt").write_text(" ".join(NEW_CHARACTERS), encoding="utf-8")
    run([BIN / "unicharset_extractor.exe", "--output_unicharset", "new.unicharset", "--norm_mode", "1", "new.txt"])
    run([BIN / "merge_unicharsets.exe", "eng.lstm-unicharset", "new.unicharset", "lab.unicharset"])
    (WORK / "starter" / "eng").mkdir(parents=True, exist_ok=True)  # the tool does not make it
    run([BIN / "combine_lang_model.exe", "--input_unicharset", "lab.unicharset", "--script_dir", LANGDATA,
         "--words", "eng.wordlist", "--puncs", "eng.punc", "--numbers", "eng.numbers", "--lang", "eng", "--output_dir", "starter"])
    made = WORK / "starter" / "eng" / "eng.traineddata"
    if not made.exists():
        raise SystemExit("the extended character set was not built")
    return made


def main():
    WORK.mkdir(exist_ok=True)
    for old in WORK.glob("lab*checkpoint"):
        old.unlink()  # a stale checkpoint would be taken for this run's result
    extended = starter()
    train = make(FONTS_TRAIN, "train", 900, 11)
    evaluation = make(FONTS_EVAL, "eval", 300, 12)
    print("before", run([BIN / "lstmeval.exe", "--model", BEST / "eng.traineddata", "--eval_listfile", evaluation.name], check=False).stderr[-120:].strip(), flush=True)
    done = run([BIN / "lstmtraining.exe", "--continue_from", "eng.lstm", "--old_traineddata", BEST / "eng.traineddata",
                "--traineddata", extended, "--model_output", "lab", "--train_listfile", train.name,
                "--eval_listfile", evaluation.name, "--max_iterations", ITERATIONS, "--learning_rate", "0.0001"], check=False)
    print((done.stderr or "")[-700:], flush=True)
    out = HERE / "tessdata_lab"
    out.mkdir(exist_ok=True)
    run([BIN / "lstmtraining.exe", "--stop_training", "--continue_from", "lab_checkpoint", "--traineddata", extended,
         "--model_output", out / "eng.traineddata"])
    print("after", run([BIN / "lstmeval.exe", "--model", out / "eng.traineddata", "--eval_listfile", evaluation.name], check=False).stderr[-120:].strip(), flush=True)
    print("model", (out / "eng.traineddata").stat().st_size // 1024 // 1024, "MB", flush=True)


if __name__ == "__main__":
    main()
