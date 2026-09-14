import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_intelligence import compound_return, driver_materiality, price_move_attribution


class PriceMoveAttributionTests(unittest.TestCase):
    def test_decomposes_relative_move_without_claiming_causality(self):
        result = price_move_attribution(
            asset_returns=[0.10, -0.02],
            benchmark_returns=[0.02, 0.01],
            sector_returns=[0.04, 0.00],
            peer_return_series=[[0.03, 0.01], [0.05, -0.01]],
        )

        self.assertAlmostEqual(result["asset_total_return"], 0.078)
        self.assertAlmostEqual(result["benchmark_total_return"], 0.0302)
        self.assertAlmostEqual(result["sector_total_return"], 0.04)
        self.assertAlmostEqual(result["peer_median_total_return"], 0.0399)
        self.assertAlmostEqual(result["residual_vs_sector"], 0.038)
        self.assertEqual(result["attribution_status"], "UNEXPLAINED")
        self.assertIn("does not establish causality", result["warning"])

    def test_rejects_mismatched_or_invalid_return_series(self):
        invalid = [
            ([0.01], [0.01, 0.02], [0.01], [[0.01]]),
            ([], [], [], []),
            ([-1.0], [0.0], [0.0], [[0.0]]),
            ([0.01], [0.0], [0.0], [[0.01, 0.02]]),
        ]
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(ValueError):
                price_move_attribution(*case)

    def test_compounds_periodic_returns(self):
        self.assertAlmostEqual(compound_return([0.10, -0.10]), -0.01)


class DriverMaterialityTests(unittest.TestCase):
    def test_accepts_evidenced_transmission_path(self):
        result = driver_materiality({
            "name": "Indian crude basket",
            "exposure": "input cost",
            "magnitude": "material",
            "transmission_path": "crude price -> feedstock cost -> EBITDA margin",
            "source_ids": ["S1", "S2"],
        })
        self.assertTrue(result["material"])
        self.assertEqual(result["classification"], "MATERIAL")

    def test_marks_unsupported_world_event_not_material(self):
        result = driver_materiality({
            "name": "unrelated election",
            "exposure": "",
            "magnitude": "unknown",
            "transmission_path": "",
            "source_ids": [],
        })
        self.assertFalse(result["material"])
        self.assertEqual(result["classification"], "NOT MATERIAL")
        self.assertIn("transmission_path", result["missing"])


if __name__ == "__main__":
    unittest.main()
