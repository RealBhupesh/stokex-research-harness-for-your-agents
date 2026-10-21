"""Build the banker-format deal workbook with live formulas.

Every calculation is an Excel formula that traces back to the blue inputs on
the Inputs sheet. Changing the case selector, an input or a sensitivity shift
in Excel flows through the statements, the debt schedule and the returns.

The Python engine is a separate implementation of the same model. Each mapped
row registers the engine's value as an expectation. Tests recompute the saved
file with ``formula_eval`` (and LibreOffice, when installed) and require the
two to agree.

Conventions:
- blue = input, black = calculation, green = link to another sheet;
- the same column is the same fiscal year on every time-series sheet.
"""

from .formula_eval import Book, Evaluator
from .xlsx import Workbook, address, column_letter

LABEL, UNIT, VALUE = 2, 3, 4
NAVY, GREEN, GREY, ORANGE = "1F3864", "00703C", "7F7F7F", "C55A11"


class _Builder:
    def __init__(self, case, results):
        self.case, self.results = case, results
        self.wb = Workbook(title=f"{case.name}: {case.company}")
        self.styles = self.wb.styles
        self.n_hist, self.n = len(case.historical_years), case.years
        self.proj_start = VALUE + max(self.n_hist, 3)
        self.proj_cols = [self.proj_start + i for i in range(self.n)]
        self.hist_cols = [self.proj_start - self.n_hist + i for i in range(self.n_hist)]
        self.last_hist = self.proj_start - 1
        self.rows: dict[tuple[str, str], int] = {}
        self.next_row: dict[str, int] = {}
        self.pending: list = []
        self.expect: dict[tuple[str, int, int], float] = {}
        self.current = None

    # ---------- addressing ----------
    def style(self, kind="calc", fmt="num", **extra):
        font = {"calc": "normal", "input": "input", "link": "link", "total": "bold", "key": "bold",
                "label": "normal", "bold": "bold", "header": "header", "note": "note", "section": "section",
                "title": "title", "subtitle": "subtitle", "good": "good", "bad": "bad"}[kind]
        fill = {"input": "input", "header": "header", "key": "key"}.get(kind, "none")
        border = {"total": "total", "key": "top"}.get(kind, "none")
        return self.styles.get(font=font, fill=fill, fmt=fmt, border=border, **extra)

    def row_of(self, sheet: str, key: str) -> int:
        return self.rows[(sheet, key)]

    def ref(self, sheet: str, key: str, col: int | None = None, *, absolute: bool | None = None) -> str:
        col = VALUE if col is None else col
        absolute = (col == VALUE) if absolute is None else absolute
        cell = address(self.row_of(sheet, key), col, absolute=absolute)
        return cell if sheet == self.current else f"{sheet}!{cell}"

    def span(self, sheet: str, key: str, cols: list[int]) -> str:
        row = self.row_of(sheet, key)
        cell = f"{address(row, cols[0], absolute=True)}:{address(row, cols[-1], absolute=True)}"
        return cell if sheet == self.current else f"{sheet}!{cell}"

    def take_row(self, sheet: str, gap: int = 0) -> int:
        row = self.next_row[sheet] + gap
        self.next_row[sheet] = row + 1
        return row

    def skip(self, sheet: str, rows: int = 1):
        self.next_row[sheet] += rows

    # ---------- writers ----------
    def sheet(self, name: str, title: str, subtitle: str, tab: str = NAVY):
        ws = self.wb.add_sheet(name, tab)
        ws.widths.update({1: 2.5, LABEL: 46, UNIT: 11})
        for col in range(VALUE, self.proj_start + self.n + 4):
            ws.widths[col] = 12.5
        ws.set(2, LABEL, title, style=self.style("title", "general"))
        ws.set(3, LABEL, subtitle, style=self.style("subtitle", "general"))
        self.next_row[name] = 5
        return ws

    def header(self, sheet: str, label: str, *, historical=True, bs=False, close_label=None):
        row = self.take_row(sheet)
        ws = self.wb.sheet(sheet)
        style = self.style("header", "general", align="right")
        ws.set(row, LABEL, label, style=self.style("header", "general"))
        ws.set(row, UNIT, self.case.raw.get("currency", ""), style=style)
        if bs:
            for col, text in zip((self.last_hist - 2, self.last_hist - 1, self.last_hist),
                                 (f"{self.case.historical_years[-1]}A", "Adjustments", "Pro forma")):
                ws.set(row, col, text, style=style)
        elif historical:
            for col, year in zip(self.hist_cols, self.case.historical_years):
                ws.set(row, col, f"{year}A", style=style)
        if close_label:
            ws.set(row, self.last_hist, close_label, style=style)
        for col, year in zip(self.proj_cols, self.case.projection_years):
            ws.set(row, col, f"{year}E", style=style)
        for col in range(VALUE, self.proj_start + self.n):
            if (row, col) not in ws.cells:
                ws.set(row, col, None, style=style)
        return row

    def section(self, sheet: str, text: str, gap: int = 1):
        row = self.take_row(sheet, gap)
        self.wb.sheet(sheet).set(row, LABEL, text, style=self.style("section", "general"))
        return row

    def note(self, sheet: str, text: str, gap: int = 0):
        row = self.take_row(sheet, gap)
        self.wb.sheet(sheet).set(row, LABEL, text, style=self.style("note", "general"))
        return row

    def _put(self, sheet, row, col, content, style, expected=None):
        ws = self.wb.sheet(sheet)
        if callable(content):
            ws.set(row, col, None, style=style)
            self.pending.append((sheet, row, col, content, style))
        else:
            ws.set(row, col, content, style=style)
        if expected is not None:
            self.expect[(sheet, row, col)] = expected

    def series(self, sheet: str, key: str, label: str, *, proj=None, hist=None, fmt="num", kind="calc",
               expected=None, hist_expected=None, unit="", indent=0, first=None):
        """A time-series row.

        ``hist`` is a list of input values or a callable (i, col) -> formula (or None for a blank).
        ``proj`` is a list of input values or a callable (i, col) -> formula.
        ``first`` = (content, style kind) fills the column just before the projections
        (the close / opening-balance column).
        """
        row = self.take_row(sheet)
        self.rows[(sheet, key)] = row
        ws = self.wb.sheet(sheet)
        ws.set(row, LABEL, label, style=self.styles.get(font="bold" if kind in {"total", "key"} else "normal",
                                                         indent=indent))
        if unit:
            ws.set(row, UNIT, unit, style=self.style("note", "general", align="right"))
        if hist is not None:
            for i, col in enumerate(self.hist_cols):
                exp = None if hist_expected is None else hist_expected[i]
                if isinstance(hist, list):
                    if hist[i] is not None:
                        self._put(sheet, row, col, hist[i], self.style("input", fmt), exp)
                else:
                    self._put(sheet, row, col, (lambda i=i, col=col: hist(i, col)),
                              self.style("calc" if kind == "link" else kind, fmt), exp)
        if first is not None:
            content, style_kind = first
            self._put(sheet, row, self.last_hist, content, self.style(style_kind, fmt))
        if proj is not None:
            for i, col in enumerate(self.proj_cols):
                if isinstance(proj, list):
                    self._put(sheet, row, col, proj[i], self.style("input", fmt))
                else:
                    self._put(sheet, row, col, (lambda i=i, col=col: proj(i, col)), self.style(kind, fmt),
                              None if expected is None else expected[i])
        return row

    def scalar(self, sheet: str, key: str, label: str, content, *, fmt="num", kind="calc", name=None,
               expected=None, unit="", col=VALUE, note=None):
        row = self.take_row(sheet)
        self.rows[(sheet, key)] = row
        ws = self.wb.sheet(sheet)
        ws.set(row, LABEL, label, style=self.styles.get(font="bold" if kind in {"total", "key"} else "normal"))
        if unit:
            ws.set(row, UNIT, unit, style=self.style("note", "general", align="right"))
        if callable(content):
            self._put(sheet, row, col, content, self.style(kind, fmt), expected)
        else:
            self._put(sheet, row, col, content, self.style("input" if kind == "calc" else kind, fmt), expected)
        if name:
            self.wb.define(name, sheet, row, col)
        if note:
            ws.set(row, col + 2, note, style=self.style("note", "general"))
        return row

    def render(self):
        for sheet, row, col, fn, style in self.pending:
            self.current = sheet
            formula = fn()
            if formula is None:
                self.wb.sheet(sheet).set(row, col, None, style=style)
                self.expect.pop((sheet, row, col), None)
            else:
                self.wb.sheet(sheet).set(row, col, formula=formula, style=style)
        self.current = None

    # ---------- sheets ----------
    def build(self):
        self.cover()
        self.inputs()
        self.income_statement()
        self.balance_sheet()
        self.cash_flow()
        self.debt()
        self.deal()
        self.returns()
        self.wacc()
        self.dcf()
        self.comps()
        self.sensitivity()
        self.football()
        self.checks()
        self.cover_outputs()
        self.render()
        for sheet in self.wb.sheets:
            if sheet.name in {"IS", "BS", "CF", "Debt"}:
                sheet.freeze = (5, 3)
            elif sheet.name in {"Inputs", "Returns", "DCF", "Deal", "Checks"}:
                sheet.freeze = (4, 0)
        book = Book.from_workbook(self.wb)
        values = Evaluator(book).evaluate_all()
        for (sheet, row, col), value in values.items():
            self.wb.sheet(sheet).cells[(row, col)].value = value
        return self.wb

    def cover(self):
        c = self.case
        ws = self.sheet("Cover", f"{c.name}", f"{c.company} | LBO, DCF and valuation model | "
                        f"{c.raw.get('currency', '')}, fiscal years ending {c.raw.get('fiscal_year_end', 'March')}")
        ws.widths[LABEL] = 54
        ws.widths[VALUE] = 16
        if c.illustrative:
            ws.set(4, LABEL, "ILLUSTRATIVE CASE: fictional company and invented figures, built to show the method.",
                   style=self.style("bad", "general"))
        self.next_row["Cover"] = 6

    def cover_outputs(self):
        s = "Cover"
        self.section(s, "Headline outputs (live: follow the case selector on Inputs)", 0)
        r = self.results
        lbo = r["lbo"]
        self.scalar(s, "case", "Live case", lambda: 'CHOOSE(Case,"Base","Upside","Downside")', fmt="general")
        self.scalar(s, "offer", "Offer price per share", lambda: self.ref("Deal", "offer_price"), fmt="price",
                    kind="link", expected=lbo["sources_uses"]["offer_price"])
        self.scalar(s, "premium", "Premium to unaffected price", lambda: "Offer_Premium", fmt="pct", kind="link")
        self.scalar(s, "entry", "Entry EV / LTM EBITDA", lambda: self.ref("Deal", "entry_multiple"), fmt="mult",
                    kind="link", expected=lbo["sources_uses"]["entry_multiple"])
        self.scalar(s, "leverage", "Total debt / LTM EBITDA", lambda: self.ref("Deal", "leverage"), fmt="mult",
                    kind="link", expected=lbo["sources_uses"]["leverage"])
        self.scalar(s, "equity", "Sponsor equity", lambda: self.ref("Deal", "sponsor_equity"), kind="link",
                    expected=lbo["sources_uses"]["sponsor_equity"])
        self.scalar(s, "irr", "Sponsor IRR", lambda: self.ref("Returns", "irr"), fmt="pct", kind="key",
                    expected=lbo["returns"]["irr"])
        self.scalar(s, "moic", "Sponsor MOIC", lambda: self.ref("Returns", "moic"), fmt="mult2", kind="key",
                    expected=lbo["returns"]["moic"])
        self.scalar(s, "dcf", "DCF value per share (Gordon growth)", lambda: self.ref("DCF", "per_share_gordon"),
                    fmt="price", kind="link", expected=r["dcf"]["gordon"]["value_per_share"])
        self.scalar(s, "wacc", "WACC", lambda: "WACC_Rate", fmt="pct", kind="link", expected=r["wacc"]["wacc"])
        self.scalar(s, "checks", "Model integrity checks", lambda: self.ref("Checks", "overall"), fmt="general",
                    kind="key")
        self.section(s, "How to read this workbook")
        for text in ("Blue cells on yellow are inputs. Black cells are formulas. Green cells link to another sheet.",
                     "Every formula traces back to Inputs. Change the case selector (1 Base, 2 Upside, 3 Downside) or "
                     "the shifts on Inputs and the whole model updates.",
                     "Interest accrues on opening balances, so the model has no circular reference.",
                     "Sensitivity and Football hold values computed by the STOCKEX engine; they do not update live.",
                     "Sheets: Inputs, IS, BS, CF, Debt, Deal (sources and uses), Returns (exit, bridge, covenants), "
                     "WACC, DCF, Comps, Sensitivity, Football, Checks.",
                     "The STOCKEX test suite recomputes every formula in this file from the inputs and requires it to "
                     "match the Python engine."):
            self.note(s, text)

    def inputs(self):
        c, s = self.case, "Inputs"
        self.sheet(s, "Inputs", "Every blue cell drives the model. Scenario blocks feed the live rows via the selector.")
        tx, rv, cv = c.transaction, c.revolver, c.covenants
        self.section(s, "Case selector", 0)
        self.scalar(s, "case", "Live case (1 Base, 2 Upside, 3 Downside)", 1, fmt="int", name="Case")
        self.section(s, "Transaction")
        rows = [
            ("unaffected", "Unaffected share price", c.market["unaffected_price"], "price", "Unaffected_Price", "₹"),
            ("premium", "Offer premium to unaffected", tx["offer_premium"], "pct", "Offer_Premium", ""),
            ("shares", "Diluted shares", c.market["diluted_shares"], "num2", "Diluted_Shares",
             c.raw.get("share_unit", "")),
            ("txn_fee", "Transaction fees (% of entry EV)", tx["transaction_fee_pct"], "pct2", "Txn_Fee_Pct", ""),
            ("fin_fee", "Financing fees (% of debt raised)", tx["financing_fee_pct"], "pct2", "Fin_Fee_Pct", ""),
            ("fee_years", "Financing fee amortisation period", tx["financing_fee_amortisation_years"], "num",
             "Fee_Amort_Years", "years"),
            ("min_cash", "Minimum operating cash", tx["minimum_cash"], "num", "Min_Cash", ""),
            ("rollover", "Promoter / management rollover (% of equity purchase)", tx["rollover_pct"], "pct",
             "Rollover_Pct", ""),
            ("leverage_scale", "Leverage scale (1.0 = tranche multiples below)", 1.0, "num2", "Leverage_Scale", "x"),
            ("sweep", "Excess cash swept to sweepable debt", tx["sweep_pct"], "pct", "Sweep_Pct", ""),
            ("holding", "Holding period", tx["holding_years"], "int", "Holding_Years", "years"),
            ("exit_cost", "Exit costs (% of exit EV)", tx["exit_cost_pct"], "pct2", "Exit_Cost_Pct", ""),
            ("mip", "Management incentive pool (% of equity gain)", tx["management_incentive_pct"], "pct",
             "MIP_Pct", ""),
            ("hurdle", "Sponsor hurdle IRR", tx["hurdle_irr"], "pct", "Hurdle_IRR", ""),
            ("target_moic", "Sponsor target MOIC", tx["target_moic"], "mult2", "Target_MOIC", ""),
        ]
        for key, label, value, fmt, name, unit in rows:
            self.scalar(s, key, label, value, fmt=fmt, name=name, unit=unit)
        self.section(s, "Operating, tax and sensitivity shifts")
        for key, label, value, fmt, name in (
                ("tax", "Corporate tax rate (s.115BAA: 22% + 10% surcharge + 4% cess)", c.projection["tax_rate"],
                 "pct2", "Tax_Rate"),
                ("cash_yield", "Interest earned on cash", c.projection["cash_yield"], "pct2", "Cash_Yield"),
                ("cap_pct", "Interest cap (% of tax EBITDA), s.94B", c.tax["interest_cap_pct_ebitda"], "pct",
                 "Cap_Pct"),
                ("cap_threshold", "Interest cap threshold (caught interest)", c.tax["interest_cap_threshold"], "num",
                 "Cap_Threshold"),
                ("growth_shift", "Revenue growth shift (added every year)", 0.0, "pct", "Growth_Shift"),
                ("margin_shift", "Gross / EBITDA margin shift (added every year)", 0.0, "pct", "Margin_Shift"),
                ("haircut", "EBITDA haircut (proportional)", 0.0, "pct", "EBITDA_Haircut")):
            self.scalar(s, key, label, value, fmt=fmt, name=name)
        self.section(s, "Revolver and covenants")
        for key, label, value, fmt, name in (
                ("rev_commitment", "Revolver commitment", rv["commitment"], "num", "Rev_Commitment"),
                ("rev_rate", "Revolver cash rate", rv["cash_rate"], "pct2", "Rev_Rate"),
                ("rev_fee", "Revolver undrawn fee", rv["undrawn_fee"], "pct2", "Rev_Undrawn_Fee"),
                ("min_icr", "Minimum interest cover (EBITDA / cash interest)", cv["min_interest_cover"], "mult2",
                 "Min_ICR"),
                ("min_dscr", "Minimum DSCR ((EBITDA - capex - tax) / debt service)", cv["min_dscr"], "mult2",
                 "Min_DSCR")):
            self.scalar(s, key, label, value, fmt=fmt, name=name)

        self.section(s, "Exit multiple (EV / EBITDA)")
        names = [n for n in ("base", "upside", "downside")]
        for n in names:
            scenario = c.scenarios.get(n, c.scenarios["base"])
            self.scalar(s, f"exit_{n}", f"{n.title()} case", scenario["exit_multiple"], fmt="mult")
        self.scalar(s, "exit_live", "Live exit multiple",
                    lambda: "CHOOSE(Case," + ",".join(self.ref(s, f"exit_{n}") for n in names) + ")",
                    fmt="mult", kind="total", name="Exit_Multiple",
                    expected=self.results["lbo"]["returns"]["exit_multiple"])

        self.skip(s)
        self.header(s, "Operating drivers by case", historical=False)
        labels = {"revenue_growth": ("Revenue growth", "pct"), "gross_margin": ("Gross margin", "pct"),
                  "opex_pct": ("Operating expenses (ex D&A) % of revenue", "pct"),
                  "da_pct": ("D&A % of revenue", "pct"), "capex_pct": ("Capex % of revenue", "pct"),
                  "receivable_days": ("Receivable days (on revenue)", "num"),
                  "inventory_days": ("Inventory days (on COGS)", "num"),
                  "payable_days": ("Payable days (on COGS)", "num")}
        base_drivers = self.results["lbo"]["drivers"]
        for driver, (label, fmt) in labels.items():
            self.section(s, label)
            for n in names:
                scenario = c.scenarios.get(n, c.scenarios["base"])
                self.series(s, f"{n}_{driver}", f"{n.title()}", proj=list(scenario[driver]), fmt=fmt, indent=1)
            self.series(s, f"live_{driver}", "Live", kind="total", fmt=fmt,
                        proj=lambda i, col, d=driver: "CHOOSE(Case," + ",".join(
                            self.ref(s, f"{n}_{d}", col) for n in names) + ")",
                        expected=base_drivers[driver])
        self.section(s, "Maximum net leverage covenant")
        self.series(s, "max_leverage", "Net debt / EBITDA (maximum)", proj=list(cv["max_net_leverage"]), fmt="mult2")

        self.skip(s)
        self.header(s, "Debt tranches (sized on LTM EBITDA at close)", historical=False)
        for k, t in enumerate(c.tranches):
            self.section(s, f"Tranche {k + 1}: {t.name} ({t.kind})")
            self.scalar(s, f"t{k}_multiple", "Size (x LTM EBITDA)", t.ebitda_multiple, fmt="mult2")
            self.scalar(s, f"t{k}_cash", "Cash coupon", t.cash_rate, fmt="pct2")
            self.scalar(s, f"t{k}_pik", "PIK coupon (accretes to principal)", t.pik_rate, fmt="pct2")
            self.scalar(s, f"t{k}_sweep", "Receives cash sweep (1 = yes)", 1 if t.sweep else 0, fmt="int")
            self.scalar(s, f"t{k}_cap", "Interest caught by s.94B cap (1 = yes)", 1 if t.subject_to_interest_cap
                        else 0, fmt="int")
            self.series(s, f"t{k}_amort", "Scheduled amortisation (% of original principal)",
                        proj=list(t.amortization), fmt="pct")

    def income_statement(self):
        c, s = self.case, "IS"
        lbo = self.results["lbo"]
        plan, fin = lbo["plan"], lbo["statements"]
        h = c.historicals
        self.sheet(s, "Income statement", "Historical figures are inputs; projections follow the live case.")
        self.header(s, "Income statement")
        I = "Inputs"
        self.series(s, "revenue", "Revenue", kind="total", hist=h["revenue"],
                    proj=lambda i, col: f"{self.ref(s, 'revenue', col - 1)}*(1+{self.ref(I, 'live_revenue_growth', col)}"
                                        f"+Growth_Shift)", expected=plan["revenue"])
        self.series(s, "growth", "Growth", fmt="pct", indent=1,
                    hist=lambda i, col: None if i == 0 else f"{self.ref(s, 'revenue', col)}/{self.ref(s, 'revenue', col - 1)}-1",
                    proj=lambda i, col: f"{self.ref(s, 'revenue', col)}/{self.ref(s, 'revenue', col - 1)}-1",
                    expected=plan["revenue_growth"])
        self.series(s, "cogs", "Cost of goods sold", hist=h["cogs"],
                    proj=lambda i, col: f"{self.ref(s, 'revenue', col)}-{self.ref(s, 'gross_profit', col)}",
                    expected=plan["cogs"])
        self.series(s, "gross_profit", "Gross profit", kind="total",
                    hist=lambda i, col: f"{self.ref(s, 'revenue', col)}-{self.ref(s, 'cogs', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'revenue', col)}*({self.ref(I, 'live_gross_margin', col)}"
                                        f"+Margin_Shift)", expected=plan["gross_profit"])
        self.series(s, "gross_margin", "Gross margin", fmt="pct", indent=1,
                    hist=lambda i, col: f"{self.ref(s, 'gross_profit', col)}/{self.ref(s, 'revenue', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'gross_profit', col)}/{self.ref(s, 'revenue', col)}")
        self.series(s, "opex", "Operating expenses (ex D&A)", hist=h["opex"],
                    proj=lambda i, col: (f"{self.ref(s, 'revenue', col)}*{self.ref(I, 'live_opex_pct', col)}"
                                         f"+EBITDA_Haircut*({self.ref(s, 'gross_profit', col)}-"
                                         f"{self.ref(s, 'revenue', col)}*{self.ref(I, 'live_opex_pct', col)})"),
                    expected=plan["opex"])
        self.series(s, "ebitda", "EBITDA", kind="key",
                    hist=lambda i, col: f"{self.ref(s, 'gross_profit', col)}-{self.ref(s, 'opex', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'gross_profit', col)}-{self.ref(s, 'opex', col)}",
                    expected=plan["ebitda"])
        self.series(s, "ebitda_margin", "EBITDA margin", fmt="pct", indent=1,
                    hist=lambda i, col: f"{self.ref(s, 'ebitda', col)}/{self.ref(s, 'revenue', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'ebitda', col)}/{self.ref(s, 'revenue', col)}",
                    expected=plan["ebitda_margin"])
        self.series(s, "da", "Depreciation and amortisation", hist=h["da"],
                    proj=lambda i, col: f"{self.ref(s, 'revenue', col)}*{self.ref(I, 'live_da_pct', col)}",
                    expected=plan["da"])
        self.series(s, "ebit", "EBIT", kind="total",
                    hist=lambda i, col: f"{self.ref(s, 'ebitda', col)}-{self.ref(s, 'da', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'ebitda', col)}-{self.ref(s, 'da', col)}", expected=plan["ebit"])
        self.series(s, "other_income", "Other income / interest on cash", hist=h["other_income"],
                    proj=lambda i, col: self.ref("Debt", "interest_income", col), kind="link",
                    expected=fin["interest_income"])
        self.series(s, "finance_cost", "Finance cost", hist=h["finance_cost"],
                    proj=lambda i, col: self.ref("Debt", "finance_cost", col), kind="link",
                    expected=fin["finance_cost"])
        self.series(s, "pbt", "Profit before tax", kind="total",
                    hist=lambda i, col: f"{self.ref(s, 'ebit', col)}+{self.ref(s, 'other_income', col)}-"
                                        f"{self.ref(s, 'finance_cost', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'ebit', col)}+{self.ref(s, 'other_income', col)}-"
                                        f"{self.ref(s, 'finance_cost', col)}", expected=fin["pbt"])
        self.series(s, "tax", "Tax", hist=h["tax"], proj=lambda i, col: self.ref(s, "tax_amount", col),
                    expected=fin["tax"])
        self.series(s, "net_income", "Net income", kind="key",
                    hist=lambda i, col: f"{self.ref(s, 'pbt', col)}-{self.ref(s, 'tax', col)}",
                    proj=lambda i, col: f"{self.ref(s, 'pbt', col)}-{self.ref(s, 'tax', col)}",
                    expected=fin["net_income"])

        self.skip(s)
        self.header(s, "Tax schedule (interest limitation and losses)", historical=False, close_label="At close")
        D = "Debt"
        self.series(s, "interest_for_cap", "Interest expense for the cap (cash + PIK + revolver)",
                    proj=lambda i, col: f"{self.ref(D, 'cash_interest', col)}+{self.ref(D, 'pik_interest', col)}+"
                                        f"{self.ref(D, 'rev_interest', col)}+{self.ref(D, 'rev_fee', col)}",
                    expected=fin["interest_for_cap"])
        self.series(s, "tax_ebitda", "Tax EBITDA (EBITDA + interest income)",
                    proj=lambda i, col: f"{self.ref(s, 'ebitda', col)}+{self.ref(s, 'other_income', col)}")
        self.series(s, "interest_cap", "Interest cap", proj=lambda i, col: f"Cap_Pct*{self.ref(s, 'tax_ebitda', col)}",
                    expected=fin["interest_cap"])
        self.series(s, "subject_interest", "Interest on caught debt",
                    proj=lambda i, col: "+".join(
                        f"({self.ref(D, f't{k}_cash', col)}+{self.ref(D, f't{k}_pik', col)})*"
                        f"{self.ref('Inputs', f't{k}_cap')}" for k in range(len(self.case.tranches))))
        self.series(s, "disallowed", "Disallowed interest (carried forward)",
                    proj=lambda i, col: (f"IF({self.ref(s, 'subject_interest', col)}>Cap_Threshold,MIN(MAX(0,"
                                         f"{self.ref(s, 'interest_for_cap', col)}-{self.ref(s, 'interest_cap', col)}),"
                                         f"{self.ref(s, 'subject_interest', col)}),0)"),
                    expected=fin["disallowed_interest"])
        self.series(s, "cf_used", "Carried-forward interest deducted",
                    proj=lambda i, col: (f"MIN({self.ref(s, 'carryforward', col - 1)},MAX(0,"
                                         f"{self.ref(s, 'interest_cap', col)}-{self.ref(s, 'interest_for_cap', col)}))"),
                    expected=fin["carryforward_used"])
        self.series(s, "carryforward", "Disallowed interest carried forward (closing)", first=(0.0, "input"),
                    proj=lambda i, col: (f"{self.ref(s, 'carryforward', col - 1)}+{self.ref(s, 'disallowed', col)}-"
                                         f"{self.ref(s, 'cf_used', col)}"), expected=fin["carryforward"])
        self.series(s, "taxable_before", "Taxable income before losses",
                    proj=lambda i, col: (f"{self.ref(s, 'pbt', col)}+{self.ref(s, 'disallowed', col)}-"
                                         f"{self.ref(s, 'cf_used', col)}"))
        self.series(s, "loss_used", "Tax losses used",
                    proj=lambda i, col: (f"MIN({self.ref(s, 'tax_losses', col - 1)},MAX(0,"
                                         f"{self.ref(s, 'taxable_before', col)}))"), expected=fin["loss_used"])
        self.series(s, "tax_losses", "Tax losses carried forward (closing)", first=(0.0, "input"),
                    proj=lambda i, col: (f"{self.ref(s, 'tax_losses', col - 1)}-{self.ref(s, 'loss_used', col)}+"
                                         f"MAX(0,-{self.ref(s, 'taxable_before', col)})"), expected=fin["tax_losses"])
        self.series(s, "taxable", "Taxable income",
                    proj=lambda i, col: f"MAX(0,{self.ref(s, 'taxable_before', col)}-{self.ref(s, 'loss_used', col)})",
                    expected=fin["taxable_income"])
        self.series(s, "tax_amount", "Tax at the corporate rate", kind="total",
                    proj=lambda i, col: f"{self.ref(s, 'taxable', col)}*Tax_Rate", expected=fin["tax"])
        self.note(s, "s.94B of the Income-tax Act, 1961 (carried into the Income-tax Act, 2025) caps deductible "
                     "interest on debt from, or guaranteed by, non-resident associated enterprises at 30% of EBITDA. "
                     "Confirm applicability with tax counsel.", 1)

    def balance_sheet(self):
        c, s = self.case, "BS"
        lbo = self.results["lbo"]
        fin, plan, pf = lbo["statements"], lbo["plan"], lbo["pro_forma"]
        bs = c.balance_sheet
        I, D = "Inputs", "Debt"
        self.sheet(s, "Balance sheet", f"{c.historical_years[-1]}A is reported; the deal adjusts it to the pro forma "
                                       "balance sheet at close.")
        self.header(s, "Balance sheet", bs=True)
        a_col, adj_col, pf_col = self.last_hist - 2, self.last_hist - 1, self.last_hist
        A, ADJ, PF = column_letter(a_col), column_letter(adj_col), column_letter(pf_col)

        def pf_formula(key):
            return lambda: f"{A}{self.row_of(s, key)}+{ADJ}{self.row_of(s, key)}"

        def flat(key):
            return lambda i, col: self.ref(s, key, col - 1)

        def line(key, label, actual, adjustment, proj, expected=None, kind="calc", indent=0):
            row = self.series(s, key, label, proj=proj, kind=kind, expected=expected, indent=indent)
            ws = self.wb.sheet(s)
            if actual is not None:
                self._put(s, row, a_col, actual, self.style("input" if isinstance(actual, float) else "calc"))
            if adjustment is not None:
                self._put(s, row, adj_col, adjustment, self.style("link"))
            self._put(s, row, pf_col, pf_formula(key) if kind != "total" else None, self.style(kind))
            del ws
            return row

        self.section(s, "Assets", 0)
        line("cash", "Cash", bs["cash"], lambda: f"Min_Cash-{A}{self.row_of(s, 'cash')}",
             lambda i, col: self.ref("CF", "closing_cash", col), fin["cash"], kind="calc")
        line("receivables", "Trade receivables", bs["receivables"], None,
             lambda i, col: f"{self.ref('IS', 'revenue', col)}*{self.ref(I, 'live_receivable_days', col)}/365",
             fin["receivables"])
        line("inventory", "Inventory", bs["inventory"], None,
             lambda i, col: f"{self.ref('IS', 'cogs', col)}*{self.ref(I, 'live_inventory_days', col)}/365",
             fin["inventory"])
        line("oca", "Other current assets", bs["other_current_assets"], None, flat("oca"))
        line("ppe", "Property, plant and equipment", bs["ppe"], None,
             lambda i, col: f"{self.ref(s, 'ppe', col - 1)}-{self.ref('CF', 'capex', col)}-{self.ref('IS', 'da', col)}",
             fin["ppe"])
        line("intangibles", "Intangibles", bs["intangibles"], None, flat("intangibles"))
        line("goodwill", "Goodwill from the transaction", 0.0, lambda: self.ref("Deal", "goodwill"), flat("goodwill"),
             fin["goodwill"])
        line("onca", "Other non-current assets", bs["other_non_current_assets"], None, flat("onca"))
        line("dff", "Deferred financing fees", 0.0, lambda: self.ref("Deal", "fin_fees"),
             lambda i, col: f"{self.ref(s, 'dff', col - 1)}-{self.ref(D, 'fee_amort', col)}",
             fin["deferred_financing_fees"])
        asset_keys = ["cash", "receivables", "inventory", "oca", "ppe", "intangibles", "goodwill", "onca", "dff"]
        total_assets = self.series(s, "total_assets", "Total assets", kind="total",
                                   proj=lambda i, col: "+".join(self.ref(s, k, col) for k in asset_keys),
                                   expected=fin["total_assets"])
        for col in (a_col, adj_col, pf_col):
            self._put(s, total_assets, col, (lambda col=col: "+".join(
                f"{column_letter(col)}{self.row_of(s, k)}" for k in asset_keys)), self.style("total"),
                pf["total_assets"] if col == pf_col else None)

        self.section(s, "Liabilities and equity")
        line("payables", "Trade payables", bs["payables"], None,
             lambda i, col: f"{self.ref('IS', 'cogs', col)}*{self.ref(I, 'live_payable_days', col)}/365",
             fin["payables"])
        line("ocl", "Other current liabilities", bs["other_current_liabilities"], None, flat("ocl"))
        line("revolver", "Revolver", 0.0, None, lambda i, col: self.ref(D, "rev_closing", col), fin["revolver"])
        line("old_debt", "Existing debt (refinanced at close)", bs["debt"],
             lambda: f"-{A}{self.row_of(s, 'old_debt')}", flat("old_debt"))
        debt_keys = ["revolver", "old_debt"]
        for k, t in enumerate(c.tranches):
            line(f"t{k}", t.name, 0.0, (lambda k=k: self.ref("Deal", f"t{k}_principal")),
                 (lambda i, col, k=k: self.ref(D, f"t{k}_closing", col)),
                 [row for row in fin["tranches"][k]["closing"]])
            debt_keys.append(f"t{k}")
        line("oncl", "Other non-current liabilities", bs["other_non_current_liabilities"], None, flat("oncl"))
        line("equity", "Shareholders' equity", bs["equity"],
             lambda: f"{self.ref('Deal', 'total_equity')}-{self.ref('Deal', 'txn_fees')}-{A}{self.row_of(s, 'equity')}",
             lambda i, col: f"{self.ref(s, 'equity', col - 1)}+{self.ref('IS', 'net_income', col)}", fin["equity"])
        claim_keys = ["payables", "ocl"] + debt_keys + ["oncl", "equity"]
        total_claims = self.series(s, "total_claims", "Total liabilities and equity", kind="total",
                                   proj=lambda i, col: "+".join(self.ref(s, k, col) for k in claim_keys),
                                   expected=fin["total_claims"])
        for col in (a_col, adj_col, pf_col):
            self._put(s, total_claims, col, (lambda col=col: "+".join(
                f"{column_letter(col)}{self.row_of(s, k)}" for k in claim_keys)), self.style("total"),
                pf["total_claims"] if col == pf_col else None)
        check = self.series(s, "check", "Balance check (assets - liabilities and equity)",
                            proj=lambda i, col: f"ROUND({self.ref(s, 'total_assets', col)}-{self.ref(s, 'total_claims', col)},6)",
                            expected=[0.0] * self.n)
        for col in (a_col, pf_col):
            self._put(s, check, col, (lambda col=col: f"ROUND({column_letter(col)}{total_assets}-{column_letter(col)}"
                                                      f"{total_claims},6)"), self.style("calc"), 0.0)

        self.section(s, "Memo")
        nwc = self.series(s, "nwc", "Trade working capital (receivables + inventory - payables)",
                          proj=lambda i, col: (f"{self.ref(s, 'receivables', col)}+{self.ref(s, 'inventory', col)}-"
                                               f"{self.ref(s, 'payables', col)}"), expected=plan["nwc"])
        self._put(s, nwc, pf_col, lambda: f"{PF}{self.row_of(s, 'receivables')}+{PF}{self.row_of(s, 'inventory')}-"
                                          f"{PF}{self.row_of(s, 'payables')}", self.style("calc"))
        self.series(s, "total_debt", "Total debt", proj=lambda i, col: "+".join(self.ref(s, k, col) for k in debt_keys),
                    expected=fin["total_debt"])
        self.series(s, "net_debt", "Net debt", kind="total",
                    proj=lambda i, col: f"{self.ref(s, 'total_debt', col)}-{self.ref(s, 'cash', col)}",
                    expected=fin["net_debt"])

    def cash_flow(self):
        s = "CF"
        lbo = self.results["lbo"]
        fin, plan = lbo["statements"], lbo["plan"]
        D = "Debt"
        self.sheet(s, "Cash flow statement", "Indirect method. Closing cash feeds the balance sheet.")
        self.header(s, "Cash flow statement", historical=False)
        self.series(s, "net_income", "Net income", kind="link", proj=lambda i, col: self.ref("IS", "net_income", col),
                    expected=fin["net_income"])
        self.series(s, "da", "Depreciation and amortisation", kind="link", proj=lambda i, col: self.ref("IS", "da", col))
        self.series(s, "pik", "PIK interest (non-cash)", kind="link", proj=lambda i, col: self.ref(D, "pik_interest", col),
                    expected=fin["pik_interest"])
        self.series(s, "fee_amort", "Financing fee amortisation (non-cash)", kind="link",
                    proj=lambda i, col: self.ref(D, "fee_amort", col), expected=fin["fee_amortisation"])
        self.series(s, "nwc_change", "(Increase) / decrease in working capital",
                    proj=lambda i, col: f"-({self.ref('BS', 'nwc', col)}-{self.ref('BS', 'nwc', col - 1)})",
                    expected=[-x for x in plan["delta_nwc"]])
        self.series(s, "cfo", "Cash flow from operations", kind="total",
                    proj=lambda i, col: "+".join(self.ref(s, k, col) for k in ("net_income", "da", "pik", "fee_amort",
                                                                                 "nwc_change")),
                    expected=fin["cfo"])
        self.series(s, "capex", "Capital expenditure",
                    proj=lambda i, col: f"-{self.ref('IS', 'revenue', col)}*{self.ref('Inputs', 'live_capex_pct', col)}",
                    expected=[-x for x in plan["capex"]])
        self.series(s, "cfi", "Cash flow from investing", kind="total", proj=lambda i, col: self.ref(s, "capex", col),
                    expected=fin["cfi"])
        self.series(s, "revolver", "Revolver draw / (repayment)", kind="link",
                    proj=lambda i, col: self.ref(D, "rev_draw", col), expected=fin["revolver_draw"])
        self.series(s, "mandatory", "Scheduled debt repayment", kind="link",
                    proj=lambda i, col: f"-{self.ref(D, 'mandatory', col)}", expected=[-x for x in fin["mandatory"]])
        self.series(s, "prepayment", "Cash sweep prepayment", kind="link",
                    proj=lambda i, col: f"-{self.ref(D, 'prepayment', col)}", expected=[-x for x in fin["prepayment"]])
        self.series(s, "cff", "Cash flow from financing", kind="total",
                    proj=lambda i, col: "+".join(self.ref(s, k, col) for k in ("revolver", "mandatory", "prepayment")),
                    expected=fin["cff"])
        self.series(s, "net_change", "Net change in cash", kind="total",
                    proj=lambda i, col: "+".join(self.ref(s, k, col) for k in ("cfo", "cfi", "cff")))
        self.series(s, "opening_cash", "Opening cash", kind="link", proj=lambda i, col: self.ref("BS", "cash", col - 1))
        self.series(s, "closing_cash", "Closing cash", kind="key",
                    proj=lambda i, col: f"{self.ref(s, 'opening_cash', col)}+{self.ref(s, 'net_change', col)}",
                    expected=fin["cash"])

    def debt(self):
        c, s = self.case, "Debt"
        lbo = self.results["lbo"]
        fin = lbo["statements"]
        I = "Inputs"
        self.sheet(s, "Debt schedule and cash sweep", "Interest accrues on opening balances (no circularity). The "
                                                     "revolver funds shortfalls; excess cash repays sweepable debt in order.")
        self.header(s, "Cash available for debt service", historical=False)
        self.series(s, "opening_cash", "Opening cash", kind="link", proj=lambda i, col: self.ref("BS", "cash", col - 1))
        self.series(s, "cfo", "Cash flow from operations", kind="link", proj=lambda i, col: self.ref("CF", "cfo", col))
        self.series(s, "cfi", "Cash flow from investing", kind="link", proj=lambda i, col: self.ref("CF", "cfi", col))
        self.series(s, "mandatory", "Scheduled repayments",
                    proj=lambda i, col: "+".join(self.ref(s, f"t{k}_mandatory", col) for k in range(len(c.tranches))),
                    expected=fin["mandatory"])
        self.series(s, "min_cash", "Minimum cash", proj=lambda i, col: "Min_Cash")
        self.series(s, "available", "Cash available after scheduled debt service", kind="total",
                    proj=lambda i, col: (f"{self.ref(s, 'opening_cash', col)}+{self.ref(s, 'cfo', col)}+"
                                         f"{self.ref(s, 'cfi', col)}-{self.ref(s, 'mandatory', col)}-"
                                         f"{self.ref(s, 'min_cash', col)}"), expected=fin["cash_available"])
        self.series(s, "rev_draw", "Revolver draw / (repayment)",
                    proj=lambda i, col: (f"MIN(MAX(-{self.ref(s, 'available', col)},-{self.ref(s, 'rev_opening', col)}),"
                                         f"Rev_Commitment-{self.ref(s, 'rev_opening', col)})"),
                    expected=fin["revolver_draw"])
        self.series(s, "after_revolver", "Cash after revolver",
                    proj=lambda i, col: f"{self.ref(s, 'available', col)}+{self.ref(s, 'rev_draw', col)}")
        self.series(s, "sweep_pool", "Cash available for the sweep", kind="total",
                    proj=lambda i, col: f"MAX(0,{self.ref(s, 'after_revolver', col)})*Sweep_Pct",
                    expected=fin["sweep_pool"])

        self.section(s, "Revolver")
        self.series(s, "rev_opening", "Opening balance", kind="link", proj=lambda i, col: self.ref("BS", "revolver", col - 1))
        self.series(s, "rev_flow", "Draw / (repayment)", proj=lambda i, col: self.ref(s, "rev_draw", col))
        self.series(s, "rev_closing", "Closing balance", kind="total",
                    proj=lambda i, col: f"{self.ref(s, 'rev_opening', col)}+{self.ref(s, 'rev_flow', col)}",
                    expected=fin["revolver"])
        self.series(s, "rev_interest", "Interest", proj=lambda i, col: f"{self.ref(s, 'rev_opening', col)}*Rev_Rate",
                    expected=fin["revolver_interest"])
        self.series(s, "rev_fee", "Undrawn commitment fee",
                    proj=lambda i, col: f"(Rev_Commitment-{self.ref(s, 'rev_opening', col)})*Rev_Undrawn_Fee",
                    expected=fin["undrawn_fee"])

        for k, t in enumerate(c.tranches):
            sched = fin["tranches"][k]
            self.section(s, f"{t.name} ({t.kind})")
            self.series(s, f"t{k}_opening", "Opening balance", kind="link",
                        proj=lambda i, col, k=k: self.ref("BS", f"t{k}", col - 1), expected=sched["opening"])
            self.series(s, f"t{k}_cash", "Cash interest",
                        proj=lambda i, col, k=k: f"{self.ref(s, f't{k}_opening', col)}*{self.ref(I, f't{k}_cash')}",
                        expected=sched["cash_interest"])
            self.series(s, f"t{k}_pik", "PIK interest",
                        proj=lambda i, col, k=k: f"{self.ref(s, f't{k}_opening', col)}*{self.ref(I, f't{k}_pik')}",
                        expected=sched["pik"])
            self.series(s, f"t{k}_mandatory", "Scheduled repayment",
                        proj=lambda i, col, k=k: (f"MIN({self.ref(s, f't{k}_opening', col)}+{self.ref(s, f't{k}_pik', col)},"
                                                  f"{self.ref(I, f't{k}_amort', col)}*{self.ref('Deal', f't{k}_principal')})"),
                        expected=sched["mandatory"])
            self.series(s, f"t{k}_pool", "Sweep cash still available",
                        proj=(lambda i, col: self.ref(s, "sweep_pool", col)) if k == 0 else
                        (lambda i, col, k=k: f"{self.ref(s, f't{k - 1}_pool', col)}-{self.ref(s, f't{k - 1}_prepay', col)}"))
            self.series(s, f"t{k}_prepay", "Sweep prepayment",
                        proj=lambda i, col, k=k: (f"IF({self.ref(I, f't{k}_sweep')}=1,MIN({self.ref(s, f't{k}_pool', col)},"
                                                  f"{self.ref(s, f't{k}_opening', col)}+{self.ref(s, f't{k}_pik', col)}-"
                                                  f"{self.ref(s, f't{k}_mandatory', col)}),0)"),
                        expected=sched["prepayment"])
            self.series(s, f"t{k}_closing", "Closing balance", kind="total",
                        proj=lambda i, col, k=k: (f"{self.ref(s, f't{k}_opening', col)}+{self.ref(s, f't{k}_pik', col)}-"
                                                  f"{self.ref(s, f't{k}_mandatory', col)}-{self.ref(s, f't{k}_prepay', col)}"),
                        expected=sched["closing"])

        ks = range(len(c.tranches))
        self.section(s, "Interest summary")
        self.series(s, "cash_interest", "Cash interest on term debt",
                    proj=lambda i, col: "+".join(self.ref(s, f"t{k}_cash", col) for k in ks), expected=fin["cash_interest"])
        self.series(s, "pik_interest", "PIK interest",
                    proj=lambda i, col: "+".join(self.ref(s, f"t{k}_pik", col) for k in ks), expected=fin["pik_interest"])
        self.series(s, "prepayment", "Total sweep prepayment",
                    proj=lambda i, col: "+".join(self.ref(s, f"t{k}_prepay", col) for k in ks), expected=fin["prepayment"])
        self.series(s, "fee_amort", "Financing fee amortisation",
                    proj=lambda i, col: (f"MIN({self.ref('BS', 'dff', col - 1)},"
                                         f"{self.ref('Deal', 'fin_fees')}/Fee_Amort_Years)"),
                    expected=fin["fee_amortisation"])
        self.series(s, "finance_cost", "Finance cost (to income statement)", kind="total",
                    proj=lambda i, col: "+".join(self.ref(s, k, col) for k in ("cash_interest", "pik_interest",
                                                                                 "rev_interest", "rev_fee", "fee_amort")),
                    expected=fin["finance_cost"])
        self.series(s, "interest_income", "Interest income on opening cash",
                    proj=lambda i, col: f"{self.ref(s, 'opening_cash', col)}*Cash_Yield", expected=fin["interest_income"])

    def deal(self):
        c, s = self.case, "Deal"
        su = self.results["lbo"]["sources_uses"]
        self.sheet(s, "Transaction: sources and uses", f"Assumed close on the {c.historical_years[-1]} balance sheet "
                                                       "date. Sponsor equity is the balancing source.")
        A = column_letter(self.last_hist - 2)
        bs_ref = lambda key: f"BS!${A}${self.row_of('BS', key)}"  # noqa: E731
        self.section(s, "Purchase price", 0)
        self.scalar(s, "offer_price", "Offer price per share", lambda: "Unaffected_Price*(1+Offer_Premium)",
                    fmt="price", kind="total", expected=su["offer_price"])
        self.scalar(s, "equity_purchase", "Equity purchase price", lambda: f"{self.ref(s, 'offer_price')}*Diluted_Shares",
                    expected=su["equity_purchase"])
        self.scalar(s, "old_debt", "Plus: existing debt", lambda: bs_ref("old_debt"), kind="link")
        self.scalar(s, "old_cash", "Less: existing cash", lambda: bs_ref("cash"), kind="link")
        self.scalar(s, "entry_ev", "Entry enterprise value", kind="total",
                    content=lambda: f"{self.ref(s, 'equity_purchase')}+{self.ref(s, 'old_debt')}-{self.ref(s, 'old_cash')}",
                    expected=su["entry_ev"])
        self.scalar(s, "ltm_ebitda", f"LTM EBITDA ({c.historical_years[-1]}A)", kind="link",
                    content=lambda: f"IS!${column_letter(self.last_hist)}${self.row_of('IS', 'ebitda')}",
                    expected=su["ltm_ebitda"])
        self.scalar(s, "entry_multiple", "Entry EV / LTM EBITDA", fmt="mult", kind="key",
                    content=lambda: f"{self.ref(s, 'entry_ev')}/{self.ref(s, 'ltm_ebitda')}", expected=su["entry_multiple"])

        self.section(s, "Debt raised")
        for k, t in enumerate(c.tranches):
            self.scalar(s, f"t{k}_principal", t.name,
                        lambda k=k: f"{self.ref('Inputs', f't{k}_multiple')}*Leverage_Scale*{self.ref(s, 'ltm_ebitda')}",
                        expected=su["tranches"][k]["principal"])
        self.scalar(s, "new_debt", "Total debt raised", kind="total",
                    content=lambda: "+".join(self.ref(s, f"t{k}_principal") for k in range(len(c.tranches))),
                    expected=su["new_debt"])
        self.scalar(s, "leverage", "Total debt / LTM EBITDA", fmt="mult",
                    content=lambda: f"{self.ref(s, 'new_debt')}/{self.ref(s, 'ltm_ebitda')}", expected=su["leverage"])
        self.scalar(s, "txn_fees", "Transaction fees", lambda: f"Txn_Fee_Pct*{self.ref(s, 'entry_ev')}",
                    expected=su["transaction_fees"])
        self.scalar(s, "fin_fees", "Financing fees (capitalised, amortised)", lambda: f"Fin_Fee_Pct*{self.ref(s, 'new_debt')}",
                    expected=su["financing_fees"])
        self.scalar(s, "cash_used", "Existing cash used (above minimum cash)",
                    lambda: f"{self.ref(s, 'old_cash')}-Min_Cash", expected=su["sources"]["existing_cash_used"])
        self.scalar(s, "rollover", "Rollover equity", lambda: f"Rollover_Pct*{self.ref(s, 'equity_purchase')}",
                    expected=su["rollover_equity"])

        self.section(s, "Uses")
        uses = (("u_equity", "Purchase of equity", "equity_purchase"), ("u_debt", "Refinance existing debt", "old_debt"),
                ("u_txn", "Transaction fees", "txn_fees"), ("u_fin", "Financing fees", "fin_fees"))
        for key, label, src in uses:
            self.scalar(s, key, label, lambda src=src: self.ref(s, src))
        self.scalar(s, "total_uses", "Total uses", kind="total",
                    content=lambda: "+".join(self.ref(s, k) for k, _, _ in uses), expected=su["total_uses"])
        self.section(s, "Sources")
        source_keys = []
        for k, t in enumerate(c.tranches):
            self.scalar(s, f"s_t{k}", t.name, lambda k=k: self.ref(s, f"t{k}_principal"))
            source_keys.append(f"s_t{k}")
        self.scalar(s, "s_cash", "Existing cash used", lambda: self.ref(s, "cash_used"))
        self.scalar(s, "s_rollover", "Rollover equity", lambda: self.ref(s, "rollover"))
        self.scalar(s, "sponsor_equity", "Sponsor equity (plug)", kind="key",
                    content=lambda: (f"{self.ref(s, 'total_uses')}-{self.ref(s, 'new_debt')}-{self.ref(s, 'rollover')}-"
                                     f"{self.ref(s, 'cash_used')}"), expected=su["sponsor_equity"])
        source_keys += ["s_cash", "s_rollover", "sponsor_equity"]
        self.scalar(s, "total_sources", "Total sources", kind="total",
                    content=lambda: "+".join(self.ref(s, k) for k in source_keys), expected=su["total_sources"])
        self.scalar(s, "su_check", "Sources - uses", lambda: f"{self.ref(s, 'total_sources')}-{self.ref(s, 'total_uses')}",
                    expected=0.0)

        self.section(s, "Equity and goodwill")
        self.scalar(s, "total_equity", "Total equity (sponsor + rollover)",
                    lambda: f"{self.ref(s, 'sponsor_equity')}+{self.ref(s, 'rollover')}", expected=su["total_equity"])
        self.scalar(s, "equity_contribution", "Equity contribution (% of capitalisation)", fmt="pct",
                    content=lambda: f"{self.ref(s, 'total_equity')}/({self.ref(s, 'total_equity')}+{self.ref(s, 'new_debt')})",
                    expected=su["equity_contribution"])
        self.scalar(s, "nd_close", "Net debt at close", lambda: f"{self.ref(s, 'new_debt')}-Min_Cash",
                    expected=su["net_debt_at_close"])
        self.scalar(s, "goodwill", "Goodwill (equity price - book equity; no PPA write-ups)",
                    lambda: f"{self.ref(s, 'equity_purchase')}-{bs_ref('equity')}",
                    expected=self.results["lbo"]["pro_forma"]["goodwill"])

    def returns(self):
        c, s = self.case, "Returns"
        lbo = self.results["lbo"]
        r, cov = lbo["returns"], lbo["covenants"]
        self.sheet(s, "Returns, value creation and covenants", "Exit at the live multiple in the holding-period year.")
        P = self.proj_cols
        self.section(s, "Exit", 0)
        self.scalar(s, "exit_multiple", "Exit EV / EBITDA", lambda: "Exit_Multiple", fmt="mult", kind="link",
                    expected=r["exit_multiple"])
        self.scalar(s, "exit_ebitda", "Exit-year EBITDA", lambda: f"INDEX({self.span('IS', 'ebitda', P)},Holding_Years)",
                    expected=r["exit_ebitda"])
        self.scalar(s, "exit_ev", "Exit enterprise value",
                    lambda: f"{self.ref(s, 'exit_multiple')}*{self.ref(s, 'exit_ebitda')}", expected=r["exit_ev"])
        self.scalar(s, "exit_costs", "Exit costs", lambda: f"Exit_Cost_Pct*{self.ref(s, 'exit_ev')}",
                    expected=r["exit_costs"])
        self.scalar(s, "exit_nd", "Net debt at exit", lambda: f"INDEX({self.span('BS', 'net_debt', P)},Holding_Years)",
                    expected=r["exit_net_debt"])
        self.scalar(s, "exit_equity", "Equity value at exit", kind="total",
                    content=lambda: f"{self.ref(s, 'exit_ev')}-{self.ref(s, 'exit_costs')}-{self.ref(s, 'exit_nd')}",
                    expected=r["exit_equity"])
        self.scalar(s, "invested", "Equity invested (sponsor + rollover)", lambda: self.ref("Deal", "total_equity"),
                    kind="link")
        self.scalar(s, "mip", "Management incentive pool",
                    lambda: f"MIP_Pct*MAX(0,{self.ref(s, 'exit_equity')}-{self.ref(s, 'invested')})",
                    expected=r["management_incentive"])
        self.scalar(s, "share", "Sponsor ownership", fmt="pct",
                    content=lambda: f"{self.ref('Deal', 'sponsor_equity')}/{self.ref(s, 'invested')}",
                    expected=r["sponsor_share"])
        self.scalar(s, "proceeds", "Sponsor proceeds", kind="total",
                    content=lambda: f"MAX(0,{self.ref(s, 'exit_equity')}-{self.ref(s, 'mip')})*{self.ref(s, 'share')}",
                    expected=r["sponsor_proceeds"])
        self.scalar(s, "moic", "Sponsor MOIC", fmt="mult2", kind="key",
                    content=lambda: f"{self.ref(s, 'proceeds')}/{self.ref('Deal', 'sponsor_equity')}", expected=r["moic"])
        self.skip(s)
        self.header(s, "Sponsor cash flows", historical=False, close_label="Close")
        flows = self.series(s, "flows", "Sponsor equity cash flow",
                            first=(lambda: f"-{self.ref('Deal', 'sponsor_equity')}", "calc"),
                            proj=lambda i, col: f"IF({i + 1}=Holding_Years,{self.ref(s, 'proceeds')},0)")
        del flows
        self.scalar(s, "irr", "Sponsor IRR", fmt="pct", kind="key",
                    content=lambda: (f"IF({self.ref(s, 'proceeds')}>0,IRR({self.span(s, 'flows', [self.last_hist] + P)}),-1)"),
                    expected=r["irr"])

        self.section(s, "Value-creation bridge (total equity)")
        b = r["bridge"]
        self.scalar(s, "b_growth", "EBITDA growth at the entry multiple",
                    lambda: f"({self.ref(s, 'exit_ebitda')}-{self.ref('Deal', 'ltm_ebitda')})*{self.ref('Deal', 'entry_multiple')}",
                    expected=b["ebitda_growth"])
        self.scalar(s, "b_multiple", "Multiple expansion / (contraction)",
                    lambda: f"({self.ref(s, 'exit_multiple')}-{self.ref('Deal', 'entry_multiple')})*{self.ref(s, 'exit_ebitda')}",
                    expected=b["multiple_change"])
        self.scalar(s, "b_delever", "Net debt paydown", lambda: f"{self.ref('Deal', 'nd_close')}-{self.ref(s, 'exit_nd')}",
                    expected=b["deleveraging"])
        self.scalar(s, "b_fees", "Fees and exit costs",
                    lambda: f"-({self.ref('Deal', 'txn_fees')}+{self.ref('Deal', 'fin_fees')}+{self.ref(s, 'exit_costs')})",
                    expected=b["fees_and_costs"])
        self.scalar(s, "b_total", "Total equity value created", kind="total",
                    content=lambda: "+".join(self.ref(s, k) for k in ("b_growth", "b_multiple", "b_delever", "b_fees")),
                    expected=b["total_equity_gain"])
        self.scalar(s, "b_check", "Check: bridge - (exit equity - invested)",
                    lambda: f"{self.ref(s, 'b_total')}-({self.ref(s, 'exit_equity')}-{self.ref(s, 'invested')})",
                    expected=0.0)

        self.skip(s)
        self.header(s, "Returns by exit year (live exit multiple)", historical=False)
        by_year = lbo["returns_by_exit_year"]
        self.series(s, "year_n", "Years held", proj=[float(i + 1) for i in range(self.n)], fmt="int")
        self.series(s, "y_ev", "Exit EV", proj=lambda i, col: f"Exit_Multiple*{self.ref('IS', 'ebitda', col)}")
        self.series(s, "y_equity", "Exit equity",
                    proj=lambda i, col: f"{self.ref(s, 'y_ev', col)}*(1-Exit_Cost_Pct)-{self.ref('BS', 'net_debt', col)}")
        self.series(s, "y_proceeds", "Sponsor proceeds",
                    proj=lambda i, col: (f"MAX(0,{self.ref(s, 'y_equity', col)}-MIP_Pct*MAX(0,{self.ref(s, 'y_equity', col)}-"
                                         f"{self.ref(s, 'invested')}))*{self.ref(s, 'share')}"))
        self.series(s, "y_moic", "MOIC", fmt="mult2",
                    proj=lambda i, col: f"{self.ref(s, 'y_proceeds', col)}/{self.ref('Deal', 'sponsor_equity')}",
                    expected=[x["moic"] for x in by_year])
        self.series(s, "y_irr", "IRR", fmt="pct", kind="total",
                    proj=lambda i, col: (f"IF({self.ref(s, 'y_proceeds', col)}>0,{self.ref(s, 'y_moic', col)}^"
                                         f"(1/{self.ref(s, 'year_n', col)})-1,-1)"),
                    expected=[x["irr"] for x in by_year])

        self.skip(s)
        self.header(s, "Covenant tests", historical=False)
        self.series(s, "c_ebitda", "EBITDA", kind="link", proj=lambda i, col: self.ref("IS", "ebitda", col))
        self.series(s, "c_nd", "Net debt", kind="link", proj=lambda i, col: self.ref("BS", "net_debt", col))
        self.series(s, "c_lev", "Net debt / EBITDA", fmt="mult2",
                    proj=lambda i, col: f"{self.ref(s, 'c_nd', col)}/{self.ref(s, 'c_ebitda', col)}",
                    expected=cov["net_leverage"])
        self.series(s, "c_lev_max", "Maximum", fmt="mult2", kind="link",
                    proj=lambda i, col: self.ref("Inputs", "max_leverage", col))
        self.series(s, "c_ci", "Cash interest (term debt + revolver + fees)",
                    proj=lambda i, col: (f"{self.ref('Debt', 'cash_interest', col)}+{self.ref('Debt', 'rev_interest', col)}+"
                                         f"{self.ref('Debt', 'rev_fee', col)}"))
        self.series(s, "c_icr", "Interest cover (EBITDA / cash interest)", fmt="mult2",
                    proj=lambda i, col: f"{self.ref(s, 'c_ebitda', col)}/{self.ref(s, 'c_ci', col)}",
                    expected=cov["interest_cover"] if None not in cov["interest_cover"] else None)
        self.series(s, "c_ds", "Debt service (cash interest + scheduled repayment)",
                    proj=lambda i, col: f"{self.ref(s, 'c_ci', col)}+{self.ref('Debt', 'mandatory', col)}")
        self.series(s, "c_dscr", "DSCR ((EBITDA - capex - tax) / debt service)", fmt="mult2",
                    proj=lambda i, col: (f"({self.ref(s, 'c_ebitda', col)}+{self.ref('CF', 'capex', col)}-"
                                         f"{self.ref('IS', 'tax', col)})/{self.ref(s, 'c_ds', col)}"),
                    expected=cov["dscr"] if None not in cov["dscr"] else None)
        self.series(s, "c_cushion", "EBITDA cushion before the tightest covenant breaks", fmt="pct", kind="total",
                    proj=lambda i, col: (f"MIN(1-{self.ref(s, 'c_nd', col)}/({self.ref(s, 'c_lev_max', col)}*"
                                         f"{self.ref(s, 'c_ebitda', col)}),1-Min_ICR*{self.ref(s, 'c_ci', col)}/"
                                         f"{self.ref(s, 'c_ebitda', col)},1-(Min_DSCR*{self.ref(s, 'c_ds', col)}-"
                                         f"{self.ref('CF', 'capex', col)}+{self.ref('IS', 'tax', col)})/"
                                         f"{self.ref(s, 'c_ebitda', col)})"),
                    expected=cov["ebitda_cushion"])
        self.series(s, "c_breach", "Breach flag (1 = any covenant or liquidity test fails)", fmt="int", kind="total",
                    proj=lambda i, col: (f"IF(OR({self.ref(s, 'c_lev', col)}>{self.ref(s, 'c_lev_max', col)},"
                                         f"{self.ref(s, 'c_icr', col)}<Min_ICR,{self.ref(s, 'c_dscr', col)}<Min_DSCR,"
                                         f"{self.ref('Debt', 'after_revolver', col)}<0),1,0)"),
                    expected=[1.0 if b else 0.0 for b in cov["breaches"]])

    def wacc(self):
        c, s = self.case, "WACC"
        w = self.results["wacc"]
        v = c.valuation
        self.sheet(s, "Cost of capital (INR)", "CAPM with peer betas unlevered and relevered (Hamada).")
        ws = self.wb.sheet(s)
        row = self.take_row(s)
        hstyle = self.style("header", "general", align="right")
        for col, text in ((LABEL, "Peer"), (VALUE, "Levered beta"), (VALUE + 1, "Debt / equity"),
                          (VALUE + 2, "Tax rate"), (VALUE + 3, "Unlevered beta")):
            ws.set(row, col, text, style=hstyle if col != LABEL else self.style("header", "general"))
        ws.set(row, UNIT, None, style=hstyle)
        first = None
        for k, peer in enumerate(v["peer_betas"]):
            row = self.take_row(s)
            first = first or row
            self.rows[(s, f"peer{k}")] = row
            ws.set(row, LABEL, peer["name"])
            ws.set(row, VALUE, peer["levered_beta"], style=self.style("input", "num2"))
            ws.set(row, VALUE + 1, peer["debt_to_equity"], style=self.style("input", "num2"))
            ws.set(row, VALUE + 2, peer["tax_rate"], style=self.style("input", "pct2"))
            self._put(s, row, VALUE + 3, (lambda r=row: f"D{r}/(1+(1-F{r})*E{r})"), self.style("calc", "num2"),
                      w["peers"][k]["unlevered_beta"])
        last = row
        self.skip(s)
        self.scalar(s, "beta_u", "Median unlevered beta", lambda first=first, last=last: f"MEDIAN(G{first}:G{last})", fmt="num2",
                    expected=w["unlevered_beta"])
        self.scalar(s, "target_dc", "Target debt / capital", v["target_debt_to_capital"], fmt="pct", name="Target_DC")
        self.scalar(s, "de", "Target debt / equity", lambda: "Target_DC/(1-Target_DC)", fmt="num2",
                    expected=w["target_debt_to_equity"])
        self.scalar(s, "beta_l", "Relevered beta", lambda: f"{self.ref(s, 'beta_u')}*(1+(1-Tax_Rate)*{self.ref(s, 'de')})",
                    fmt="num2", expected=w["relevered_beta"])
        self.scalar(s, "rf", "Risk-free rate (10-year G-sec)", v["risk_free"], fmt="pct2", name="Risk_Free")
        self.scalar(s, "erp", "Equity risk premium (India)", v["equity_risk_premium"], fmt="pct2",
                    name="Equity_Risk_Premium")
        self.scalar(s, "size", "Size / company-specific premium", v["size_premium"], fmt="pct2", name="Size_Premium")
        self.scalar(s, "ke", "Cost of equity",
                    lambda: f"Risk_Free+{self.ref(s, 'beta_l')}*Equity_Risk_Premium+Size_Premium",
                    fmt="pct2", kind="total", expected=w["cost_of_equity"])
        self.scalar(s, "kd", "Pre-tax cost of debt", v["pre_tax_cost_of_debt"], fmt="pct2", name="Kd_Pre_Tax")
        self.scalar(s, "kd_after", "After-tax cost of debt", lambda: "Kd_Pre_Tax*(1-Tax_Rate)", fmt="pct2",
                    expected=w["after_tax_cost_of_debt"])
        self.scalar(s, "wacc", "WACC", lambda: f"(1-Target_DC)*{self.ref(s, 'ke')}+Target_DC*{self.ref(s, 'kd_after')}",
                    fmt="pct2", kind="key", name="WACC_Rate", expected=w["wacc"])

    def dcf(self):
        c, s = self.case, "DCF"
        d = self.results["dcf"]
        v = c.valuation
        self.sheet(s, "Discounted cash flow (unlevered, standalone)",
                   "FCFF follows the live operating case; the deal's capital structure does not affect it.")
        self.section(s, "Assumptions", 0)
        self.scalar(s, "tg", "Terminal growth (nominal INR)", v["terminal_growth"], fmt="pct2", name="Terminal_Growth")
        self.scalar(s, "exit", "Terminal EV / EBITDA (cross-check)", v["exit_multiple"], fmt="mult", name="DCF_Exit_Multiple")
        self.scalar(s, "mid", "Mid-year convention (1 = on)", 1 if v["mid_year"] else 0, fmt="int", name="Mid_Year")
        self.skip(s)
        self.header(s, "Free cash flow to the firm", historical=False)
        self.series(s, "ebit", "EBIT", kind="link", proj=lambda i, col: self.ref("IS", "ebit", col))
        self.series(s, "nopat", "NOPAT (EBIT x (1 - tax))", proj=lambda i, col: f"{self.ref(s, 'ebit', col)}*(1-Tax_Rate)",
                    expected=d["plan"]["nopat"])
        self.series(s, "da", "Plus: D&A", kind="link", proj=lambda i, col: self.ref("IS", "da", col))
        self.series(s, "capex", "Less: capex", kind="link", proj=lambda i, col: self.ref("CF", "capex", col))
        self.series(s, "nwc", "Less: increase in working capital", kind="link",
                    proj=lambda i, col: self.ref("CF", "nwc_change", col))
        self.series(s, "fcff", "Unlevered free cash flow", kind="total",
                    proj=lambda i, col: "+".join(self.ref(s, k, col) for k in ("nopat", "da", "capex", "nwc")),
                    expected=d["fcff"])
        self.series(s, "year", "Year", proj=[float(i + 1) for i in range(self.n)], fmt="int")
        self.series(s, "period", "Discount period", fmt="num2",
                    proj=lambda i, col: f"{self.ref(s, 'year', col)}-0.5*Mid_Year", expected=d["periods"])
        self.series(s, "factor", "Discount factor", fmt="num2",
                    proj=lambda i, col: f"1/(1+WACC_Rate)^{self.ref(s, 'period', col)}", expected=d["discount_factors"])
        self.series(s, "pv", "Present value", kind="total",
                    proj=lambda i, col: f"{self.ref(s, 'fcff', col)}*{self.ref(s, 'factor', col)}", expected=d["pv_fcff"])
        P, last = self.proj_cols, self.proj_cols[-1]
        n = float(self.n)
        self.section(s, "Valuation")
        self.scalar(s, "sum_pv", "Sum of PV of FCFF", lambda: f"SUM({self.span(s, 'pv', P)})", expected=d["sum_pv_fcff"])
        self.scalar(s, "g_tv", "Terminal value: Gordon growth",
                    lambda: f"{self.ref(s, 'fcff', last, absolute=True)}*(1+Terminal_Growth)/(WACC_Rate-Terminal_Growth)",
                    expected=d["gordon_terminal_value"])
        self.scalar(s, "g_pv", "PV of terminal value (Gordon)",
                    lambda: f"{self.ref(s, 'g_tv')}/(1+WACC_Rate)^({n}-0.5*Mid_Year)", expected=d["gordon_terminal_pv"])
        self.scalar(s, "x_tv", "Terminal value: exit multiple",
                    lambda: f"DCF_Exit_Multiple*{self.ref('IS', 'ebitda', last, absolute=True)}",
                    expected=d["exit_terminal_value"])
        self.scalar(s, "x_pv", "PV of terminal value (exit multiple)",
                    lambda: f"{self.ref(s, 'x_tv')}/(1+WACC_Rate)^{n}", expected=d["exit_terminal_pv"])
        A = column_letter(self.last_hist - 2)
        self.scalar(s, "net_debt", "Net debt (standalone, pre-deal)",
                    lambda: f"BS!${A}${self.row_of('BS', 'old_debt')}-BS!${A}${self.row_of('BS', 'cash')}",
                    kind="link", expected=d["net_debt"])
        for method, key in (("gordon", "g"), ("exit", "x")):
            label = "Gordon growth" if method == "gordon" else "exit multiple"
            self.scalar(s, f"ev_{method}", f"Enterprise value ({label})",
                        lambda key=key: f"{self.ref(s, 'sum_pv')}+{self.ref(s, f'{key}_pv')}", kind="total",
                        expected=d[method]["enterprise_value"])
            self.scalar(s, f"eq_{method}", f"Equity value ({label})",
                        lambda method=method: f"{self.ref(s, f'ev_{method}')}-{self.ref(s, 'net_debt')}",
                        expected=d[method]["equity_value"])
            self.scalar(s, f"per_share_{method}", f"Value per share ({label})", fmt="price", kind="key",
                        content=lambda method=method: f"{self.ref(s, f'eq_{method}')}/Diluted_Shares",
                        expected=d[method]["value_per_share"])
            self.scalar(s, f"tv_share_{method}", f"Terminal value share of EV ({label})", fmt="pct",
                        content=lambda method=method, key=key: f"{self.ref(s, f'{key}_pv')}/{self.ref(s, f'ev_{method}')}",
                        expected=d[method]["terminal_share"])
        self.section(s, "Cross-checks")
        self.scalar(s, "implied_multiple", "Exit multiple implied by the Gordon value", fmt="mult",
                    content=lambda: (f"{self.ref(s, 'g_tv')}*(1+WACC_Rate)^(0.5*Mid_Year)/"
                                     f"{self.ref('IS', 'ebitda', last, absolute=True)}"),
                    expected=d["implied_exit_multiple"])
        self.scalar(s, "implied_growth", "Perpetual growth implied by the exit multiple", fmt="pct2",
                    content=lambda: (f"({self.ref(s, 'x_tv')}/(1+WACC_Rate)^(0.5*Mid_Year)*WACC_Rate-"
                                     f"{self.ref(s, 'fcff', last, absolute=True)})/({self.ref(s, 'x_tv')}/(1+WACC_Rate)^"
                                     f"(0.5*Mid_Year)+{self.ref(s, 'fcff', last, absolute=True)})"),
                    expected=d["implied_terminal_growth"])
        self.scalar(s, "vs_unaffected", "Gordon value vs unaffected price", fmt="pct",
                    content=lambda: f"{self.ref(s, 'per_share_gordon')}/Unaffected_Price-1")
        self.scalar(s, "vs_offer", "Gordon value vs offer price", fmt="pct",
                    content=lambda: f"{self.ref(s, 'per_share_gordon')}/{self.ref('Deal', 'offer_price')}-1")

    def comps(self):
        c, s = self.case, "Comps"
        comps, prec = self.results["comps"], self.results["precedents"]
        self.sheet(s, "Trading comparables and precedent transactions",
                   f"Trading multiples on {comps['basis']} estimates; precedents on {prec['basis']} EBITDA.")
        ws = self.wb.sheet(s)
        columns = [("Market cap", "num0"), ("Net debt", "num0"), ("EV", "num0"), ("Revenue", "num0"),
                   ("EBITDA", "num0"), ("Net income", "num0"), ("EV / Revenue", "mult2"), ("EV / EBITDA", "mult"),
                   ("P / E", "mult"), ("Revenue growth", "pct"), ("EBITDA margin", "pct")]
        for k in range(len(columns)):
            ws.widths[VALUE + k] = 12.5
        row = self.take_row(s)
        ws.set(row, LABEL, "Trading comparables", style=self.style("header", "general"))
        ws.set(row, UNIT, None, style=self.style("header", "general"))
        for k, (text, _) in enumerate(columns):
            ws.set(row, VALUE + k, text, style=self.style("header", "general", align="right"))
        first = None
        keys = ["market_cap", "net_debt", None, "revenue", "ebitda", "net_income", None, None, None,
                "revenue_growth", "ebitda_margin"]
        for k, comp in enumerate(comps["rows"]):
            row = self.take_row(s)
            first = first or row
            ws.set(row, LABEL, comp["name"])
            for j, key in enumerate(keys):
                col = VALUE + j
                if key:
                    ws.set(row, col, comp[key], style=self.style("input", columns[j][1]))
            L = lambda j, r=row: f"{column_letter(VALUE + j)}{r}"  # noqa: E731
            self._put(s, row, VALUE + 2, (lambda L=L: f"{L(0)}+{L(1)}"), self.style("calc", "num0"),
                      comp["enterprise_value"])
            self._put(s, row, VALUE + 6, (lambda L=L: f"{L(2)}/{L(3)}"), self.style("calc", "mult2"), comp["ev_revenue"])
            self._put(s, row, VALUE + 7, (lambda L=L: f"{L(2)}/{L(4)}"), self.style("calc", "mult"), comp["ev_ebitda"])
            self._put(s, row, VALUE + 8, (lambda L=L: f"{L(0)}/{L(5)}"), self.style("calc", "mult"), comp["pe"])
        last = row
        stat_keys = {6: "ev_revenue", 7: "ev_ebitda", 8: "pe", 9: "revenue_growth", 10: "ebitda_margin"}
        for label, fn, point in (("Maximum", "MAX({r})", "max"), ("75th percentile", "QUARTILE({r},3)", "q3"),
                                 ("Median", "MEDIAN({r})", "median"), ("Mean", "AVERAGE({r})", "mean"),
                                 ("25th percentile", "QUARTILE({r},1)", "q1"), ("Minimum", "MIN({r})", "min")):
            row = self.take_row(s)
            self.rows[(s, f"stat_{point}")] = row
            ws.set(row, LABEL, label, style=self.styles.get(font="bold"))
            for j, key in stat_keys.items():
                col = column_letter(VALUE + j)
                self._put(s, row, VALUE + j, (lambda fn=fn, col=col, first=first, last=last: fn.format(r=f"{col}{first}:{col}{last}")),
                          self.style("total" if point == "median" else "calc", columns[j][1]),
                          comps["stats"][key][point])
        self.skip(s)
        self.section(s, "Implied value of the target")
        G = column_letter(self.proj_cols[0])
        F = column_letter(self.last_hist)
        A = column_letter(self.last_hist - 2)
        self.scalar(s, "ntm_revenue", f"Target revenue, {comps['basis']}", lambda: f"IS!${G}${self.row_of('IS', 'revenue')}",
                    kind="link", expected=comps["target_metrics"]["revenue"])
        self.scalar(s, "ntm_ebitda", f"Target EBITDA, {comps['basis']}", lambda: f"IS!${G}${self.row_of('IS', 'ebitda')}",
                    kind="link", expected=comps["target_metrics"]["ebitda"])
        self.scalar(s, "ntm_ni", f"Target standalone net income, {comps['basis']} (pre-deal capital structure)",
                    lambda: (f"(IS!${G}${self.row_of('IS', 'ebit')}-IS!${F}${self.row_of('IS', 'finance_cost')}+"
                             f"IS!${F}${self.row_of('IS', 'other_income')})*(1-Tax_Rate)"),
                    expected=comps["target_metrics"]["net_income"])
        self.scalar(s, "standalone_nd", "Standalone net debt",
                    lambda: f"BS!${A}${self.row_of('BS', 'old_debt')}-BS!${A}${self.row_of('BS', 'cash')}", kind="link")
        ws = self.wb.sheet(s)
        row = self.take_row(s, 1)
        for col, text in ((LABEL, "Implied price per share"), (VALUE, "25th pct"), (VALUE + 1, "Median"),
                          (VALUE + 2, "75th pct")):
            ws.set(row, col, text, style=self.style("header", "general", align=None if col == LABEL else "right"))
        ws.set(row, UNIT, None, style=self.style("header", "general"))
        for key, label, metric, enterprise, j in (("ev_revenue", "EV / Revenue", "ntm_revenue", True, 6),
                                                  ("ev_ebitda", "EV / EBITDA", "ntm_ebitda", True, 7),
                                                  ("pe", "P / E", "ntm_ni", False, 8)):
            row = self.take_row(s)
            self.rows[(s, f"implied_{key}")] = row
            ws.set(row, LABEL, label)
            for k, point in enumerate(("q1", "median", "q3")):
                stat = f"${column_letter(VALUE + j)}${self.row_of(s, f'stat_{point}')}"
                self._put(s, row, VALUE + k, (lambda stat=stat, metric=metric, enterprise=enterprise: (
                    f"({stat}*{self.ref(s, metric)}" + (f"-{self.ref(s, 'standalone_nd')}" if enterprise else "")
                    + ")/Diluted_Shares")), self.style("calc", "price"), comps["implied_price"][key][point])

        self.skip(s)
        row = self.take_row(s)
        for col, text in ((LABEL, "Precedent transactions"), (UNIT, "Year"), (VALUE, "EV / LTM EBITDA"),
                          (VALUE + 1, "Premium"), (VALUE + 2, "Acquirer")):
            ws.set(row, col, text, style=self.style("header", "general", align=None if col == LABEL else "right"))
        first = None
        for p in prec["rows"]:
            row = self.take_row(s)
            first = first or row
            ws.set(row, LABEL, p["target"])
            ws.set(row, UNIT, p["year"], style=self.style("input", "general", align="right"))
            ws.set(row, VALUE, p["ev_ebitda"], style=self.style("input", "mult"))
            ws.set(row, VALUE + 1, p["premium"], style=self.style("input", "pct"))
            ws.set(row, VALUE + 2, p["acquirer"], style=self.style("input", "general", align="right"))
        last = row
        for label, fn, point in (("75th percentile", "QUARTILE({r},3)", "q3"), ("Median", "MEDIAN({r})", "median"),
                                 ("25th percentile", "QUARTILE({r},1)", "q1")):
            row = self.take_row(s)
            self.rows[(s, f"p_stat_{point}")] = row
            ws.set(row, LABEL, label, style=self.styles.get(font="bold"))
            for j, (key, fmt) in enumerate((("ev_ebitda", "mult"), ("premium", "pct"))):
                col = column_letter(VALUE + j)
                self._put(s, row, VALUE + j, (lambda fn=fn, col=col, first=first, last=last: fn.format(r=f"{col}{first}:{col}{last}")),
                          self.style("total" if point == "median" else "calc", fmt), prec["stats"][key][point])
        row = self.take_row(s, 1)
        for col, text in ((LABEL, "Implied price per share"), (VALUE, "25th pct"), (VALUE + 1, "Median"),
                          (VALUE + 2, "75th pct")):
            ws.set(row, col, text, style=self.style("header", "general", align=None if col == LABEL else "right"))
        ws.set(row, UNIT, None, style=self.style("header", "general"))
        for key, label, j in (("ev_ebitda", f"EV / LTM EBITDA ({c.historical_years[-1]}A)", 0),
                              ("premium", "Premium to unaffected price", 1)):
            row = self.take_row(s)
            ws.set(row, LABEL, label)
            for k, point in enumerate(("q1", "median", "q3")):
                stat = f"${column_letter(VALUE + j)}${self.row_of(s, f'p_stat_{point}')}"
                content = ((lambda stat=stat: f"({stat}*{self.ref('Deal', 'ltm_ebitda')}-{self.ref(s, 'standalone_nd')})"
                                              "/Diluted_Shares") if key == "ev_ebitda" else
                           (lambda stat=stat: f"Unaffected_Price*(1+{stat})"))
                self._put(s, row, VALUE + k, content, self.style("calc", "price"), prec["implied_price"][key][point])

    def sensitivity(self):
        s = "Sensitivity"
        sens = self.results["sensitivities"]
        self.sheet(s, "Sensitivity tables", "Static values computed by the STOCKEX engine (base case). Re-run "
                                            "`deal-model` after changing inputs.", tab=GREY)
        ws = self.wb.sheet(s)
        ws.widths[LABEL] = 34
        specs = (("irr_entry_exit", "Sponsor IRR: entry vs exit multiple", "mult", "mult", "pct"),
                 ("moic_entry_exit", "Sponsor MOIC: entry vs exit multiple", "mult", "mult", "mult2"),
                 ("irr_leverage_exit", "Sponsor IRR: leverage vs exit multiple", "mult", "mult", "pct"),
                 ("irr_growth_margin", "Sponsor IRR: growth vs margin shift", "pct", "pct", "pct"),
                 ("dcf_wacc_growth", "DCF value per share: WACC vs terminal growth", "pct2", "pct2", "price"))
        for key, title, row_fmt, col_fmt, fmt in specs:
            grid = sens[key]
            self.section(s, title)
            row = self.take_row(s)
            ws.set(row, LABEL, f"{grid['row_label']} (rows) / {grid['col_label']} (columns)",
                   style=self.style("note", "general"))
            row = self.take_row(s)
            ws.set(row, UNIT, None, style=self.style("header", "general"))
            ws.set(row, LABEL, None, style=self.style("header", "general"))
            for j, value in enumerate(grid["cols"]):
                ws.set(row, VALUE + j, value, style=self.style("header", col_fmt, align="right"))
            mid = len(grid["rows"]) // 2
            for i, value in enumerate(grid["rows"]):
                row = self.take_row(s)
                ws.set(row, UNIT, value, style=self.style("bold", row_fmt))
                for j, cell in enumerate(grid["values"][i]):
                    kind = "key" if (i == mid and j == len(grid["cols"]) // 2) else "calc"
                    ws.set(row, VALUE + j, cell if cell is not None else "n/a", style=self.style(kind, fmt))
            self.skip(s)

    def football(self):
        s = "Football"
        r = self.results
        self.sheet(s, "Valuation football field (per share)", "Static values from the STOCKEX engine.", tab=GREY)
        ws = self.wb.sheet(s)
        ws.widths[LABEL] = 52
        row = self.take_row(s)
        for col, text in ((LABEL, "Method"), (VALUE, "Low"), (VALUE + 1, "High"), (VALUE + 2, "Mid")):
            ws.set(row, col, text, style=self.style("header", "general", align=None if col == LABEL else "right"))
        ws.set(row, UNIT, None, style=self.style("header", "general"))
        for bar in r["football_field"]:
            row = self.take_row(s)
            ws.set(row, LABEL, bar["method"])
            ws.set(row, VALUE, bar["low"], style=self.style("calc", "price"))
            ws.set(row, VALUE + 1, bar["high"], style=self.style("calc", "price"))
            ws.set(row, VALUE + 2, (bar["low"] + bar["high"]) / 2, style=self.style("calc", "price"))
        self.skip(s)
        bids = r["breakevens"]
        for label, value in (("Unaffected price", self.case.market["unaffected_price"]),
                             ("Offer price", bids["offer_price"]),
                             ("Maximum bid (lower of base-case hurdle IRR and downside 1.0x)", bids["max_bid"])):
            row = self.take_row(s)
            ws.set(row, LABEL, label, style=self.styles.get(font="bold"))
            ws.set(row, VALUE, value if value is not None else "n/a", style=self.style("key", "price"))

    def checks(self):
        s = "Checks"
        self.sheet(s, "Model integrity checks", "Every check must be zero. The overall flag feeds the cover.", tab=ORANGE)
        self.header(s, "Per-year checks", historical=False)
        self.series(s, "bs", "Balance sheet balances (assets - claims)", proj=lambda i, col: self.ref("BS", "check", col),
                    kind="link", expected=[0.0] * self.n)
        self.series(s, "cash", "Cash ties to the sweep (BS cash - (min cash + cash after revolver - prepayments))",
                    proj=lambda i, col: (f"{self.ref('BS', 'cash', col)}-(Min_Cash+{self.ref('Debt', 'after_revolver', col)}-"
                                         f"{self.ref('Debt', 'prepayment', col)})"), expected=[0.0] * self.n)
        self.series(s, "revolver", "Revolver above commitment",
                    proj=lambda i, col: f"MAX(0,{self.ref('Debt', 'rev_closing', col)}-Rev_Commitment)",
                    expected=[0.0] * self.n)
        self.series(s, "liquidity", "Liquidity shortfall flag (cash below minimum after the revolver)", fmt="int",
                    proj=lambda i, col: f"IF({self.ref('Debt', 'after_revolver', col)}<0,1,0)")
        P = self.proj_cols
        self.section(s, "Transaction checks")
        self.scalar(s, "su", "Sources - uses", lambda: self.ref("Deal", "su_check"), kind="link", expected=0.0)
        PF = column_letter(self.last_hist)
        self.scalar(s, "pf", "Pro forma balance sheet balances",
                    lambda: f"BS!${PF}${self.row_of('BS', 'check')}", kind="link", expected=0.0)
        self.scalar(s, "bridge", "Value-creation bridge reconciles", lambda: self.ref("Returns", "b_check"), kind="link",
                    expected=0.0)
        self.scalar(s, "overall", "Overall", kind="key", fmt="general", content=lambda: (
            "IF(AND(" + ",".join([f"MAX({self.span(s, k, P)})<0.001" for k in ("bs", "cash", "revolver")]
                                 + [f"MIN({self.span(s, k, P)})>-0.001" for k in ("bs", "cash")]
                                 + [f"ABS({self.ref(s, k)})<0.001" for k in ("su", "pf", "bridge")])
            + '),"ALL CHECKS PASS","CHECK FAILURE")'))


def build_workbook(case, results) -> tuple[Workbook, dict]:
    """Return the workbook and the engine expectations {(sheet, row, col): value} for the base case."""
    builder = _Builder(case, results)
    workbook = builder.build()
    return workbook, builder.expect
