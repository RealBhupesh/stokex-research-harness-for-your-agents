# STOCKEX v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete STOCKEX v3 institutional equity-research operating system as a portable, evidence-gated skill package with deterministic decision controls.

**Architecture:** Five research subsystems produce explicit artifacts and gate states: market intelligence, evidence and normalization, expectations and catalysts, investment committee, and monitoring. A sixth release layer adds portfolio, execution, calibration and repository validation. Python standard-library scripts validate objective structure and arithmetic while analyst judgment remains source-backed and auditable.

**Tech Stack:** Markdown skills and references, JSON Schema documents, Python 3 standard library, `unittest`, Git.

**Spec:** `docs/superpowers/specs/2026-09-13-institutional-equity-research-os-design.md`

## Global Constraints

- Scope is India-listed cash equities on NSE and BSE.
- No authenticated live feed is claimed unless separately configured and tested.
- No personalized rupee sizing without capital, holdings, liquidity and loss-tolerance inputs.
- No aggregate score overrides a failed mandate, evidence, governance, liquidity or hard-risk gate.
- Requested extreme returns are search objectives, not base-case forecasts or promises.
- Every current claim requires a research cutoff and dated evidence.
- Python helpers use the standard library and perform deterministic calculations only.
- New or changed skill folders must pass `quick_validate.py`.

## File structure

- `scripts/market_intelligence.py`: benchmark-relative price attribution and driver materiality.
- `scripts/forecasting.py`: driver forecasts, estimate revisions and scenario distributions.
- `scripts/decision_packet.py`: machine-readable packet consistency validator.
- `scripts/portfolio_execution.py`: portfolio opportunity cost, capacity and execution estimates.
- `scripts/calibration.py`: frozen-forecast scoring and process-error summaries.
- `schema/decision-packet.schema.json`: documented packet contract.
- `skills/india-equity-{market-intelligence,evidence-room,variant-perception,investment-committee,thesis-monitor}/SKILL.md`: focused analyst roles.
- `references/*.md`: detailed rules loaded only by applicable roles.
- `templates/*.md`: evidence, forecast, IC and monitoring artifacts.
- `tests/test_*.py`: behavioral and arithmetic invariants.
- `SKILL.md`, `README.md`, `QUICKSTART.md`, `manifest.json`, `prompts/deep-stock-research.md`: release routing and documentation.

---

### Task 1: Market intelligence and price-move attribution

**Files:**
- Create: `scripts/market_intelligence.py`
- Create: `tests/test_market_intelligence.py`
- Create: `references/world-to-stock-transmission.md`
- Create: `references/price-move-attribution.md`
- Create: `references/active-research-triggers.md`
- Create: `skills/india-equity-market-intelligence/SKILL.md`
- Create: `templates/world-exposure-map.md`
- Create: `templates/price-move-attribution.md`

**Interfaces:**
- Produces: `compound_return(returns) -> float`, `price_move_attribution(asset_returns, benchmark_returns, sector_returns, peer_return_series) -> dict`, `driver_materiality(driver) -> dict`.
- Consumes: decimal periodic returns and a driver mapping with `exposure`, `magnitude`, `transmission_path`, `source_ids`.

- [ ] Write tests proving relative-return decomposition, mismatched-series rejection, material-driver requirements and explicit unexplained residuals.
- [ ] Run `python -m unittest tests.test_market_intelligence -v` and confirm imports or assertions fail.
- [ ] Implement the three pure functions with finite-number validation and warning fields.
- [ ] Run `python -m unittest tests.test_market_intelligence -v` and confirm all cases pass.
- [ ] Add the three references, specialist skill and two templates with `CONFIRMED`, `STRONGLY SUPPORTED`, `PLAUSIBLE`, `UNEXPLAINED` and `NOT MATERIAL` rules.
- [ ] Validate the skill and commit with `git commit -m "Build market intelligence and attribution layer"`.

### Task 2: Point-in-time evidence and normalization

**Files:**
- Create: `references/research-operating-system.md`
- Create: `references/evidence-gates.md`
- Create: `references/financial-normalization.md`
- Create: `skills/india-equity-evidence-room/SKILL.md`
- Create: `templates/evidence-packet.md`
- Create: `templates/normalized-financial-model.md`
- Create: `schema/decision-packet.schema.json`
- Create: `scripts/decision_packet.py`
- Create: `tests/test_decision_packet.py`

**Interfaces:**
- Produces: `validate_packet(packet) -> dict` returning `valid`, `errors`, `warnings`, and `gate_summary`; CLI accepts a packet JSON path.
- Consumes: decision packets conforming to `schema/decision-packet.schema.json`.

- [ ] Write failing tests for future-dated evidence, missing source provenance, approvals with failed gates, personalized sizing without portfolio inputs and hard-stop overrides.
- [ ] Run `python -m unittest tests.test_decision_packet -v` and confirm failure.
- [ ] Implement validation without third-party dependencies, including ISO-8601 timezone checks and deterministic error codes.
- [ ] Run `python -m unittest tests.test_decision_packet -v` and confirm pass.
- [ ] Add the schema, references, skill and templates with primary-source, contradiction and normalization contracts.
- [ ] Validate the skill and commit with `git commit -m "Build evidence room and decision packet validator"`.

### Task 3: Forecasting, expectations and catalysts

**Files:**
- Create: `scripts/forecasting.py`
- Create: `tests/test_forecasting.py`
- Create: `references/variant-perception.md`
- Create: `references/forecast-policy.md`
- Create: `references/catalyst-underwriting.md`
- Create: `references/management-credibility.md`
- Create: `references/relationship-graph.md`
- Create: `skills/india-equity-variant-perception/SKILL.md`
- Create: `templates/expectations-variant-map.md`
- Create: `templates/catalyst-calendar.md`

**Interfaces:**
- Produces: `driver_forecast(base_value, drivers) -> dict`, `estimate_revision(old, new) -> dict`, `scenario_distribution(current_price, scenarios) -> dict`, `guidance_score(records) -> dict`.
- `scenarios` contain `name`, `value`, and optional `probability`; probabilities are either absent everywhere or sum to one.

- [ ] Write failing tests for multiplicative driver bridges, revision direction, inconsistent probabilities, expected value, downside and management-guidance calibration.
- [ ] Run `python -m unittest tests.test_forecasting -v` and confirm failure.
- [ ] Implement the functions with finite checks, no implicit probabilities and warnings against false precision.
- [ ] Run `python -m unittest tests.test_forecasting -v` and confirm pass.
- [ ] Add references, specialist skill and templates connecting market expectations to operating drivers and dated catalysts.
- [ ] Validate the skill and commit with `git commit -m "Build expectations forecast and catalyst engine"`.

### Task 4: Investment committee, legal and credit controls

**Files:**
- Create: `references/investment-committee.md`
- Create: `references/legal-credit-intelligence.md`
- Create: `skills/india-equity-investment-committee/SKILL.md`
- Create: `templates/initiating-coverage-report.md`
- Create: `templates/investment-committee-memo.md`
- Modify: `scripts/decision_packet.py`
- Modify: `tests/test_decision_packet.py`

**Interfaces:**
- Extends: `validate_packet(packet)` with IC action, unresolved contradiction, legal-credit and speculative-mandate checks.
- IC actions are `APPROVE_FOR_CONSIDERATION`, `APPROVE_WITH_CONDITIONS`, `RETURN_FOR_WORK`, or `VETO`.

- [ ] Add failing tests proving unresolved controlling contradictions, legal hard stops and incomplete asymmetric-speculation controls block approval.
- [ ] Run the targeted tests and confirm failure.
- [ ] Implement the new deterministic checks and stable error codes.
- [ ] Run the targeted tests and the full test suite.
- [ ] Add references, specialist skill and IC report templates.
- [ ] Validate the skill and commit with `git commit -m "Build adversarial investment committee controls"`.

### Task 5: Portfolio, opportunity cost and execution realism

**Files:**
- Create: `scripts/portfolio_execution.py`
- Create: `tests/test_portfolio_execution.py`
- Create: `references/portfolio-and-opportunity-cost.md`
- Create: `references/execution-simulation.md`
- Modify: `templates/investment-committee-memo.md`

**Interfaces:**
- Produces: `candidate_opportunity_cost(candidate_return, alternative_returns) -> dict`, `execution_estimate(order_value, average_daily_traded_value, spread_bps, slippage_bps, fees_bps, participation_rate) -> dict`, `position_risk_budget(portfolio_value, max_loss_fraction, entry_price, invalidation_price) -> dict`.

- [ ] Write failing tests for opportunity-cost ranking, invalid liquidity inputs, all-in friction, exit sessions and loss-budget sizing.
- [ ] Run `python -m unittest tests.test_portfolio_execution -v` and confirm failure.
- [ ] Implement transparent arithmetic with no order execution or stop guarantee.
- [ ] Run targeted and full tests.
- [ ] Add portfolio and execution references and update the IC template.
- [ ] Commit with `git commit -m "Add portfolio and execution decision controls"`.

### Task 6: Active monitoring and analyst calibration

**Files:**
- Create: `scripts/calibration.py`
- Create: `tests/test_calibration.py`
- Create: `references/thesis-monitoring.md`
- Create: `references/analyst-performance-lab.md`
- Create: `skills/india-equity-thesis-monitor/SKILL.md`
- Create: `templates/thesis-monitor.md`
- Create: `templates/post-mortem.md`

**Interfaces:**
- Produces: `validate_transition(old_status, new_status, trigger) -> dict`, `forecast_error(forecast, actual) -> dict`, `process_score(records) -> dict`.
- Monitoring statuses are `ACTIVE`, `CONFIRMED`, `WEAKENED`, `INVALIDATED`, `CLOSED`; status changes require a dated trigger.

- [ ] Write failing tests for prohibited silent status changes, forecast-error direction and aggregated process metrics.
- [ ] Run `python -m unittest tests.test_calibration -v` and confirm failure.
- [ ] Implement functions with minimum-sample warnings and no automatic strategy rewrite.
- [ ] Run targeted and full tests.
- [ ] Add monitoring references, skill and templates.
- [ ] Validate the skill and commit with `git commit -m "Build thesis monitoring and calibration loop"`.

### Task 7: Orchestrator and deep-research integration

**Files:**
- Modify: `SKILL.md`
- Modify: `prompts/deep-stock-research.md`
- Modify: `skills/india-equity-review/SKILL.md`
- Modify: `templates/recommendation.md`
- Modify: `scripts/USAGE.md`

**Interfaces:**
- Consumes: every artifact and gate produced in Tasks 1 through 6.
- Produces: a fifteen-stage run contract with objective-specific routing and IC outcomes.

- [ ] Update the root orchestrator to route all five mandate modes and fifteen stages.
- [ ] Update the deep-research prompt so no opinion appears before attribution, evidence, forecasts, risks and IC review.
- [ ] Update review and recommendation files with world-driver, price-attribution, opportunity-cost and IC sections.
- [ ] Document every new CLI with reproducible JSON examples.
- [ ] Run internal-link and prohibited-claim checks.
- [ ] Commit with `git commit -m "Integrate STOCKEX v3 research workflow"`.

### Task 8: Release validation and documentation

**Files:**
- Modify: `README.md`
- Modify: `QUICKSTART.md`
- Modify: `manifest.json`
- Modify: `references/design-decisions.md`
- Create: `tests/test_repository_integrity.py`

**Interfaces:**
- Repository version becomes `3.0.0` only after every test and skill validation passes.

- [ ] Write repository-integrity tests for manifest completeness, internal links, JSON parsing, skill metadata and required v3 assets.
- [ ] Run the integrity test and confirm it fails against the v2 manifest.
- [ ] Update README, quickstart, design decisions and manifest to reflect tested capabilities and explicit integration limits.
- [ ] Run `python -m unittest discover -s tests -v` and validate all eleven specialist skills.
- [ ] Run `git diff --check`, inspect `git status --short`, create a release archive outside the repository and verify its contents.
- [ ] Commit with `git commit -m "Release STOCKEX v3 institutional research OS"`.
