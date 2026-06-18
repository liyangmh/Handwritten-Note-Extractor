# Handwritten Lab-Note Extraction

This project extracts structured, machine-readable data from a messy handwritten chemistry lab notebook page.

The task is evaluated on four abilities:

1. **Text** - read handwritten notes, procedures, labels, and tables.
2. **Special symbols** - preserve scientific notation such as `30°C`, `2θ`, `Li+`, `e-`, `cm^2`, and `mA/cm^2`.
3. **Chemistry** - extract chemicals, concentrations, reagents, formulas, and page-specific hand-drawn structure interpretations.
4. **Experiment** - explain the goal, conditions, procedure, calculations, observations, and result meaning.

The core design is intentionally layered:

- **Recognition layer**: reads image text into line-level OCR/transcript data.
- **Parser layer**: turns recognized lines into deterministic structured JSON.
- **Validation layer**: checks schema completeness, symbols, chemistry, and electrochemical calculations.
- **Interpretation layer**: summarizes the experiment from extracted facts.

In short: first read the page, then structure it, then validate it, then explain what the experiment means.

Reference papers are used only after note extraction, inside the `experiment_interpretation` context layer. They are not used to fill missing OCR text, chemicals, procedure fields, conditions, calculations, or observations.

## Basic Data Layout

Important files and folders:

| Path | Purpose |
| --- | --- |
| `Example Lab Notebook Page.jpg` | Input handwritten lab notebook image. |
| `labnote_extractor.py` | Main extraction script. Produces structured JSON. |
| `validate_machine_reading.py` | Validates JSON and can write a readable Markdown report. |
| `recognizers/apple_vision_ocr.swift` | Local macOS Apple Vision OCR adapter. |
| `examples/example_transcription.json` | Verified line-by-line transcript for the sample page. This is a clean baseline for parser validation, not automatic OCR. |
| `outputs/example_labnote_page.json` | JSON generated from the verified transcript baseline. |
| `outputs/apple_vision_labnote_page.json` | JSON generated from the Apple Vision OCR path. This demonstrates automatic image-to-JSON extraction. |
| `reports/example_validation_report.md` | Human-readable validation report for the verified transcript output. |
| `reports/apple_vision_validation_report.md` | Human-readable validation report for the Apple Vision output. |
| `reference-paper/` | Related papers used only for experiment context/summary. |
| `tests/test_labnote_extractor.py` | Regression tests. |

## Required Packages

Python requirement:

- Python 3.10 or newer

Required Python packages:

- `numpy`
- `Pillow`

Optional but recommended Python packages:

- `rapidfuzz` - improves correction of OCR mistakes such as chemistry names.
- `opencv-python-headless` - enables optional image preprocessing before OCR.

macOS-only OCR dependency:

- Apple Vision through `/usr/bin/swift`, used by `recognizers/apple_vision_ocr.swift`.

Install packages into the Python environment selected by your IDE:

```bash
python3 -m pip install -r requirements.txt
```

## How To Run

The easiest way is to click **Run** on `labnote_extractor.py` in your IDE. If no arguments are passed, the script automatically processes `Example Lab Notebook Page.jpg`, generates both JSON outputs, and writes both validation reports:

- `outputs/example_labnote_page.json`
- `outputs/apple_vision_labnote_page.json`
- `reports/example_validation_report.md`
- `reports/apple_vision_validation_report.md`

Equivalent terminal command:

```bash
python3 labnote_extractor.py
```

After the run finishes, open `outputs/` for machine-readable JSON and `reports/` for human-readable validation reports.

The no-argument run generates two outputs:

| Output | What it demonstrates |
| --- | --- |
| `outputs/example_labnote_page.json` | Reference-quality parser output from the verified transcript baseline. |
| `outputs/apple_vision_labnote_page.json` | Automatic OCR-backed output from the Apple Vision recognition path. |

## Run Tests

```bash
python3 -m unittest tests/test_labnote_extractor.py
```

## Validation Status

The one-click/no-argument run already writes validation reports.

| Output | Meaning | Validation |
| --- | --- | --- |
| `outputs/example_labnote_page.json` | Reference-quality output from verified transcript. Best for parser correctness. | `PASS: 103`, `WARN: 0`, `FAIL: 0` |
| `outputs/apple_vision_labnote_page.json` | Automatic OCR-backed output. Best for demoing image-to-JSON extraction. | `PASS: 85`, `WARN: 1`, `FAIL: 0` |

The Apple Vision warning is low OCR confidence on some handwritten lines. The structured output still validates, but the report correctly flags that it should be manually reviewed.

## How To Read The JSON Output

Open either file in `outputs/`.

Top-level sections:

| JSON key | Meaning |
| --- | --- |
| `schema_version` | Version of this output schema. |
| `source_image` | Image used for extraction. |
| `page_geometry` | Basic image/page geometry. |
| `metadata` | Page number, date, project, continuation page. |
| `goal` | Extracted experiment goal. |
| `solution_preparation` | Salt, solvent ratio, additive, total volume, stir time, target temperature. |
| `apparatus` | Working/counter/reference electrodes and glovebox condition. |
| `deposition_run` | Run ID, potential, duration, rotation, current density, area, charge, and Faraday calculation. |
| `chemistry` | Compounds, formulas/SMILES where available, drawn-structure interpretations, and reaction scheme. |
| `experiment_interpretation` | Goal/condition/procedure/result reasoning, plus clearly separated reference-paper context. |
| `temperature_test` | Extracted temperature table. |
| `observations` | Film and XRD observations from the page. |
| `transcription` | Line-level recognized text with regions and confidence. |
| `quality` | Recognition backend, confidence, optional dependencies, preprocessing, and limitations. |

For human review, open the Markdown reports in `reports/`. They summarize the same JSON in a readable format and include the validation checklist.

## What The Algorithm Does Well

- Produces structured JSON rather than a free-form summary.
- Separates raw extraction from later scientific interpretation.
- Preserves important scientific symbols and units such as `°C`, `2θ`, `Li+`, `e-`, and `cm^2`.
- Extracts the main procedure fields: electrolyte, additive, stir time, apparatus, potential, duration, rotation, current density, and temperature table.
- Checks electrochemical math: `I = J x A`, `Q = I x t`, `n(Li) = Q/F`, and lithium mass.
- Captures page-specific chemistry, including `LiTFSI`, `diglyme`, `EtOH`, `12-crown-4`, `[Li(12-crown-4)]+`, and the Li plating reaction.
- Generates human-readable validation reports for manual review.
- Supports a swappable recognition layer: Apple Vision, verified transcript, or another future handwriting/VLM recognizer.

## Current Limitations

- The project does not include a custom trained handwriting OCR model.
- Apple Vision provides automatic OCR but has lower confidence on some messy handwritten lines.
- The verified transcript is a clean baseline for this sample page; it should not be described as automatic OCR.
- Hand-drawn structures are interpreted using chemistry-aware templates and page context. This is not general atom-by-atom molecular graph recognition for arbitrary unknown structures.
- Reference papers improve experiment interpretation only. They do not improve raw OCR and are not used to fill missing note data.
- The experiment interpretation is evidence-aware: the page suggests Li deposition, but it does not prove dendrite-free or SEI-controlled plating without controls, microscopy, XPS, cycling data, or stronger phase analysis.
