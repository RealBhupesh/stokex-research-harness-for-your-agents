# Accuracy controls

These controls exist so the scanner's track record means something. Each one closes a specific way a short-term backtest can look better than live trading.

## 1. Corporate-action adjustment

NSE bhavcopies carry raw prices, so a 1:5 split looks like an 80% crash and a false breakdown or breakout. Histories are back-adjusted before any signal is computed:

- Import NSE's corporate-actions file (`market-import DB corporate_actions.csv`). Splits, bonuses and consolidations become factors; other purposes are counted and skipped.
- Actions missing from that file are inferred from the bhavcopy itself. On an ex-date NSE publishes an adjusted `PREV_CLOSE`, so a gap of more than 2% between it and the previous close becomes an `INFERRED` adjustment. Rights issues are caught this way too.
- Only ex-dates on or before the as-of date are applied. Each series lists its adjustments, and `market-status` counts the imported actions.

## 2. Forward-test journal

The backtest is evidence; live results are the test.

```bash
python -m stockex.cli scan DB --as-of 2026-10-09 --scorecard scorecard.json --journal
python -m stockex.cli journal-update DB --as-of 2026-10-23
python -m stockex.cli journal-report DB
```

Picks are frozen with their plan and judge opinions. `journal-update` replays later sessions with the backtester's fill and exit rules, rescaling plan prices if a split goes ex after the scan. `journal-report` gives live results per setup and live calibration for Jev and the model. Scans show the live record next to the backtest record.

## 3. What PROVEN means

A setup is `PROVEN` only when all of these hold (scorecard schema 2):

- at least 30 trades and positive expectancy after costs;
- the one-sided lower confidence bound of expectancy is above zero. The bound comes from a bootstrap that resamples whole signal days, because trades signalled on the same day move together. Its confidence is Bonferroni-corrected for the number of setups (or setup × regime groups) tested;
- expectancy is positive in at least 60% of four consecutive time folds.

Each scorecard entry lists the lower bound, the confidence used, the number of signal days, the fold results and the reasons it failed. Expect fewer PROVEN setups than before. That is the point.

## 4. Execution realism

- **Costs.** Round-trip costs are the fee estimate (default 45 bp) plus square-root market impact per side: 100 bp × √(position value ÷ median daily traded value). Larger orders in thinner stocks cost more, and plans whose reward/risk falls below the minimum after impact are rejected.
- **Upper circuit.** A stock locked at its upper circuit all session cannot be bought.
- **Lower circuit.** A position locked at its lower circuit cannot be sold until the next session opens.
- **Gap risk.** Statistics report the share of gap-stop exits and the average loss beyond the planned stop.

## 5. Sectors and announcements

- **Sectors.** Import an index constituent list (for example `ind_nifty500list.csv`) to map symbols to industries. Candidates gain 20- and 60-day strength against their industry. Scans keep at most two picks per industry (`max_per_sector`), and so does the portfolio backtest.
- **Announcements.** Import NSE corporate announcements. They are keyword-classified on import; `announcements-classify --jev` lets Jev classify the ones left as `OTHER`.
  - Results, order wins, bonus/split, buyback, fund raises, promoter trades and M&A become catalysts on the first session whose end-of-day data could react (18:30 IST cutoff).
  - They label gaps and other picks automatically, alongside any `--events` file.

## 6. Walk-forward model

A transparent logistic regression predicts whether a candidate reaches T1 before its stop. It uses the same anonymized features Jev sees and fixed ridge shrinkage so its probabilities stay calibrated.
- **Training.** During a backtest it retrains every 20 sessions on trades that had already closed, so every prediction it is judged on is out of sample.
- **Proof.** It must pass the same proof as Jev: positive Brier skill against setup base rates, AUC above 0.55, at least 50 judged trades and higher filtered expectancy.
- **Use in scans.** The final coefficients are stored in the scorecard. In scans, the PROVEN judge with the higher Brier skill (model or Jev) filters and re-ranks candidates; an unproven judge is shown for information only.

## Limits

- All of this was tested on synthetic NSE-format data. Run it on 2–3 years of real files, including names that later delisted (bhavcopies keep them), before trusting any status.
- Inferred adjustments can misfire on bad data. Check `market-status` and the series' adjustment list for surprises.
- Daily bars cannot show intraday order. Circuit and impact models are approximations.
