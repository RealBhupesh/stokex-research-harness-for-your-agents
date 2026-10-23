import math
import pathlib
import random
import sys
import unittest

from stockex.deals.analysis import analyze, breakevens, monte_carlo, sensitivities, solve
from stockex.deals.case import DealCaseError, load_case
from stockex.deals.lbo import irr, run_lbo, sources_and_uses
from stockex.deals.valuation import dcf, quartile, wacc

from deal_fixtures import demo_raw, modified, textbook_raw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from finance_helpers import fcff_dcf  # noqa: E402


class CaseValidationTests(unittest.TestCase):
    def test_demo_case_loads_and_resolves_scenarios(self):
        case = load_case(demo_raw())
        self.assertEqual(set(case.scenarios), {"base", "upside", "downside"})
        self.assertEqual(case.scenarios["upside"]["da_pct"], case.scenarios["base"]["da_pct"])
        self.assertAlmostEqual(case.ltm_ebitda, 408.0)

    def test_invalid_cases_fail_with_codes_and_paths(self):
        raw = demo_raw()
        cases = [
            (modified(raw, balance_sheet__cash=261.0), "BALANCE_SHEET_UNBALANCED", "$.balance_sheet"),
            (modified(raw, scenarios__upside__probability=0.4), "DEAL_CASE_INVALID", "$.scenarios"),
            (modified(raw, debt__1__amortization=[0.1, 0, 0, 0, 0]), "DEAL_CASE_INVALID", "$.debt[1].amortization"),
            (modified(raw, transaction__holding_years=7), "DEAL_CASE_INVALID", "$.transaction.holding_years"),
            (modified(raw, scenarios__base__revenue_growth=[0.1, 0.1]), "DEAL_CASE_INVALID",
             "$.scenarios.base.revenue_growth"),
        ]
        for case, code, path in cases:
            with self.subTest(path=path):
                with self.assertRaises(DealCaseError) as caught:
                    load_case(case)
                self.assertEqual((caught.exception.code, caught.exception.path), (code, path))


class EquityChequeTests(unittest.TestCase):
    def test_a_deal_funded_entirely_by_debt_is_rejected(self):
        with self.assertRaises(DealCaseError) as caught:
            run_lbo(load_case(modified(textbook_raw(), debt__0__ebitda_multiple=8.0)))
        self.assertEqual(caught.exception.code, "EQUITY_CHEQUE_NOT_POSITIVE")


class TextbookLboTests(unittest.TestCase):
    """Small cases whose answers are worked by hand in the comments."""

    def test_no_sweep_cash_builds_and_returns_match_hand_calculation(self):
        result = run_lbo(load_case(textbook_raw()))
        su, r = result["sources_uses"], result["returns"]
        self.assertAlmostEqual(su["entry_multiple"], 8.0)
        self.assertAlmostEqual(su["sponsor_equity"], 80.0)
        # Net income 20 - 8 = 12 a year accumulates as cash; exit EV 160 less net debt (80 - 36).
        self.assertAlmostEqual(result["statements"]["cash"][-1], 36.0)
        self.assertAlmostEqual(r["moic"], 116 / 80)
        self.assertAlmostEqual(r["irr"], (116 / 80) ** (1 / 3) - 1, places=9)
        self.assertTrue(result["checks"]["ok"])

    def test_cash_sweep_repays_debt_from_free_cash_flow(self):
        result = run_lbo(load_case(textbook_raw(sweep=True)))
        # 80 -> 68 -> 54.8 -> 40.28: each year's 20 - 10% x opening balance repays debt.
        self.assertEqual([round(x, 6) for x in result["statements"]["tranches"][0]["closing"]], [68.0, 54.8, 40.28])
        self.assertAlmostEqual(result["returns"]["moic"], (160 - 40.28) / 80)
        self.assertTrue(all(abs(c) < 1e-9 for c in result["statements"]["cash"]))

    def test_pik_accretes_and_is_added_back_to_cash_flow(self):
        result = run_lbo(load_case(textbook_raw(pik=0.05)))
        closing = result["statements"]["tranches"][0]["closing"]
        self.assertEqual([round(x, 6) for x in closing], [84.0, 88.2, 92.61])
        self.assertAlmostEqual(result["statements"]["cash"][-1], 12 + 11.6 + 11.18)
        self.assertAlmostEqual(result["returns"]["moic"], (160 - (92.61 - 34.78)) / 80)

    def test_interest_cap_disallows_excess_interest_and_carries_it_forward(self):
        raw = modified(textbook_raw(), projection__tax_rate=0.25, debt__0__subject_to_interest_cap=True)
        fin = run_lbo(load_case(raw))["statements"]
        # Interest 8 against a cap of 30% x 20 = 6: 2 is disallowed, so tax is 25% of (12 + 2).
        self.assertEqual([round(x, 9) for x in fin["disallowed_interest"]], [2.0, 2.0, 2.0])
        self.assertAlmostEqual(fin["tax"][0], 3.5)
        self.assertAlmostEqual(fin["carryforward"][-1], 6.0)
        uncaught = run_lbo(load_case(modified(raw, debt__0__subject_to_interest_cap=False)))["statements"]
        self.assertEqual(uncaught["disallowed_interest"], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(uncaught["tax"][0], 3.0)

    def test_covenant_breach_is_found_in_the_expected_year(self):
        raw = modified(textbook_raw(), covenants__max_net_leverage=[3.5, 3.0, 2.0])
        cov = run_lbo(load_case(raw))["covenants"]
        # Net debt / EBITDA is 68/20 = 3.4, 56/20 = 2.8 and 44/20 = 2.2: the first failure is FY29.
        self.assertEqual(cov["first_breach"]["year"], "FY29")
        self.assertEqual(cov["first_breach"]["tests"], ["NET_LEVERAGE"])

    def test_revolver_funds_a_shortfall_and_is_repaid_before_the_sweep(self):
        raw = modified(textbook_raw(sweep=True), scenarios__base__capex_pct=[0.25, 0.0, 0.0],
                       scenarios__base__da_pct=[0.0, 0.0, 0.0])
        fin = run_lbo(load_case(raw))["statements"]
        # Year 1: net income 12 less capex 25 leaves a 13 gap; the revolver covers 10 and cash dips to -3.
        self.assertAlmostEqual(fin["revolver_draw"][0], 10.0)
        self.assertTrue(fin["liquidity_shortfall"][0])
        # Year 2: net income 20 - 8 - 0.8 = 11.2 first restores cash, then repays 8.2 of the revolver; no sweep.
        self.assertAlmostEqual(fin["revolver"][1], 1.8)
        self.assertAlmostEqual(fin["prepayment"][1], 0.0)
        # Year 3: net income 20 - 8 - 0.144 = 11.856 clears the revolver (1.8) and sweeps the rest.
        self.assertAlmostEqual(fin["revolver"][2], 0.0)
        self.assertAlmostEqual(fin["prepayment"][2], 11.856 - 1.8)


class RandomisedIntegrityTests(unittest.TestCase):
    def test_statements_balance_and_tie_across_randomised_cases(self):
        rng = random.Random(11)
        for trial in range(50):
            raw = demo_raw()
            for name in ("base", "upside", "downside"):
                spec = raw["scenarios"][name]
                if "revenue_growth" in spec:
                    spec["revenue_growth"] = [rng.uniform(-0.15, 0.3) for _ in range(5)]
            raw["transaction"]["offer_premium"] = rng.uniform(0, 0.6)
            raw["transaction"]["sweep_pct"] = rng.choice([0.0, 0.5, 1.0])
            raw["transaction"]["minimum_cash"] = rng.uniform(0, 250)
            raw["debt"][0]["ebitda_multiple"] = rng.uniform(0, 3)
            raw["debt"][1]["ebitda_multiple"] = rng.uniform(0, 4)
            raw["debt"][1]["sweep"] = rng.random() < 0.5
            raw["debt"][1]["pik_rate"] = rng.uniform(0, 0.06)
            raw["projection"]["cash_yield"] = rng.uniform(0, 0.07)
            case = load_case(raw)
            for scenario in case.scenarios:
                with self.subTest(trial=trial, scenario=scenario):
                    result = run_lbo(case, scenario, ebitda_haircut=rng.uniform(0, 0.5))
                    self.assertTrue(result["checks"]["ok"], result["checks"])
                    fin = result["statements"]
                    for i in range(case.years):
                        self.assertLessEqual(fin["revolver"][i], case.revolver["commitment"] + 1e-9)
                        if not fin["liquidity_shortfall"][i]:
                            self.assertGreaterEqual(fin["cash"][i], case.transaction["minimum_cash"] - 1e-9)
                        if fin["revolver"][i] > 1e-9:
                            self.assertAlmostEqual(fin["prepayment"][i], 0.0)
                        for tranche in fin["tranches"]:
                            self.assertGreaterEqual(tranche["closing"][i], -1e-9)


class ValuationTests(unittest.TestCase):
    def test_wacc_build_up_matches_hand_calculation(self):
        case = load_case(textbook_raw())
        w = wacc(case)
        unlevered = sorted([1.2 / (1 + 0.75 * 0.5), 0.9, 1.0 / (1 + 0.75 * 0.25)])[1]
        beta = unlevered * (1 + (1 - 0.0) * 0.25)  # textbook tax rate is 0
        ke = 0.07 + beta * 0.07
        self.assertAlmostEqual(w["unlevered_beta"], unlevered)
        self.assertAlmostEqual(w["wacc"], 0.8 * ke + 0.2 * 0.09)

    def test_dcf_without_mid_year_matches_the_existing_helper(self):
        case = load_case(textbook_raw())
        d = dcf(case, discount_rate=0.11, terminal_growth=0.03)
        net_debt = case.balance_sheet["debt"] - case.balance_sheet["cash"]
        helper = fcff_dcf(d["fcff"], 0.11, 0.03, net_debt, case.market["diluted_shares"])
        self.assertAlmostEqual(d["gordon"]["enterprise_value"], helper["enterprise_value"])
        self.assertAlmostEqual(d["gordon"]["value_per_share"], helper["value_per_share"])

    def test_exit_multiple_at_the_implied_multiple_reproduces_the_gordon_value(self):
        case = load_case(demo_raw())
        first = dcf(case)
        second = dcf(case, exit_multiple=first["implied_exit_multiple"])
        self.assertAlmostEqual(second["exit"]["enterprise_value"], first["gordon"]["enterprise_value"], places=6)
        self.assertAlmostEqual(second["implied_terminal_growth"], first["terminal_growth"], places=9)

    def test_quartile_follows_excel_inclusive_interpolation(self):
        self.assertEqual(quartile([1, 2, 3, 4], 1), 1.75)
        self.assertEqual(quartile([4, 1, 3, 2], 2), 2.5)
        self.assertEqual(quartile([1, 2, 3, 4], 3), 3.25)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_case(demo_raw())
        cls.bids = breakevens(cls.case)

    def test_irr_against_known_cash_flows(self):
        self.assertAlmostEqual(irr([-100, 0, 0, 0, 0, 248.832]), 0.2, places=9)
        self.assertAlmostEqual(irr([-100, 10, 10, 110]), 0.1, places=9)
        self.assertIsNone(irr([100, 10]))

    def test_breakeven_solvers_hit_their_targets(self):
        b, case = self.bids, self.case
        self.assertAlmostEqual(run_lbo(case, exit_multiple=b["exit_multiple_for_2x"])["returns"]["moic"], 2.0, places=6)
        self.assertAlmostEqual(run_lbo(case, exit_multiple=b["exit_multiple_for_hurdle_irr"])["returns"]["irr"],
                               case.transaction["hurdle_irr"], places=6)
        self.assertAlmostEqual(run_lbo(case, price=b["price_at_hurdle_irr"])["returns"]["irr"],
                               case.transaction["hurdle_irr"], places=6)
        self.assertAlmostEqual(run_lbo(case, "downside", price=b["price_at_downside_1x"])["returns"]["moic"], 1.0,
                               places=6)
        haircut = b["ebitda_haircut_to_covenant_breach"]
        self.assertIsNone(run_lbo(case, ebitda_haircut=haircut - 1e-4)["covenants"]["first_breach"])
        self.assertIsNotNone(run_lbo(case, ebitda_haircut=haircut + 1e-4)["covenants"]["first_breach"])
        self.assertEqual(b["max_bid"], min(b["price_at_hurdle_irr"], b["price_at_downside_1x"]))

    def test_sensitivities_are_monotonic_and_centred_on_the_base_case(self):
        sens = sensitivities(self.case)
        base_irr = run_lbo(self.case)["returns"]["irr"]
        grid = sens["irr_entry_exit"]
        self.assertAlmostEqual(grid["values"][2][2], base_irr, places=9)
        for row in grid["values"]:
            self.assertEqual(row, sorted(row))
        for col in range(5):
            column = [grid["values"][r][col] for r in range(5)]
            self.assertEqual(column, sorted(column, reverse=True))

    def test_monte_carlo_is_seeded_and_reproducible(self):
        small = load_case(modified(demo_raw(), monte_carlo__paths=60))
        first, second = monte_carlo(small), monte_carlo(small)
        self.assertEqual(first, second)
        self.assertEqual(sum(b["count"] for b in first["histogram"]), 60)
        self.assertLessEqual(first["irr"]["p5"], first["irr"]["p50"])
        self.assertLessEqual(first["irr"]["p50"], first["irr"]["p95"])

    def test_sponsor_equity_is_the_plug_for_any_price(self):
        for price in (300.0, 475.0, 700.0):
            su = sources_and_uses(self.case, price=price)
            self.assertAlmostEqual(su["total_sources"], su["total_uses"])

    def test_solver_returns_none_when_not_bracketed(self):
        self.assertIsNone(solve(lambda x: x * x, -1.0, 0.0, 5.0))
        self.assertAlmostEqual(solve(math.exp, 1.0, -3.0, 3.0), 0.0, places=8)

    def test_full_analysis_is_internally_consistent(self):
        results = analyze(load_case(modified(demo_raw(), monte_carlo__paths=40)))
        self.assertTrue(results["lbo"]["checks"]["ok"])
        bars = results["football_field"]
        self.assertTrue(all(bar["low"] <= bar["high"] for bar in bars))
        weighted = results["scenarios"]["probability_weighted"]["moic"]
        rows = results["scenarios"]["rows"]
        self.assertAlmostEqual(weighted, sum(r["probability"] * r["moic"] for r in rows.values()))


if __name__ == "__main__":
    unittest.main()
