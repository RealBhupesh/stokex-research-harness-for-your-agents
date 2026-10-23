import contextlib
import io
import json
import pathlib
import re
import tempfile
import unittest

from stockex.cli import main
from stockex.deals.analysis import analyze
from stockex.deals.case import load_case
from stockex.deals.memo import recommendation, to_html, to_markdown
from stockex.store.database import PointInTimeStore
from stockex.store.importer import import_jsonl

from deal_fixtures import demo_raw, modified, textbook_raw


def _differences(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [f"{path}: keys {sorted(set(a) ^ set(b))}"]
        return [d for key in a for d in _differences(a[key], b[key], f"{path}.{key}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 1e-9 * max(1.0, abs(b)):
            return []
        if path.endswith("max_relative_error"):
            return []
    elif a == b:
        return []
    return [f"{path}: {a!r} != {b!r}"]


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


class MemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_case(modified(demo_raw(), monte_carlo__paths=40))
        cls.results = analyze(cls.case)

    def test_memo_numbers_come_from_the_results(self):
        text = to_markdown(self.case, self.results)
        lbo = self.results["lbo"]
        for snippet in (f"₹{lbo['sources_uses']['offer_price']:,.2f}", f"{lbo['returns']['irr'] * 100:.1f}% IRR",
                        f"{lbo['returns']['moic']:.2f}x MOIC", f"₹{self.results['breakevens']['max_bid']:,.2f}",
                        f"{lbo['sources_uses']['entry_multiple']:.1f}x LTM EBITDA"):
            self.assertIn(snippet, text)
        self.assertIn("Illustrative case", text)
        self.assertNotIn("nan", text.lower().replace("financ", "").replace("covenant", ""))

    def test_html_is_self_contained_with_charts(self):
        html = to_html(self.case, self.results)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertEqual(html.count("<svg"), 3)
        self.assertNotRegex(html, r"<script|https?://")

    def test_recommendation_rules(self):
        rec = recommendation(self.case, self.results)
        self.assertEqual(rec["decision"], "APPROVE WITH CONDITIONS")
        self.assertTrue(any("DSCR" in c for c in rec["conditions"]))
        overpay = load_case(modified(demo_raw(), transaction__offer_premium=0.45, monte_carlo__paths=20))
        rec = recommendation(overpay, analyze(overpay))
        self.assertIn(rec["decision"], {"RETURN FOR WORK", "DECLINE"})
        self.assertTrue(any("maximum bid" in f for f in rec["failures"]))


class CommittedExampleTests(unittest.TestCase):
    def test_committed_example_outputs_are_current(self):
        from stockex.deals import build_deal
        from deal_fixtures import DEMO
        with tempfile.TemporaryDirectory() as directory:
            build_deal(DEMO, directory)
            fresh = pathlib.Path(directory)
            committed = DEMO.parent / "project-saffron"
            # Python 3.12 changed float sum() rounding, so numbers are compared with a tolerance.
            differences = _differences(json.loads((fresh / "results.json").read_text(encoding="utf-8")),
                                       json.loads((committed / "results.json").read_text(encoding="utf-8")))
            self.assertEqual(differences[:5], [], "re-run: python -m stockex.cli deal-model "
                             "examples/deals/project-saffron.json --out examples/deals/project-saffron")
            self.assertEqual((fresh / "ic-memo.md").read_text(encoding="utf-8"),
                             (committed / "ic-memo.md").read_text(encoding="utf-8"))


class DealCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.case_path = self.root / "case.json"
        self.case_path.write_text(json.dumps(modified(demo_raw(), monte_carlo__paths=30)), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_deal_model_writes_all_outputs(self):
        code, out, err = run_cli("deal-model", self.case_path, "--out", self.root / "out")
        self.assertEqual((code, err), (0, ""))
        summary = json.loads(out)
        self.assertEqual(summary["recommendation"], "APPROVE WITH CONDITIONS")
        self.assertTrue(summary["model_checks_ok"])
        self.assertTrue(summary["workbook_verification"]["ok"])
        for name in ("model.xlsx", "ic-memo.md", "ic-memo.html", "results.json"):
            self.assertTrue((self.root / "out" / name).stat().st_size > 1000, name)
        results = json.loads((self.root / "out" / "results.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(results["lbo"]["returns"]["irr"], summary["irr"])

    def test_invalid_case_is_a_structured_error(self):
        bad = modified(demo_raw(), balance_sheet__cash=1.0)
        self.case_path.write_text(json.dumps(bad), encoding="utf-8")
        code, out, err = run_cli("deal-model", self.case_path, "--out", self.root / "out")
        self.assertEqual((code, out), (2, ""))
        payload = json.loads(err)
        self.assertEqual((payload["code"], payload["path"]), ("BALANCE_SHEET_UNBALANCED", "$.balance_sheet"))

    def _store(self, raw, *, skip=()):
        records = [
            {"schema_version": 1, "record_type": "issuer", "record": {"issuer_id": "issuer_tb", "legal_name": "Textbook"}},
            {"schema_version": 1, "record_type": "security",
             "record": {"security_id": "SEC_TB", "issuer_id": "issuer_tb", "exchange": "NSE"}},
            {"schema_version": 1, "record_type": "source",
             "record": {"source_id": "annual_report", "publisher": "Company", "available_at": "2026-05-20T00:00:00Z"}},
        ]
        values = {}
        for line in ("revenue", "cogs", "opex", "da", "finance_cost", "other_income", "tax"):
            for year, value in zip(raw["historicals"]["years"], raw["historicals"][line]):
                values[f"financial.{line}.{year}"] = value
        for item, value in raw["balance_sheet"].items():
            values[f"balance_sheet.{item}.{raw['historicals']['years'][-1]}"] = value
        for k, (field, value) in enumerate(sorted(values.items())):
            if field in skip:
                continue
            records.append({"schema_version": 1, "record_type": "observation", "record": {
                "observation_id": f"obs_{k}", "security_id": "SEC_TB", "field": field, "value_type": "NUMBER",
                "value_number": value * 1.5, "unit": "INR_CRORE", "source_id": "annual_report",
                "available_at": "2026-05-20T00:00:00Z", "valid_from": "2026-05-20T00:00:00Z",
                "revision_number": 0, "quality_status": "VERIFIED"}})
        source = self.root / "records.jsonl"
        source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        database = self.root / "store.sqlite3"
        with PointInTimeStore.open(database) as store:
            import_jsonl(store, source)
        return database

    def test_historicals_can_come_from_the_point_in_time_store(self):
        raw = textbook_raw()
        self.case_path.write_text(json.dumps(raw), encoding="utf-8")
        database = self._store(raw)
        code, out, err = run_cli("deal-model", self.case_path, "--out", self.root / "out", "--from-store", database,
                                 "--security", "SEC_TB", "--cutoff", "2026-06-01T00:00:00Z")
        self.assertEqual((code, err), (0, ""))
        summary = json.loads(out)
        self.assertEqual(summary["historicals_from_store"]["fields"], 2 * 7 + 12)
        results = json.loads((self.root / "out" / "results.json").read_text(encoding="utf-8"))
        # The store holds 1.5x every figure, so LTM EBITDA is 30 rather than the case file's 20.
        self.assertAlmostEqual(results["lbo"]["sources_uses"]["ltm_ebitda"], 30.0)

    def test_store_cutoff_is_enforced(self):
        raw = textbook_raw()
        self.case_path.write_text(json.dumps(raw), encoding="utf-8")
        database = self._store(raw)
        code, _, err = run_cli("deal-model", self.case_path, "--out", self.root / "out", "--from-store", database,
                               "--security", "SEC_TB", "--cutoff", "2026-05-01T00:00:00Z")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["code"], "STORE_HISTORICALS_MISSING")
        database.unlink()
        database = self._store(raw, skip={"financial.tax.FY25"})
        code, _, err = run_cli("deal-model", self.case_path, "--out", self.root / "out", "--from-store", database,
                               "--security", "SEC_TB", "--cutoff", "2026-06-01T00:00:00Z")
        self.assertEqual(code, 2)
        self.assertTrue(re.search(r"financial\.tax\.FY25", json.loads(err)["message"]))


if __name__ == "__main__":
    unittest.main()
