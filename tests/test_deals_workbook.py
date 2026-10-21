import pathlib
import shutil
import subprocess
import tempfile
import unittest
import xml.dom.minidom
import zipfile

from stockex.deals import verify_workbook
from stockex.deals.analysis import analyze
from stockex.deals.case import load_case
from stockex.deals.formula_eval import Book, Evaluator, FormulaError, parse
from stockex.deals.lbo import run_lbo
from stockex.deals.workbook import build_workbook
from stockex.deals.xlsx import Workbook, column_index, column_letter, split_address

from deal_fixtures import demo_raw, modified, textbook_raw

SHEETS = ["Cover", "Inputs", "IS", "BS", "CF", "Debt", "Deal", "Returns", "WACC", "DCF", "Comps", "Sensitivity",
          "Football", "Checks"]


def _evaluate(cells: dict, names: dict | None = None, sheet: str = "S"):
    return Evaluator(Book({sheet: cells}, names or {}))


class FormulaEvaluatorTests(unittest.TestCase):
    def test_precedence_follows_excel(self):
        cells = {(1, 1): (None, "-2^2"), (1, 2): (None, "2+3*4"), (1, 3): (None, "(2+3)*4"),
                 (1, 4): (None, "2^3^2"), (1, 5): (None, '"a"&1+1'), (1, 6): (None, "1+2>2")}
        ev = _evaluate(cells)
        self.assertEqual([ev.value("S", 1, c) for c in range(1, 7)], [4.0, 14.0, 20.0, 64.0, "a2", True])

    def test_references_ranges_names_and_functions(self):
        cells = {(1, 1): (1.0, None), (2, 1): (2.0, None), (3, 1): (3.0, None), (4, 1): (4.0, None),
                 (1, 2): (None, "SUM(A1:A4)"), (2, 2): (None, "QUARTILE(A1:A4,1)"), (3, 2): (None, "Rate*10"),
                 (4, 2): (None, "INDEX(A1:A4,3)"), (5, 2): (None, "CHOOSE(2,A1,A2,A3)"),
                 (6, 2): (None, 'IF(A1>0,"yes","no")'), (7, 2): (None, "MEDIAN(A1:A4)"),
                 (8, 2): (None, "MIN(A1:A4,0.5)"), (9, 2): (None, "ROUND(2.345,2)"),
                 (10, 2): (None, "IFERROR(1/0,7)"), (11, 2): (None, "AND(A1=1,OR(A2=5,TRUE))")}
        ev = _evaluate(cells, {"Rate": "S!$A$2"})
        self.assertEqual([ev.value("S", r, 2) for r in range(1, 12)],
                         [10.0, 1.75, 20.0, 3.0, 2.0, "yes", 2.5, 0.5, 2.35, 7.0, True])

    def test_cross_sheet_references_and_irr(self):
        book = Book({"A": {(1, 1): (-100.0, None), (1, 2): (0.0, None), (1, 3): (144.0, None)},
                     "B": {(1, 1): (None, "IRR(A!A1:C1)"), (2, 1): (None, "'A'!C1/2")}}, {})
        ev = Evaluator(book)
        self.assertAlmostEqual(ev.value("B", 1, 1), 0.2, places=9)
        self.assertEqual(ev.value("B", 2, 1), 72.0)

    def test_errors_are_reported_not_hidden(self):
        with self.assertRaises(FormulaError):
            _evaluate({(1, 1): (None, "B1"), (1, 2): (None, "A1+1")}).value("S", 1, 1)
        with self.assertRaises(FormulaError):
            _evaluate({(1, 1): (None, "1/0")}).value("S", 1, 1)
        with self.assertRaises(FormulaError):
            _evaluate({(1, 1): (None, "NOPE(1)")}).value("S", 1, 1)
        with self.assertRaises(FormulaError):
            parse("1+")

    def test_addresses_round_trip(self):
        for index in (1, 26, 27, 52, 703):
            self.assertEqual(column_index(column_letter(index)), index)
        self.assertEqual(split_address("$AB$12"), (12, 28))


class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls.directory.name)
        cls.case = load_case(modified(demo_raw(), monte_carlo__paths=40))
        cls.results = analyze(cls.case)
        cls.workbook, cls.expect = build_workbook(cls.case, cls.results)
        cls.path = cls.root / "model.xlsx"
        cls.workbook.save(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_file_is_a_valid_package_with_the_expected_sheets(self):
        with zipfile.ZipFile(self.path) as archive:
            for name in archive.namelist():
                xml.dom.minidom.parseString(archive.read(name))
            self.assertIn("xl/styles.xml", archive.namelist())
        self.assertEqual([s.name for s in self.workbook.sheets], SHEETS)

    def test_every_formula_recomputes_to_the_engine_from_the_saved_file(self):
        report = verify_workbook(self.path, self.expect)
        self.assertTrue(report["ok"], report["failures"])
        self.assertGreater(report["formulas"], 800)
        self.assertGreater(report["engine_checked_cells"], 600)

    def test_model_checks_pass_and_feed_the_cover(self):
        book = Book.from_xlsx(self.path)
        ev = Evaluator(book)
        for sheet in ("Checks", "Cover"):
            values = [ev.value(sheet, r, c) for (r, c), (_, f) in book.sheets[sheet].items() if f]
            self.assertIn("ALL CHECKS PASS", values)

    def test_inputs_are_values_and_calculations_are_formulas(self):
        inputs = self.workbook.sheet("Inputs")
        formulas = sum(1 for cell in inputs.cells.values() if cell.formula)
        self.assertGreater(formulas, 40)  # live driver rows and the exit multiple selector
        for sheet in ("IS", "BS", "CF", "Debt", "Returns"):
            projection = [cell for (r, c), cell in self.workbook.sheet(sheet).cells.items()
                          if c >= 7 and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)]
            hardcoded = [cell for cell in projection if cell.formula is None]
            # Only the "years held" counters on Returns are typed in.
            self.assertLessEqual(len(hardcoded), 5 if sheet == "Returns" else 0, sheet)

    def _live(self, **inputs):
        book = Book.from_xlsx(self.path)
        for name, value in inputs.items():
            sheet, ref = book.names[name].split("!")
            row, col = split_address(ref)
            book.sheets[sheet][(row, col)] = (value, None)
        ev = Evaluator(book)
        returns = self.workbook.sheet("Returns")
        irr_cell = next((r, c) for (r, c), cell in returns.cells.items()
                        if cell.formula and cell.formula.startswith("IF(") and "IRR(" in cell.formula)
        moic_label = next(r for (r, c), cell in returns.cells.items() if cell.value == "Sponsor MOIC")
        return ev.value("Returns", *irr_cell), ev.value("Returns", moic_label, 4)

    def test_case_selector_switches_the_whole_model(self):
        for selector, scenario in ((2, "upside"), (3, "downside")):
            with self.subTest(scenario=scenario):
                irr, moic = self._live(Case=selector)
                engine = run_lbo(self.case, scenario)["returns"]
                self.assertAlmostEqual(irr, engine["irr"], places=8)
                self.assertAlmostEqual(moic, engine["moic"], places=8)

    def test_sensitivity_inputs_flow_through_live(self):
        irr, moic = self._live(Growth_Shift=0.02, EBITDA_Haircut=0.1, Offer_Premium=0.3, Leverage_Scale=0.8)
        case = self.case
        price = case.market["unaffected_price"] * 1.3
        engine = run_lbo(case, growth_shift=0.02, ebitda_haircut=0.1, price=price, leverage_scale=0.8)["returns"]
        self.assertAlmostEqual(irr, engine["irr"], places=8)
        self.assertAlmostEqual(moic, engine["moic"], places=8)

    def test_textbook_case_workbook_matches_hand_answers(self):
        case = load_case(textbook_raw(sweep=True))
        workbook, expect = build_workbook(case, analyze(case))
        path = self.root / "textbook.xlsx"
        workbook.save(path)
        report = verify_workbook(path, expect)
        self.assertTrue(report["ok"], report["failures"])

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice not installed")
    def test_libreoffice_recalculation_matches_the_engine(self):
        stripped = Workbook()
        stripped.sheets, stripped.styles, stripped.names = self.workbook.sheets, self.workbook.styles, self.workbook.names
        cached = {}
        for sheet in stripped.sheets:
            for key, cell in sheet.cells.items():
                if cell.formula is not None:
                    cached[(sheet.name, key)] = cell.value
                    cell.value = None   # no cached values: LibreOffice has to calculate everything itself
        source = self.root / "nocache.xlsx"
        try:
            stripped.save(source)
        finally:
            for sheet in stripped.sheets:
                for key, cell in sheet.cells.items():
                    if (sheet.name, key) in cached:
                        cell.value = cached[(sheet.name, key)]
        out = self.root / "lo"
        profile = (self.root / "profile").as_uri()
        result = subprocess.run(["soffice", f"-env:UserInstallation={profile}", "--headless", "--calc",
                                 "--convert-to", "xlsx", "--outdir", str(out), str(source)],
                                capture_output=True, text=True, timeout=240)
        converted = out / "nocache.xlsx"
        if not converted.exists():
            self.skipTest(f"LibreOffice could not convert spreadsheets here: {result.stderr.strip()[-200:]}")
        book = Book.from_xlsx(converted)
        failures = []
        for (sheet, row, col), expected in self.expect.items():
            got = book.sheets[sheet].get((row, col), (None, None))[0]
            if not isinstance(got, float) or abs(got - expected) > 1e-6 * max(1.0, abs(expected)):
                failures.append((sheet, row, col, expected, got))
        self.assertEqual(failures[:5], [])


if __name__ == "__main__":
    unittest.main()
