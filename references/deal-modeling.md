# Deal modelling: LBO, DCF and comps for Indian companies

`stockex/deals/` turns one deal case (a JSON file) into the outputs a private equity deal team takes to an investment committee:
- an Excel model with live formulas;
- an IC memo in Markdown and HTML;
- `results.json` with every number behind both.

```bash
python -m stockex.cli deal-model examples/deals/project-saffron.json --out deal-output/
```

The committed example output is in [examples/deals/project-saffron/](../examples/deals/project-saffron/ic-memo.md). Project Saffron is a fictional take-private of an NSE-listed regional packaged-foods company. All of its figures are invented.

## What gets built

| Layer | Contents |
| --- | --- |
| Three statements | Income statement, balance sheet and cash flow, projected from drivers: growth, gross margin, opex %, D&A %, capex % and working-capital days. The balance sheet must balance in every year, and cash must tie to the cash flow statement. |
| Transaction | Offer price from the premium to the unaffected price. Entry EV, sources and uses (sponsor equity is the plug), promoter rollover, transaction fees, and financing fees capitalised and amortised. Pro forma balance sheet with goodwill. |
| Debt | OpCo amortising term loan, HoldCo NCDs with cash and PIK coupons, and a revolver that funds shortfalls below minimum cash. The cash sweep pays down tranches in priority order after the revolver is repaid. Interest accrues on opening balances, so there is no circular reference. |
| Tax | 25.17% (s.115BAA). The interest-limitation cap (30% of tax EBITDA) applies to caught debt, with carry-forward of disallowed interest, and tax losses carry forward. |
| Returns | Exit at a multiple in any year, exit costs and a management incentive pool. Sponsor IRR and MOIC, plus returns by exit year. Value-creation bridge (EBITDA growth, multiple change, debt paydown, fees) that reconciles exactly to the equity gain. |
| Covenants | Maximum net leverage by year, minimum interest cover and minimum DSCR. Each year shows headroom and the EBITDA cushion (how much EBITDA can fall before the tightest test breaks); the first breach and its year are reported. |
| WACC | CAPM in INR: G-sec risk-free rate, peer betas unlevered and relevered with the Hamada formula, size premium, after-tax cost of debt and target weights. |
| DCF | Unlevered FCFF, mid-year convention, Gordon and exit-multiple terminal values. Cross-checks: the exit multiple implied by Gordon and the growth implied by the exit multiple. EV to equity bridge. |
| Comps | Trading comparables (EV/Revenue, EV/EBITDA, P/E on NTM; Excel-consistent quartiles) and precedent transactions (LTM multiples and premiums). Both give implied price ranges. |
| Analysis | Scenarios (base, upside, downside) with probabilities, and five sensitivity grids. Seeded Monte Carlo over growth, margin and exit multiple. Breakeven solvers and the football field. |

## Downside-first questions the model answers

- What exit multiple returns 1.0x, 2.0x and the hurdle IRR?
- How far can EBITDA fall, every year, before the first covenant breach, before cash runs out, and before the sponsor loses money?
- What price earns the hurdle IRR in the base case, and what price still returns 1.0x in the downside case? The **maximum bid** is the lower of the two.

## The recommendation rule

The memo's decision follows stated rules:

- **DECLINE**: downside MOIC below 0.75x, or base IRR more than 5 points under the hurdle.
- **RETURN FOR WORK**: the base case misses the hurdle IRR or target MOIC, breaches a covenant, or the offer exceeds the maximum bid.
- **APPROVE WITH CONDITIONS**: the base case works, but any of these hold:
  - the downside case breaches a covenant;
  - headroom to the maximum bid is under 5%;
  - fewer than half of the simulated paths clear the hurdle;
  - the standalone DCF is below the offer.
- **APPROVE**: none of the above.

## Workbook conventions

- Blue cells on yellow are inputs. Black cells are formulas. Green cells link to another sheet.
- On every time-series sheet, the same column is the same fiscal year.
- The **case selector** on Inputs (1 Base, 2 Upside, 3 Downside) switches every driver row and the exit multiple through `CHOOSE`. The growth shift, margin shift, EBITDA haircut, offer premium and leverage scale inputs also flow through live.
- Sensitivity and Football sheets hold engine values. Excel data tables cannot be authored reliably without Excel, so these sheets are labelled as static.
- The Checks sheet must read `ALL CHECKS PASS`. The cover shows it too.

### How the workbook is proven

The Python engine and the workbook are two separate implementations of one model:
- the engine computes each number directly;
- the workbook holds Excel formulas.

The tests do three things:
1. **Recompute from the saved file.** `stockex.deals.formula_eval` reloads the `.xlsx`, recomputes every formula from the inputs alone, and requires each engine-mapped cell (more than 600) to match within 1e-6. `deal-model` runs the same check and reports it in `workbook_verification`.
2. **Switch the case live.** The case selector and the sensitivity inputs are changed in the file, and the recomputed IRR and MOIC must equal the engine's run of that case.
3. **Recalculate in LibreOffice, when installed.** All cached values are stripped, LibreOffice recalculates the file, and every mapped cell must match. This catches any formula that only our evaluator would accept.

## Indian deal structuring captured in the memo

The memo states these as points for counsel to confirm. Rules change, so treat them as a checklist, not advice.

- **SEBI SAST.** Crossing 25% triggers a mandatory open offer for at least 26% more, priced at or above the regulation's floor.
- **SEBI Delisting.** Going private needs 90% ownership after the offer, with reverse book-building price discovery (or the fixed-price route where available). Plan for the case where delisting fails.
- **Acquisition finance.**
  - Indian banks have historically been restricted from funding share purchases, and ECB end-use rules bar borrowing for share acquisition. So the acquisition debt is HoldCo NCDs placed with private credit.
  - RBI has been loosening these rules, so check the current position.
- **Structural subordination and Companies Act s.67.** HoldCo debt is paid from upstream dividends. OpCo security and debt push-down usually wait until the company is delisted and converted to private, or merged with the HoldCo.
- **Interest limitation (s.94B; renumbered in the Income-tax Act, 2025).**
  - The cap applies only to interest on debt from, or guaranteed by, non-resident associated enterprises. The case flags which tranches are caught, and the memo reports the disallowed interest.
  - Also check withholding tax on interest paid to FPIs.

## Using the evidence store

`--from-store DB --security ID --cutoff TS` replaces the case's historicals and closing balance sheet with point-in-time observations from the evidence store:
- field names are `financial.<line>.<FY>` and `balance_sheet.<item>.<FY>`;
- only observations available at the cutoff are used, and a missing field is an error;
- the summary lists the observation and source behind every figure, and flags anything not `VERIFIED`.

## Limits

- Annual periods. The close is assumed on the last balance sheet date, and stub periods are ignored.
- No purchase-price allocation write-ups, deferred tax, leases, minority interests or dividend recapitalisations.
- The model assumes 100% ownership after the deal. Model partial ownership separately if delisting may fail.
- Comps and precedents are whatever the case supplies. The engine does not fetch market data.
- Monte Carlo shifts apply uniformly to every year of a path. It describes sensitivity to the stated distributions, not a forecast of real-world probabilities.
