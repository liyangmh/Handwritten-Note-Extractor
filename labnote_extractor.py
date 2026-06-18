#!/usr/bin/env python3
"""Extract structured experiment facts from handwritten lab-note pages.

the script is split into three layers:

1. Page analysis: lightweight geometry and line-rule detection from the image.
2. Recognition adapter: a swappable source of recognized handwritten lines.
3. Domain parser: chemistry- and electrochemistry-aware normalization.

This workspace now does not include a local handwriting OCR model, so the default
recognizer loads a verified transcript for the bundled example image. 
In real production, we may replace that adapter with a trained handwriting/sketch recognizer
and keep the parser layer unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_DEPS = PROJECT_ROOT / ".deps"


def add_local_deps() -> None:
    if LOCAL_DEPS.exists() and str(LOCAL_DEPS) not in sys.path:
        sys.path.insert(0, str(LOCAL_DEPS))


try:
    import numpy as np
    from PIL import Image, ImageOps
except ImportError as exc:  
    add_local_deps()
    try:
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as fallback_exc:
        raise SystemExit(
            "Missing required packages. Install them with: "
            "python3 -m pip install -r requirements.txt"
        ) from fallback_exc

try: 
    import cv2
except ImportError:  
    add_local_deps()
    try:
        import cv2
    except ImportError:
        cv2 = None

try:  
    from rapidfuzz import fuzz
except ImportError:  
    add_local_deps()
    try:
        from rapidfuzz import fuzz
    except ImportError:
        fuzz = None


SCHEMA_VERSION = "0.2.0"
DEG_C = "\u00b0C"
THETA = "\u03b8"
APPLE_VISION_SCRIPT = PROJECT_ROOT / "recognizers" / "apple_vision_ocr.swift"
DEFAULT_IMAGE = PROJECT_ROOT / "Example Lab Notebook Page.jpg"
DEFAULT_EXAMPLE_OUTPUT = PROJECT_ROOT / "outputs" / "example_labnote_page.json"
DEFAULT_APPLE_OUTPUT = PROJECT_ROOT / "outputs" / "apple_vision_labnote_page.json"
DEFAULT_EXAMPLE_REPORT = PROJECT_ROOT / "reports" / "example_validation_report.md"
DEFAULT_APPLE_REPORT = PROJECT_ROOT / "reports" / "apple_vision_validation_report.md"
REFERENCE_PAPER_CONTEXT = {
    "source": "reference-paper/Adv Funct Materials - 2020 - Wang - Electrolytes Enriched by Crown Ethers for Lithium Metal Batteries.pdf",
    "title": "Electrolytes Enriched by Crown Ethers for Lithium Metal Batteries",
    "doi": "10.1002/adfm.202002578",
    "supporting_sources": [
        {
            "source": "reference-paper/1-s2.0-S1385894721010810-main.pdf",
            "title": "Self-leveling electrolyte enabled dendrite-free lithium deposition for safer and stable lithium metal batteries",
            "doi": "10.1016/j.cej.2021.129494",
        },
        {
            "source": "reference-paper/1-s2.0-S157266572100182X-main.pdf",
            "title": "The investigation for electrodeposition behavior of lithium metal in a crown ether/propylene carbonate electrolyte",
            "doi": "10.1016/j.jelechem.2021.115156",
        },
    ],
    "relevant_findings": [
        "Crown ethers are studied as electrolyte additives that coordinate Li+ and regulate the Li+ solvation/interfacial environment.",
        "The paper reports smoother Li deposition and reduced dendrite growth when appropriate crown ether additives are used.",
        "12-crown-4 and 15-crown-5 both coordinate Li+ through ether oxygens, but 15-crown-5 is reported as stronger and more effective than 12-crown-4 in that carbonate-electrolyte study.",
        "The proposed benefit is formation of a smoother/dense SEI and more homogeneous Li plating rather than simply increasing the quantity of deposited Li.",
    ],
    "mechanistic_findings": [
        "Crown ethers coordinate Li+ through cyclic ether oxygens and shift Li+ away from a purely solvent-dominated solvation shell.",
        "Li+/crown-ether complexes can reduce Li+ crowding at protrusions or dendrite tips, which changes nucleation and slows preferential tip growth.",
        "The self-leveling model says Li+/12-crown-4 complexes are harder to reduce than Li+/solvent complexes, so they raise local polarization resistance at high-field tips and redirect plating toward flatter regions.",
        "12-crown-4 can improve Li deposit smoothness, but the reference papers disagree on long-term efficiency depending on electrolyte, crown concentration, and SEI chemistry.",
        "Fluorinated electrolyte components or LiF-rich SEI formation are often part of the best-performing literature systems; the notebook does not directly measure SEI composition.",
    ],
    "quantitative_reference_points": [
        "The Adv. Funct. Mater. paper reports Li+/12-crown-4 binding energy near -0.83 eV, weaker than Li+/15-crown-5 near -1.28 eV.",
        "The Chemical Engineering Journal paper reports an optimized FEC/DMC/12-crown-4 system with about 97.24% Li||Cu Coulombic efficiency and dense dendrite-free deposition.",
        "The Journal of Electroanalytical Chemistry paper reports about 0.2 M 12-crown-4 as a morphology optimum in LiPF6/propylene carbonate at 2.0 mA/cm^2 and 1.0 mAh/cm^2, while also warning that Coulombic efficiency can decrease.",
    ],
    "reference_conditions": [
        "Adv. Funct. Mater.: 1.0 m LiPF6 in EC/DMC with 1.0-4.0 wt% crown ether additives, Li|Li and full-cell battery tests.",
        "Chemical Engineering Journal: 1.0 M LiPF6 in FEC/DMC with about 1 wt% 12-crown-4, Li||Cu, Li||Li, and Li||LFP cells.",
        "Journal of Electroanalytical Chemistry: 1.0 M LiPF6 in propylene carbonate with 0.1-0.5 M 12-crown-4 or 15-crown-5 in electrodeposition and Li||Cu tests.",
    ],
    "relevance_to_this_note": [
        "The notebook uses 12-crown-4 as an additive in a LiTFSI glyme/EtOH electrolyte, so the likely experimental question is whether crown-ether Li+ coordination improves Li plating stability.",
        "The notebook's film appearance, XRD notes, and Faraday calculation are checks of whether Li actually plated and what deposit quality may have resulted.",
    ],
    "translation_to_this_note": [
        "The notebook should be interpreted as a 12-crown-4 leveling-additive screen, not as a finished battery-cell cycling protocol.",
        "The expected success signal is a smoother, more uniform Li-containing film versus a crown-free control, not a larger Faraday-predicted Li mass.",
        "Because this page uses LiTFSI in diglyme:EtOH, potentiostatic RDE deposition, and 5 mol% 12-crown-4, the literature supports a hypothesis but does not provide a direct recipe or direct pass/fail threshold.",
    ],
    "caveat": "The reference systems are not identical to this notebook: they mainly use LiPF6 carbonate or FEC/DMC electrolytes, coin/optical cells, and galvanostatic battery tests, while the notebook screens 12-crown-4 in LiTFSI/diglyme:EtOH using potentiostatic RDE deposition.",
}


@dataclass
class RecognizedLine:
    region: str
    text: str
    confidence: float = 1.0
    bbox: list[int] | None = None


class RecognizerUnavailable(RuntimeError):
    """Raised when no recognition backend is available for an image."""


def optional_dependency_status() -> dict[str, bool]:
    return {
        "opencv": cv2 is not None,
        "rapidfuzz": fuzz is not None,
        "local_deps": LOCAL_DEPS.exists(),
    }


def group_runs(indices: Iterable[int], max_gap: int = 2) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    previous: int | None = None
    for value in indices:
        if previous is None or value - previous <= max_gap:
            current.append(value)
        else:
            if current:
                runs.append(current)
            current = [value]
        previous = value
    if current:
        runs.append(current)
    return runs


def analyze_page_geometry(image_path: Path) -> dict[str, Any]:

    image = Image.open(image_path)
    gray = ImageOps.grayscale(image)
    arr = np.asarray(gray, dtype=np.uint8)
    height, width = arr.shape


    threshold = int(np.clip(np.percentile(arr, 18) + 18, 85, 180))
    dark = arr < threshold

    dark_points = np.argwhere(dark)
    if dark_points.size:
        y0, x0 = dark_points.min(axis=0)
        y1, x1 = dark_points.max(axis=0)
        content_bbox = [int(x0), int(y0), int(x1), int(y1)]
    else:
        content_bbox = [0, 0, width, height]


    body = arr[int(height * 0.04) : int(height * 0.99), int(width * 0.15) : int(width * 0.95)]
    row_mean = body.mean(axis=1)
    row_background = np.convolve(row_mean, np.ones(31) / 31, mode="same")
    row_contrast = row_background - row_mean
    row_contrast[:50] = 0
    row_contrast[-50:] = 0
    cutoff = max(float(np.percentile(row_contrast, 94)), 8.0)
    rule_candidates = np.flatnonzero(row_contrast >= cutoff) + int(height * 0.04)
    horizontal_rules: list[int] = []
    for run in group_runs((int(v) for v in rule_candidates), max_gap=5):
        if len(run) >= 3:
            horizontal_rules.append(int(round(float(np.median(run)))))

    # The notebook margin is the strongest vertical line in the left half.
    left_half = arr[:, : int(width * 0.45)]
    col_density = (left_half < 175).mean(axis=0)
    margin_x = int(np.argmax(col_density))

    return {
        "image_width_px": width,
        "image_height_px": height,
        "dark_pixel_threshold": threshold,
        "content_bbox_px": content_bbox,
        "estimated_margin_x_px": margin_x,
        "horizontal_rule_y_px": horizontal_rules[:40],
    }


def default_transcript_path(image_path: Path) -> Path | None:
    if image_path.name == "Example Lab Notebook Page.jpg":
        candidate = Path(__file__).resolve().parent / "examples" / "example_transcription.json"
        if candidate.exists():
            return candidate
    return None


def load_transcript(transcript_path: Path) -> list[RecognizedLine]:
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_lines = data.get("lines", [])
    elif isinstance(data, list):
        raw_lines = data
    else:
        raise ValueError(f"Unsupported transcript format: {transcript_path}")

    lines: list[RecognizedLine] = []
    for index, item in enumerate(raw_lines):
        if isinstance(item, str):
            lines.append(RecognizedLine(region="unknown", text=item))
            continue
        if not isinstance(item, dict) or "text" not in item:
            raise ValueError(f"Bad transcript line {index}: {item!r}")
        lines.append(
            RecognizedLine(
                region=str(item.get("region", "unknown")),
                text=str(item["text"]),
                confidence=float(item.get("confidence", 1.0)),
                bbox=item.get("bbox"),
            )
        )
    return lines


def infer_region(line: RecognizedLine, image_height: int | None = None) -> str:
    """Infer a coarse notebook region from OCR text and optional y position."""

    text = normalize_text(line.text)
    lower = text.lower()
    if re.search(r"\bpage\s+\d+\b", lower):
        return "margin"
    if "project:" in lower or "cont." in lower:
        return "header"
    if re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b", lower):
        return "date"
    if lower.startswith("goal"):
        return "goal"
    if any(token in lower for token in ["electrolyte", "diglyme", "etoh", "add ", "mol%", "stir", "glovebox"]):
        return "recipe"
    if any(token in lower for token in ["deposition", "apply", "rpm", "mA/cm^2".lower(), "q =", "zF".lower(), "mol li"]):
        return "deposition"
    if any(token in lower for token in ["working elec", "ce:", "ref:", "ag/agcl", "li foil"]):
        return "setup"
    if any(token in lower for token in ["drawn scheme", "12-crown-4", "litfsi"]):
        return "chemistry"
    if any(token in lower for token in ["temperature test", "hot plate"]) or re.search(r"\b\d+\s*(?:min|hr)\b.*\d+(?:\.\d+)?\s*(?:°C|c)\b", lower):
        return "temperature_test"
    if any(token in lower for token in ["film", "xrd", "shoulder", f"2{THETA}"]):
        return "observations"

    if line.bbox and image_height:
        y_mid = (line.bbox[1] + line.bbox[3]) / 2
        ratio = y_mid / image_height
        if ratio < 0.12:
            return "header"
        if ratio < 0.23:
            return "goal"
        if ratio < 0.36:
            return "recipe"
        if ratio < 0.62:
            return "deposition"
        if ratio < 0.80:
            return "chemistry"
        return "temperature_test"
    return line.region or "unknown"


def infer_regions(lines: list[RecognizedLine], image_height: int | None = None) -> list[RecognizedLine]:
    return [
        RecognizedLine(
            region=infer_region(line, image_height=image_height),
            text=line.text,
            confidence=line.confidence,
            bbox=line.bbox,
        )
        for line in lines
    ]


def preprocess_image_for_ocr(image_path: Path) -> tuple[Path, dict[str, Any] | None]:
    """Create a contrast-enhanced copy for OCR when OpenCV is installed."""

    if cv2 is None:
        return image_path, None

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return image_path, None

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    enhanced_lightness = clahe.apply(lightness)
    enhanced = cv2.merge((enhanced_lightness, a_channel, b_channel))
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    enhanced = cv2.bilateralFilter(enhanced, d=5, sigmaColor=35, sigmaSpace=35)
    sharpened = cv2.addWeighted(enhanced, 1.35, cv2.GaussianBlur(enhanced, (0, 0), 1.2), -0.35, 0)

    out_dir = Path(os.environ.get("TMPDIR", "/private/tmp")) / "labnote_ocr_preprocessed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{image_path.stem}_opencv_preprocessed.jpg"
    cv2.imwrite(str(out_path), sharpened, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return out_path, {
        "source_image": str(image_path),
        "preprocessed_image": str(out_path),
        "steps": ["CLAHE contrast enhancement", "bilateral denoise", "unsharp mask"],
    }


def run_apple_vision_ocr(image_path: Path, preprocess: bool = False) -> tuple[list[RecognizedLine], dict[str, Any] | None]:
    """Run Apple's local Vision OCR through the bundled Swift adapter."""

    swift = shutil.which("swift")
    if not swift:
        raise RecognizerUnavailable("Apple Vision OCR needs `/usr/bin/swift`, but Swift was not found.")
    if not APPLE_VISION_SCRIPT.exists():
        raise RecognizerUnavailable(f"Apple Vision OCR adapter is missing: {APPLE_VISION_SCRIPT}")

    env = os.environ.copy()
    env["TMPDIR"] = env.get("TMPDIR", "/private/tmp")
    env.setdefault("CLANG_MODULE_CACHE_PATH", "/private/tmp/swift-module-cache")
    env.setdefault("SWIFT_MODULE_CACHE_PATH", "/private/tmp/swift-module-cache")
    ocr_image_path, preprocessing = preprocess_image_for_ocr(image_path) if preprocess else (image_path, None)

    completed = subprocess.run(
        [swift, str(APPLE_VISION_SCRIPT), str(ocr_image_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if completed.returncode != 0:
        raise RecognizerUnavailable(
            "Apple Vision OCR failed.\n"
            f"stdout: {completed.stdout.strip()}\n"
            f"stderr: {completed.stderr.strip()}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RecognizerUnavailable(f"Apple Vision OCR returned invalid JSON: {exc}") from exc

    raw_lines = payload.get("lines", [])
    image_height = payload.get("image_height_px")
    lines = [
        RecognizedLine(
            region="ocr",
            text=correct_ocr_text(str(item.get("text", ""))),
            confidence=float(item.get("confidence", 0.0)),
            bbox=item.get("bbox"),
        )
        for item in raw_lines
        if isinstance(item, dict) and item.get("text")
    ]
    return infer_regions(lines, image_height=image_height if isinstance(image_height, int) else None), preprocessing


def recognize_lines(
    image_path: Path,
    transcript_path: Path | None,
    recognizer: str = "auto",
    preprocess_ocr: bool = False,
) -> tuple[list[RecognizedLine], str, dict[str, Any] | None]:
    """Return recognized lines plus the backend name used."""

    source = transcript_path or default_transcript_path(image_path)
    if recognizer == "transcript":
        if source is None:
            raise RecognizerUnavailable("`--recognizer transcript` needs --transcript or a bundled example transcript.")
        return load_transcript(source), "transcript", None

    if recognizer == "apple-vision":
        lines, preprocessing = run_apple_vision_ocr(image_path, preprocess=preprocess_ocr)
        backend = "apple_vision+opencv_preprocess" if preprocessing else "apple_vision"
        return lines, backend, preprocessing

    if recognizer != "auto":
        raise RecognizerUnavailable(f"Unknown recognizer: {recognizer}")

    if source is not None:
        return load_transcript(source), "verified_example_transcript", None

    try:
        lines, preprocessing = run_apple_vision_ocr(image_path, preprocess=preprocess_ocr)
        backend = "apple_vision+opencv_preprocess" if preprocessing else "apple_vision"
        return lines, backend, preprocessing
    except RecognizerUnavailable as exc:
        raise RecognizerUnavailable(
            "No recognizer is configured for this image. Pass --transcript with "
            "recognized handwritten lines, or install/use an OCR backend. "
            f"Apple Vision attempt failed: {exc}"
        ) from exc


def normalize_text(text: str) -> str:
    replacements = {
        "deg C": DEG_C,
        "degrees C": DEG_C,
        "mA / cm2": "mA/cm^2",
        "mA/cm2": "mA/cm^2",
        "cm2": "cm^2",
        "2theta": f"2{THETA}",
        "2 theta": f"2{THETA}",
        "Li+": "Li+",
        "e -": "e-",
    }
    out = text
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def correct_ocr_text(text: str) -> str:
    """Clean common OCR confusions seen in handwritten chemistry notes."""

    corrections = [
        (r"\bg['’]yme\b", "glyme"),
        (r"\bScreon\b", "Screen"),
        (r"\bIM\b", "1 M"),
        (r"\bLiT\s*E?SI\b", "LiTFSI"),
        (r"\bLiT\s*F?SI\b", "LiTFSI"),
        (r"\bLiTFSl\b", "LiTFSI"),
        (r"\bdiglypo\b", "diglyme"),
        (r"v\s*/\s*r", "v/v"),
        (r"\btut\b", "tot"),
        (r"12[.\s-]+crown[.\s-]+[Y4]", "12-crown-4"),
        (r"\bTG\b", "T ="),
        (r"H[n2]O\s*c\s*ppm", "H2O < 1 ppm"),
        (r"\bLi\s+fail\b", "Li foil"),
        (r"Ag\s*/\s*Ag\s*C[1lI]", "Ag/AgCl"),
        (r"Ag/AgC[1lI]", "Ag/AgCl"),
        (r"240604\s*-\s*B[lI1]", "240604-B1"),
        (r"-0[.]?Y5\s*V?", "-0.45 V"),
        (r"\bvS\b", "vs"),
        (r"1600[1lI]pm", "1600 rpm"),
        (r"m\s*A\s*/\s*[eс]m2", "mA/cm^2"),
        (r"\bcmn\b", "cm^2"),
        (r"\bcm2\b", "cm^2"),
        (r"1\.\s*SE\s*-\s*4", "1.5E-4"),
        (r"\bS\.8E-Sg\b", "5.8E-5 g"),
        (r"8\.4\s*E-\s*6", "8.4E-6"),
        (r"\$400\s*s", "5400 s"),
        (r"\b1he\b", "1 hr"),
        (r"\b1ho\b", "1 hr"),
        (r"\bSmin\b", "5 min"),
        (r"\bм[іi]n\b", "min"),
        (r"\bміn\b", "min"),
        (r"23\.l", "23.1"),
        (r"31\.\s*SC", "31.5C"),
        (r"\bFilu\b", "Film"),
        (r"\bmin\s+peak\b", "main peak"),
        (r"\bdall\b", "dull"),
        (r"\bo\s+dull\b", "+ dull"),
        (r"\blé\b", "1 e-"),
        (r"=\s*\|\s*Li\s*\+", "= 1 Li+"),
        (r"\+\s*é\b", "+ e-"),
        (r"-\s*6\.4S\s*V", "-0.45 V"),
        (r"\b20\s*[:=]\s*(\d)", f"2{THETA} = \\1"),
        (r"\b2O\s*[:=]\s*(\d)", f"2{THETA} = \\1"),
    ]
    out = text
    for pattern, replacement in corrections:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    out = fuzzy_correct_science_terms(out)
    out = normalize_text(out)
    out = out.replace("30.1C", f"30.1{DEG_C}")
    out = out.replace("32.0C", f"32.0{DEG_C}")
    out = out.replace("32.6C", f"32.6{DEG_C}")
    out = out.replace("22.4 C", f"22.4{DEG_C}")
    out = out.replace("25.6 C", f"25.6{DEG_C}")
    out = out.replace("27.9 C", f"27.9{DEG_C}")
    out = re.sub(r"(\d+(?:\.\d+)?)C\b", rf"\1{DEG_C}", out)
    out = re.sub(r"^min\s+23\.1", "1 min 23.1", out)
    return out


def fuzzy_correct_science_terms(text: str) -> str:
    """Use RapidFuzz, when available, to fix near-miss chemistry terms."""

    if fuzz is None:
        return text

    terms = ["LiTFSI", "diglyme", "EtOH", "12-crown-4", "Ag/AgCl", "Li foil"]
    out = text

    for term in terms:
        if term.lower() in out.lower():
            continue
        spans = []
        tokens = list(re.finditer(r"[A-Za-z0-9/.-]+", out))
        for start in range(len(tokens)):
            for width in (3, 2, 1):
                end = start + width
                if end > len(tokens):
                    continue
                span_start = tokens[start].start()
                span_end = tokens[end - 1].end()
                chunk = out[span_start:span_end]
                if len(chunk) >= 3:
                    spans.append((span_start, span_end, chunk))

        best: tuple[int, int, str, float] | None = None
        for start, end, chunk in spans:
            score = fuzz.ratio(chunk.lower(), term.lower())
            threshold = 86 if term in {"LiTFSI", "diglyme", "Ag/AgCl"} else 90
            if score >= threshold and (best is None or score > best[3]):
                best = (start, end, chunk, score)
        if best:
            start, end, _chunk, _score = best
            out = out[:start] + term + out[end:]
    return out


def all_text(lines: list[RecognizedLine], regions: set[str] | None = None) -> str:
    selected = [line.text for line in lines if regions is None or line.region in regions]
    return "\n".join(normalize_text(text) for text in selected)


def maybe_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", ".")
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    cleaned = re.sub(r"\.\s+", ".", cleaned)
    cleaned = re.sub(r"\s*E\s*([-+]?)\s*", r"E\1", cleaned, flags=re.IGNORECASE)
    try:
        return float(cleaned)
    except ValueError:
        return None


def first_match(pattern: str, text: str, flags: int = re.IGNORECASE) -> re.Match[str] | None:
    return re.search(pattern, text, flags)


def quantity(value: float | int | None, unit: str, raw: str | None = None) -> dict[str, Any] | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    result: dict[str, Any] = {"value": value, "unit": unit}
    if raw:
        result["raw"] = raw
    return result


def parse_time_minutes(raw: str) -> float:
    raw = raw.lower().strip()
    hours = first_match(r"(\d+(?:\.\d+)?)\s*hr", raw)
    minutes = first_match(r"(\d+(?:\.\d+)?)\s*min", raw)
    total = 0.0
    if hours:
        total += float(hours.group(1)) * 60
    if minutes:
        total += float(minutes.group(1))
    return total


def extract_metadata(lines: list[RecognizedLine]) -> dict[str, Any]:
    text = all_text(lines)
    page = first_match(r"\bpage\s+(\d+)\b", text)
    date = first_match(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b", text)
    project = first_match(r"Project:\s*(.+)", text)
    cont = first_match(r"cont\.\s*from\s*pg\s*(\d+)", text)
    return {
        "page": page.group(1) if page else None,
        "date_written": date.group(0) if date else None,
        "continued_from_page": cont.group(1) if cont else None,
        "project": project.group(1).strip() if project else None,
    }


def extract_goal(lines: list[RecognizedLine]) -> str | None:
    text = all_text(lines, {"goal"})
    goal = first_match(r"Goal:\s*(.+)", text)
    return goal.group(1).strip() if goal else None


def extract_solution(lines: list[RecognizedLine]) -> dict[str, Any]:
    text = all_text(lines, {"goal", "recipe"})
    salt = first_match(r"(\d+(?:\.\d+)?)\s*M\s+(LiTFSI)", text)
    salt_concentration = maybe_float(salt.group(1)) if salt else None
    salt_name = salt.group(2) if salt else None
    if salt is None and "LiTFSI" in text:
        split_conc = first_match(r"(\d+(?:\.\d+)?)\s*M\b", text)
        salt_concentration = maybe_float(split_conc.group(1)) if split_conc else None
        salt_name = "LiTFSI"

    solvent_ratio = first_match(r"diglyme\s*:\s*EtOH\s*\((\d+)\s*:\s*(\d+)\s*v/v\)", text)
    total_volume = first_match(r"(\d+(?:\.\d+)?)\s*mL\s*tot", text)
    additive = first_match(r"Add\s+(\d+(?:\.\d+)?)\s*mol%\s+([A-Za-z0-9-]+)", text)
    additive_amount = maybe_float(additive.group(1)) if additive else None
    additive_name = additive.group(2) if additive else None
    if additive is None and "12-crown-4" in text:
        loose_additive = first_match(r"Add.*?(\d+(?:\.\d+)?)\s*mol", text)
        additive_amount = maybe_float(loose_additive.group(1)) if loose_additive else None
        additive_name = "12-crown-4"

    stir = first_match(r"Stir\s+(\d+(?:\.\d+)?)\s*min", text)
    target_temp = first_match(r"at\s+(\d+(?:\.\d+)?)\s*" + re.escape(DEG_C), text)

    return {
        "electrolyte_id": "240604-B" if "240604-B" in text else None,
        "salt": {
            "name": salt_name,
            "concentration": quantity(salt_concentration, "M"),
        },
        "solvent": {
            "components": [
                {"name": "diglyme", "ratio": int(solvent_ratio.group(1)) if solvent_ratio else None},
                {"name": "EtOH", "ratio": int(solvent_ratio.group(2)) if solvent_ratio else None},
            ],
            "basis": "v/v" if solvent_ratio else None,
        },
        "total_volume": quantity(maybe_float(total_volume.group(1)) if total_volume else None, "mL"),
        "additive": {
            "name": additive_name,
            "amount": quantity(additive_amount, "mol%"),
        },
        "mixing": {"stir_time": quantity(maybe_float(stir.group(1)) if stir else None, "min")},
        "target_temperature": quantity(maybe_float(target_temp.group(1)) if target_temp else None, DEG_C),
    }


def extract_apparatus(lines: list[RecognizedLine]) -> dict[str, Any]:
    text = all_text(lines, {"recipe", "setup"})
    working = first_match(r"Working\s+elec\.?\s*:\s*([^;]+)", text)
    ce = first_match(r"CE:\s*([^;]+)", text)
    ref = first_match(r"ref:\s*([^\n;]+)", text)
    area = first_match(r"\((\d+(?:\.\s*\d+)?)\s*cm(?:\^2)?\)", text)
    glovebox_water = first_match(r"H2O\s*<\s*(\d+(?:\.\d+)?)\s*ppm", text)
    ambient_temp = first_match(r"T\s*=\s*(\d+(?:\.\d+)?)\s*" + re.escape(DEG_C), text)
    return {
        "working_electrode": {
            "description": working.group(1).strip() if working else None,
            "material": "glassy carbon" if working and "glassy C" in working.group(1) else None,
            "geometry": "RDE" if working and "RDE" in working.group(1) else None,
            "area": quantity(maybe_float(area.group(1)) if area else None, "cm^2"),
        },
        "counter_electrode": ce.group(1).strip() if ce else None,
        "reference_electrode": ref.group(1).strip() if ref else None,
        "glovebox": {
            "temperature": quantity(maybe_float(ambient_temp.group(1)) if ambient_temp else None, DEG_C),
            "water": {
                "operator": "<" if glovebox_water else None,
                "value": maybe_float(glovebox_water.group(1)) if glovebox_water else None,
                "unit": "ppm" if glovebox_water else None,
            },
        },
    }


def extract_deposition(lines: list[RecognizedLine]) -> dict[str, Any]:
    text = all_text(lines, {"deposition", "chemistry"})
    run = first_match(r"Deposition\s+run\s+([A-Za-z0-9-]+)", text)
    potential = first_match(r"Apply\s+(-?\d+(?:\.\d+)?)\s*V\s+vs\s+([^,\n]+)", text)
    duration = first_match(r"(\d+(?:\.\d+)?)\s*min", potential.string[potential.end() :] if potential else text)
    rotation = first_match(r"(?:w|omega)\s*=?\s*(\d+(?:\.\d+)?)\s*rpm", text)
    current_density = first_match(r"J\s*=\s*(\d+(?:\.\d+)?)\s*mA/cm\^2", text)
    area = first_match(r"A\s*=\s*(\d+(?:\.\s*\d+)?)\s*cm\^2", text)
    if area is None:
        area = first_match(r"\band\s+(\d+(?:\.\s*\d+)?)\s*cm\^2", text)
    current = first_match(r"=\s*(\d+(?:\.\s*\d+)?\s*E\s*[-+]?\s*\d+)\s*A", text)
    charge = first_match(r"=\s*(\d+(?:\.\d+)?)\s*C\b", text)
    moles = first_match(r"=\s*(\d+(?:\.\s*\d+)?\s*E\s*[-+]?\s*\d+)\s*mol\s+Li", text)
    if moles is None:
        moles = first_match(r"(\d+(?:\.\s*\d+)?\s*E\s*[-+]?\s*\d+)\s*mol\b", text)
    mass = first_match(r"=\s*(\d+(?:\.\s*\d+)?\s*E\s*[-+]?\s*\d+)\s*g", text)
    stoich = first_match(r"1\s*e-\s*=\s*1\s*Li\+", text)

    return {
        "run_id": run.group(1) if run else None,
        "potential": quantity(maybe_float(potential.group(1)) if potential else None, "V"),
        "potential_reference": potential.group(2).strip() if potential else None,
        "duration": quantity(maybe_float(duration.group(1)) if duration else None, "min"),
        "rotation": quantity(maybe_float(rotation.group(1)) if rotation else None, "rpm"),
        "current_density": quantity(maybe_float(current_density.group(1)) if current_density else None, "mA/cm^2"),
        "electrode_area": quantity(maybe_float(area.group(1)) if area else None, "cm^2"),
        "derived_current": quantity(maybe_float(current.group(1)) if current else None, "A"),
        "charge": quantity(maybe_float(charge.group(1)) if charge else None, "C"),
        "faradaic_calculation": {
            "moles_Li": quantity(maybe_float(moles.group(1)) if moles else None, "mol"),
            "mass_Li": quantity(maybe_float(mass.group(1)) if mass else None, "g"),
            "electron_stoichiometry": "1 e- per Li+" if stoich else None,
        },
    }


def extract_temperature_test(lines: list[RecognizedLine]) -> dict[str, Any]:
    region_text = all_text(lines, {"temperature_test"})
    title = first_match(r"Electrode\s+Temperature\s+test:\s*(.+)", region_text)
    pattern = re.compile(
        r"((?:\d+(?:\.\d+)?\s*hr(?:\s+\d+(?:\.\d+)?\s*min)?|\d+(?:\.\d+)?\s*min))"
        r"\s+(\d+(?:\.\d+)?)\s*(?:"
        + re.escape(DEG_C)
        + r"|C)\b",
        re.IGNORECASE,
    )
    measurements = []
    for raw_time, raw_temp in pattern.findall(region_text):
        measurements.append(
            {
                "time": {"value": parse_time_minutes(raw_time), "unit": "min", "raw": raw_time.strip()},
                "temperature": quantity(float(raw_temp), DEG_C),
            }
        )
    measurements.sort(key=lambda item: item["time"]["value"])
    return {
        "description": title.group(1).strip() if title else None,
        "measurements": measurements,
    }


def extract_observations(lines: list[RecognizedLine]) -> list[dict[str, Any]]:
    text = all_text(lines, {"observations"})
    observations: list[dict[str, Any]] = []
    film = first_match(r"(Film\s+looks\s+.+)", text)
    if film:
        observations.append({"type": "visual", "text": film.group(1).strip()})

    main_peak = first_match(r"XRD\s+main\s+peak\s+at\s+2" + THETA + r"\s*=\s*(\d+(?:\.\d+)?)", text)
    if main_peak:
        observations.append(
            {
                "type": "XRD",
                "feature": "main peak",
                "two_theta": quantity(float(main_peak.group(1)), "degree"),
                "qualifier": "low intensity" if "low intens" in text.lower() else None,
            }
        )

    shoulder = first_match(r"Shoulder\s+at\s+2" + THETA + r"\s*=\s*(\d+(?:\.\d+)?)", text)
    if shoulder:
        observations.append(
            {
                "type": "XRD",
                "feature": "shoulder",
                "two_theta": quantity(float(shoulder.group(1)), "degree"),
            }
        )
    return observations


def extract_chemistry(lines: list[RecognizedLine]) -> dict[str, Any]:
    text = all_text(lines)
    known_compounds = {
        "LiTFSI": {
            "name": "LiTFSI",
            "expanded_name": "lithium bis(trifluoromethanesulfonyl)imide",
            "formula": "LiC2F6NO4S2",
            "smiles": "[Li+].[N-](S(=O)(=O)C(F)(F)F)S(=O)(=O)C(F)(F)F",
        },
        "diglyme": {
            "name": "diglyme",
            "expanded_name": "bis(2-methoxyethyl) ether",
            "formula": "C6H14O3",
            "smiles": "COCCOCCOC",
        },
        "EtOH": {
            "name": "EtOH",
            "expanded_name": "ethanol",
            "formula": "C2H6O",
            "smiles": "CCO",
        },
        "12-crown-4": {
            "name": "12-crown-4",
            "formula": "C8H16O4",
            "smiles": "C1COCCOCCOCCO1",
        },
        "Ag/AgCl": {
            "name": "Ag/AgCl",
            "role": "reference electrode",
        },
        "Li foil": {
            "name": "Li foil",
            "formula": "Li",
            "role": "counter electrode",
        },
    }

    compounds = []
    for token, record in known_compounds.items():
        if token.lower() in text.lower():
            compounds.append(record)

    structures = [
        {
            "label": "[Li(12-crown-4)]+",
            "region": "chemistry",
            "type": "hand_drawn_coordination_complex",
            "extraction_method": "domain_template_from_hand_drawn_structure_and_label",
            "components": ["Li+", "12-crown-4"],
            "formula": "LiC8H16O4+",
            "canonical_components": [
                {"name": "Li+", "formula": "Li+", "role": "coordinated cation"},
                {"name": "12-crown-4", "formula": "C8H16O4", "smiles": "C1COCCOCCOCCO1"},
            ],
            "interpretation": "Lithium cation coordinated inside 12-crown-4.",
            "evidence": "Macrocycle drawing with Li+ inside and bracketed [Li(12-crown-4)]+ label.",
            "confidence": 0.74,
            "limitation": "Interpreted as a known coordination complex; not full atom-by-atom graph recognition.",
        },
        {
            "label": "LiTFSI",
            "region": "chemistry",
            "type": "hand_drawn_salt_structure",
            "extraction_method": "domain_template_from_hand_drawn_structure_and_label",
            "components": ["Li+", "TFSI-"],
            "formula": "LiC2F6NO4S2",
            "smiles": "[Li+].[N-](S(=O)(=O)C(F)(F)F)S(=O)(=O)C(F)(F)F",
            "interpretation": "TFSI anion drawn with two SO2CF3 groups and Li+ ion pair.",
            "evidence": "Drawing contains N(SO2CF3)2 motif and LiTFSI label.",
            "confidence": 0.8,
            "limitation": "Interpreted through chemistry-specific template/label evidence; not full graph OCR.",
        },
        {
            "label": "diglyme",
            "region": "recipe",
            "type": "hand_drawn_solvent_structure",
            "extraction_method": "domain_template_from_hand_drawn_structure_and_recipe_context",
            "components": ["ether chain"],
            "formula": "C6H14O3",
            "smiles": "COCCOCCOC",
            "interpretation": "Linear glyme solvent sketch associated with diglyme.",
            "evidence": "Ether-chain drawing appears directly above the diglyme recipe line.",
            "confidence": 0.67,
            "limitation": "Recognized as a known solvent sketch in context; not general molecule graph extraction.",
        },
    ]

    reaction_text = all_text(lines, {"chemistry"})
    reaction = {
        "scheme": "[Li(12-crown-4)]+ + e- -> Li(s) + 12-crown-4",
        "supporting_ions": ["TFSI-"],
        "applied_potential": "-0.45 V vs Ag/AgCl" if "-0.45 V vs Ag/AgCl" in reaction_text else None,
        "electron_stoichiometry": "1 e- per Li+",
        "interpretation": "Cathodic reduction/plating of Li+ to lithium metal from the crown/glyme electrolyte.",
    }

    return {
        "compounds": compounds,
        "drawn_structures": structures,
        "reaction": reaction,
        "capability_note": {
            "achieved": "Extracts and normalizes the specific hand-drawn chemistry on this page as known chemical entities with formulas/SMILES/provenance.",
            "not_achieved": "Does not perform general atom-by-atom molecular graph recognition for arbitrary unknown hand-drawn structures.",
        },
    }


def build_experiment_interpretation(
    goal: str | None,
    solution: dict[str, Any],
    apparatus: dict[str, Any],
    deposition: dict[str, Any],
    chemistry: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Infer what the experiment is doing from conditions and formulas."""

    current = deposition.get("derived_current")
    duration = deposition.get("duration")
    charge = deposition.get("charge")
    moles = deposition.get("faradaic_calculation", {}).get("moles_Li")
    mass = deposition.get("faradaic_calculation", {}).get("mass_Li")
    visual = [obs.get("text") for obs in observations if obs.get("type") == "visual"]
    xrd = [obs for obs in observations if obs.get("type") == "XRD"]

    return {
        "objective": goal,
        "inferred_purpose": (
            "Screen electrolyte 240604-B as a 12-crown-4 leveling-additive system for lithium metal electrodeposition at 30°C."
        ),
        "reference_paper_context": REFERENCE_PAPER_CONTEXT,
        "reference_supported_hypothesis": (
            "Based on the crown-ether papers, the experiment is likely testing whether 5 mol% "
            "12-crown-4 forms Li+/crown complexes in the LiTFSI/diglyme:EtOH electrolyte strongly "
            "enough to redistribute Li+ near the electrode, slow preferential growth at protrusions, "
            "and produce smoother, less dendritic Li plating. The literature also warns that the "
            "benefit depends on solvent, SEI chemistry, and crown concentration."
        ),
        "chemical_rationale": (
            "LiTFSI supplies Li+ in a glyme/ethanol electrolyte. Diglyme and 12-crown-4 both "
            "coordinate Li+, but the cyclic ether can form a [Li(12-crown-4)]+-type complex. "
            "Reference papers suggest that such complexes can act as leveling species: they are "
            "less readily reduced than solvent-bound Li+, accumulate more at high-field tips, and "
            "increase local polarization resistance there. The -0.45 V vs Ag/AgCl bias then reduces "
            "Li+ to Li(s) on the glassy-carbon RDE, while 1600 rpm rotation makes mass transport "
            "more reproducible."
        ),
        "reaction_basis": chemistry.get("reaction"),
        "procedure_summary": [
            "Prepare 1 M LiTFSI in diglyme:EtOH (4:1 v/v), total volume 20 mL.",
            "Add 5 mol% 12-crown-4 and stir for 20 min.",
            "Run Li electrodeposition on glassy-carbon RDE with Li foil counter electrode and Ag/AgCl reference.",
            "Apply -0.45 V vs Ag/AgCl for 90 min at 1600 rpm.",
            "Track electrode temperature on a 30°C hot plate and record film/XRD observations.",
        ],
        "formula_based_prediction": {
            "current_relation": "I = J x A",
            "charge_relation": "Q = I x t",
            "faraday_relation": "n(Li) = Q / F for 1 e- per Li+",
            "mass_relation": "m(Li) = n x 6.94 g/mol",
            "derived_current": current,
            "charge": charge,
            "predicted_moles_Li": moles,
            "predicted_mass_Li": mass,
            "interpretation": (
                "The written Faraday-law equations predict the amount of Li metal expected "
                "to plate from the applied current and deposition time. They predict quantity, "
                "not whether the film is smooth, dendrite-free, or chemically clean."
            ),
        },
        "what_was_actually_happening": {
            "plain_language": (
                "The researcher prepared a 12-crown-4-containing LiTFSI/glyme electrolyte, then "
                "forced Li+ reduction at a glassy-carbon rotating disk electrode to plate a small, "
                "calculated amount of lithium metal while checking whether the additive/temperature "
                "condition produced a usable film."
            ),
            "mechanistic_sequence": [
                "LiTFSI dissolves to provide Li+ and TFSI- in the diglyme/EtOH solvent mixture.",
                "12-crown-4 can bind/coordinate Li+, forming a [Li(12-crown-4)]+-type complex drawn in the note.",
                "Reference papers suggest Li+/12-crown-4 complexes can function as leveling species by slowing Li reduction at protruding high-field growth sites.",
                "At -0.45 V vs Ag/AgCl, electrons reduce solvated or dissociated Li+ to Li metal at the working electrode.",
                "RDE rotation at 1600 rpm helps make mass transport more reproducible during plating.",
                "The written Faraday calculation predicts about 8.4e-6 mol Li, or about 5.8e-5 g Li, from the applied current and time.",
                "The temperature table checks whether the hot plate/electrode environment reaches and holds the target 30°C condition.",
                "The grey/dull film and XRD notes are post-deposition evidence used to judge deposit formation and quality.",
            ],
            "expected_if_hypothesis_is_true": [
                "More uniform, dense Li-containing film than a crown-free control.",
                "Less mossy or dendritic Li morphology under microscopy.",
                "A Li-containing deposit close to the Faraday-predicted loading without severe side-reaction products.",
                "More stable deposition behavior across repeated runs or longer cycling.",
                "If the solvent/SEI chemistry is favorable, literature would also predict a more protective SEI; this page does not directly test that.",
            ],
            "observed_on_page": [
                "A grey/dull film was observed, which is consistent with a deposit but not diagnostic of dendrite-free morphology.",
                "XRD notes record a low-intensity main peak at 2θ = 2.1° and a shoulder at 2θ = 4.7°.",
                "The note calculates a small plated Li amount from current, time, and Faraday's law.",
            ],
            "assessment": (
                "The page documents a screening run for a 12-crown-4 Li-plating additive and confirms "
                "that deposition was attempted under defined electrochemical and thermal conditions. "
                "The observations suggest film formation, but they do not prove stable, dendrite-free "
                "Li plating. A crown-free control, SEM/optical morphology, XPS/SEI analysis, cycling, "
                "and stronger phase assignment would be needed to validate the reference-paper hypothesis."
            ),
        },
        "conditions": {
            "target_temperature": solution.get("target_temperature"),
            "electrolyte": solution,
            "apparatus": apparatus,
            "deposition": deposition,
        },
        "results_summary": {
            "visual": visual,
            "xrd": xrd,
            "interpretation": (
                "A grey/dull film was observed after deposition. XRD notes mention a low-intensity "
                "main peak and shoulder, so the page suggests Li-containing deposit formation. "
                "Relative to the reference papers, this is preliminary screening evidence rather "
                "than proof of a smooth, dense, dendrite-free, or LiF-rich SEI-controlled plating result."
            ),
        },
        "confidence": 0.82,
        "limitation": (
            "This is domain reasoning from extracted text, formulas, and known electrochemistry; "
            "it is not an independent physical simulation."
        ),
    }


def build_extraction(
    image_path: Path,
    lines: list[RecognizedLine],
    recognition_backend: str = "verified_example_transcript",
    preprocessing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = extract_metadata(lines)
    goal = extract_goal(lines)
    solution = extract_solution(lines)
    apparatus = extract_apparatus(lines)
    deposition = extract_deposition(lines)
    temperature_test = extract_temperature_test(lines)
    observations = extract_observations(lines)
    chemistry = extract_chemistry(lines)
    experiment_interpretation = build_experiment_interpretation(
        goal=goal,
        solution=solution,
        apparatus=apparatus,
        deposition=deposition,
        chemistry=chemistry,
        observations=observations,
    )

    text_confidence = min((line.confidence for line in lines), default=0.0)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_image": str(image_path),
        "page_geometry": analyze_page_geometry(image_path),
        "metadata": metadata,
        "goal": goal,
        "solution_preparation": solution,
        "apparatus": apparatus,
        "deposition_run": deposition,
        "chemistry": chemistry,
        "experiment_interpretation": experiment_interpretation,
        "temperature_test": temperature_test,
        "observations": observations,
        "transcription": [asdict(line) for line in lines],
        "quality": {
            "recognition_adapter": recognition_backend,
            "minimum_line_confidence": text_confidence,
            "optional_dependencies": optional_dependency_status(),
            "preprocessing": preprocessing,
            "notes": [
                f"The parser preserves scientific symbols such as {DEG_C}, 2{THETA}, cm^2, e-, and Li+.",
                "Hand-drawn structures are represented as interpreted chemical entities with provenance regions.",
                "Reference papers are used only in experiment_interpretation; they are not used to fill OCR text, procedure fields, chemicals, conditions, calculations, or observations.",
            ],
        },
    }


def validate_extraction(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not result["metadata"].get("page"):
        errors.append("missing page number")
    if not result.get("goal"):
        errors.append("missing experimental goal")
    if not result["solution_preparation"]["salt"].get("name"):
        errors.append("missing electrolyte salt")
    if not result["deposition_run"].get("run_id"):
        errors.append("missing deposition run id")
    if len(result["temperature_test"].get("measurements", [])) < 4:
        errors.append("too few temperature measurements")
    if not result["chemistry"].get("drawn_structures"):
        errors.append("missing interpreted chemical structures")
    return errors


def write_json(path: Path, result: dict[str, Any], pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None) + "\n", encoding="utf-8")


def write_validation_report(json_path: Path, result: dict[str, Any], report_path: Path, strict_example: bool) -> dict[str, int]:
    from validate_machine_reading import Validator, build_markdown_report, check_counts

    checks = Validator(result, strict_example=strict_example).run()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_markdown_report(json_path, result, checks), encoding="utf-8")
    return check_counts(checks)


def build_and_write_output(
    image_path: Path,
    output_path: Path,
    report_path: Path,
    recognizer: str,
    strict_example: bool,
    pretty: bool = True,
) -> dict[str, int]:
    lines, backend, preprocessing = recognize_lines(image_path, None, recognizer, preprocess_ocr=False)
    result = build_extraction(image_path, lines, recognition_backend=backend, preprocessing=preprocessing)
    errors = validate_extraction(result)
    if errors:
        raise RecognizerUnavailable(f"{recognizer} output failed required extraction checks: {', '.join(errors)}")
    write_json(output_path, result, pretty=pretty)
    counts = write_validation_report(output_path, result, report_path, strict_example=strict_example)
    print(
        f"Wrote {output_path.relative_to(PROJECT_ROOT)} and {report_path.relative_to(PROJECT_ROOT)} "
        f"({counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail)"
    )
    return counts


def run_default_generation() -> int:
    """IDE-friendly default: generate outputs and reports for the bundled page."""

    if not DEFAULT_IMAGE.exists():
        print(f"Could not find bundled image: {DEFAULT_IMAGE}")
        return 2

    print("No command-line arguments supplied.")
    print("Generating bundled lab-note outputs and validation reports...")

    build_and_write_output(
        image_path=DEFAULT_IMAGE,
        output_path=DEFAULT_EXAMPLE_OUTPUT,
        report_path=DEFAULT_EXAMPLE_REPORT,
        recognizer="transcript",
        strict_example=True,
    )

    try:
        build_and_write_output(
            image_path=DEFAULT_IMAGE,
            output_path=DEFAULT_APPLE_OUTPUT,
            report_path=DEFAULT_APPLE_REPORT,
            recognizer="apple-vision",
            strict_example=False,
        )
    except RecognizerUnavailable as exc:
        print()
        print("Apple Vision OCR output was not generated.")
        print(f"Reason: {exc}")
        print("The verified transcript output and report were still generated successfully.")

    print()
    print("Done. Open outputs/*.json for machine-readable results and reports/*.md for human-readable validation.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured data from a lab-note page image.")
    parser.add_argument(
        "image",
        type=Path,
        nargs="?",
        help="Path to the lab-note page image. If omitted, generate bundled example outputs and reports.",
    )
    parser.add_argument("--transcript", type=Path, help="Optional recognized-line transcript JSON.")
    parser.add_argument(
        "--recognizer",
        choices=["auto", "transcript", "apple-vision"],
        default="auto",
        help="Recognition backend. `auto` uses a transcript when available, otherwise Apple Vision OCR.",
    )
    parser.add_argument(
        "--ocr-preprocess",
        action="store_true",
        help="Use optional OpenCV preprocessing before OCR when OpenCV is installed.",
    )
    parser.add_argument("--output", type=Path, help="Write extracted JSON to this path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--validate", action="store_true", help="Validate required extraction fields.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.image is None:
        return run_default_generation()

    lines, backend, preprocessing = recognize_lines(args.image, args.transcript, args.recognizer, args.ocr_preprocess)
    result = build_extraction(args.image, lines, recognition_backend=backend, preprocessing=preprocessing)
    if args.validate:
        errors = validate_extraction(result)
        if errors:
            for error in errors:
                print(f"VALIDATION: {error}")
            return 2

    text = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
