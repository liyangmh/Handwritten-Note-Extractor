import unittest
from pathlib import Path

from labnote_extractor import (
    build_extraction,
    correct_ocr_text,
    load_transcript,
    validate_extraction,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "Example Lab Notebook Page.jpg"
TRANSCRIPT = ROOT / "examples" / "example_transcription.json"


class LabnoteExtractorTest(unittest.TestCase):
    def setUp(self):
        self.lines = load_transcript(TRANSCRIPT)
        self.result = build_extraction(IMAGE, self.lines)

    def test_required_fields_validate(self):
        self.assertEqual(validate_extraction(self.result), [])

    def test_preserves_symbols_and_units(self):
        self.assertEqual(self.result["solution_preparation"]["target_temperature"]["unit"], "°C")
        self.assertEqual(self.result["deposition_run"]["current_density"]["unit"], "mA/cm^2")
        self.assertEqual(self.result["deposition_run"]["faradaic_calculation"]["electron_stoichiometry"], "1 e- per Li+")

    def test_extracts_chemistry_and_experiment(self):
        compounds = {compound["name"] for compound in self.result["chemistry"]["compounds"]}
        self.assertIn("LiTFSI", compounds)
        self.assertIn("12-crown-4", compounds)
        structures = self.result["chemistry"]["drawn_structures"]
        self.assertTrue(all("limitation" in structure for structure in structures))
        self.assertIn("formula_based_prediction", self.result["experiment_interpretation"])
        self.assertIn("Faraday", self.result["experiment_interpretation"]["formula_based_prediction"]["interpretation"])
        self.assertIn("reference_paper_context", self.result["experiment_interpretation"])
        self.assertIn("crown", self.result["experiment_interpretation"]["reference_supported_hypothesis"])
        self.assertIn("what_was_actually_happening", self.result["experiment_interpretation"])
        self.assertEqual(self.result["solution_preparation"]["mixing"]["stir_time"]["value"], 20.0)
        self.assertEqual(self.result["deposition_run"]["run_id"], "240604-B1")
        self.assertAlmostEqual(self.result["deposition_run"]["charge"]["value"], 0.81)
        self.assertAlmostEqual(
            self.result["deposition_run"]["faradaic_calculation"]["mass_Li"]["value"],
            5.8e-5,
        )

    def test_temperature_table(self):
        measurements = self.result["temperature_test"]["measurements"]
        self.assertEqual(len(measurements), 8)
        self.assertEqual(measurements[-1]["time"]["value"], 90)
        self.assertEqual(measurements[-1]["temperature"]["value"], 32.6)

    def test_ocr_cleanup_preserves_science_tokens(self):
        self.assertEqual(correct_ocr_text("LiT ESI in diglypo : EtOH"), "LiTFSI in diglyme : EtOH")
        self.assertEqual(correct_ocr_text("-0.Y5V vS Ag/AgC1"), "-0.45 V vs Ag/AgCl")
        self.assertEqual(correct_ocr_text("Shoulder at 20:4.7°"), "Shoulder at 2θ = 4.7°")
        self.assertEqual(correct_ocr_text("min 23.l°C"), "1 min 23.1°C")


if __name__ == "__main__":
    unittest.main()
