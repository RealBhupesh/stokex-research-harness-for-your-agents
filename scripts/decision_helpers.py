"""Transparent decision diagnostics. No data retrieval, prediction model, or order execution."""
import argparse
from datetime import datetime
import json
import math


def finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


def required_return(capital, target_value, calendar_days):
    capital = finite(capital, 'capital')
    target_value = finite(target_value, 'target_value')
    days = finite(calendar_days, 'calendar_days')
    if capital <= 0 or target_value <= 0 or days <= 0:
        raise ValueError('Capital, target value and days must be positive')
    holding = target_value / capital - 1
    annualized = (target_value / capital) ** (365.25 / days) - 1
    return {'required_holding_period_return': holding,
            'equivalent_compounded_annual_return': annualized,
            'warning': 'Annualized equivalence is arithmetic context, not an expected or achievable return.'}


def gbm_target_probability(start_price, target_price, years, annual_drift, annual_volatility):
    s0, target, t, mu, sigma = [finite(v, n) for v, n in zip(
        [start_price, target_price, years, annual_drift, annual_volatility],
        ['start_price', 'target_price', 'years', 'annual_drift', 'annual_volatility'])]
    if s0 <= 0 or target <= 0 or t <= 0 or sigma < 0:
        raise ValueError('Prices and years must be positive; volatility must be nonnegative')
    if sigma == 0:
        terminal = s0 * math.exp(mu * t)
        probability = 1.0 if terminal >= target else 0.0
    else:
        z = (math.log(target / s0) - (mu - 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
        probability = 0.5 * math.erfc(z / math.sqrt(2))
    return {'model': 'geometric Brownian motion sensitivity',
            'target_probability': probability,
            'inputs': {'annual_drift': mu, 'annual_volatility': sigma, 'years': t},
            'warning': 'Assumption-driven sensitivity only; ignores jumps, circuits, liquidity, regime change and parameter error.'}


def _fcff_ev(fcff0, explicit_growth, years, discount_rate, terminal_growth):
    flows = [fcff0 * (1 + explicit_growth) ** year for year in range(1, years + 1)]
    pv = sum(flow / (1 + discount_rate) ** year for year, flow in enumerate(flows, 1))
    terminal = flows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    return pv + terminal / (1 + discount_rate) ** years


def reverse_fcff_growth(current_enterprise_value, current_fcff, years,
                        discount_rate, terminal_growth,
                        lower_growth=-0.5, upper_growth=2.0, tolerance=1e-8):
    ev, fcff0, r, tg, low, high, tol = [finite(v, n) for v, n in zip(
        [current_enterprise_value, current_fcff, discount_rate, terminal_growth,
         lower_growth, upper_growth, tolerance],
        ['current_enterprise_value', 'current_fcff', 'discount_rate', 'terminal_growth',
         'lower_growth', 'upper_growth', 'tolerance'])]
    years_value = finite(years, 'years')
    if years_value != math.floor(years_value):
        raise ValueError('years must be an integer')
    years = int(years_value)
    if ev <= 0 or fcff0 <= 0 or years <= 0 or r <= tg or r <= 0 or low <= -1 or high <= low or tol <= 0:
        raise ValueError('Invalid positive values or growth/discount bracket')
    low_ev = _fcff_ev(fcff0, low, years, r, tg)
    high_ev = _fcff_ev(fcff0, high, years, r, tg)
    if not low_ev <= ev <= high_ev:
        raise ValueError('Current EV lies outside values produced by the supplied growth bracket')
    for _ in range(200):
        mid = (low + high) / 2
        mid_ev = _fcff_ev(fcff0, mid, years, r, tg)
        if abs(mid_ev - ev) <= tol * ev:
            break
        if mid_ev < ev:
            low = mid
        else:
            high = mid
    return {'implied_explicit_fcff_growth': mid, 'reconstructed_enterprise_value': mid_ev,
            'fixed_assumptions': {'years': years, 'discount_rate': r, 'terminal_growth': tg},
            'warning': 'Single-variable reverse DCF; result is fragile to normalization, discount rate and terminal assumptions.'}


def earnings_acceleration(quarterly_values):
    values = [finite(v, 'quarterly_values') for v in quarterly_values]
    if len(values) < 8 or values[-5] == 0 or values[-6] == 0:
        raise ValueError('Need at least eight quarters and nonzero comparison bases')
    current_yoy = values[-1] / values[-5] - 1
    prior_yoy = values[-2] / values[-6] - 1
    low_confidence = values[-5] < 0 or values[-6] < 0
    return {'latest_yoy_growth': current_yoy, 'prior_quarter_yoy_growth': prior_yoy,
            'change_in_yoy_growth': current_yoy - prior_yoy,
            'low_confidence_negative_base': low_confidence,
            'warning': 'Reconcile seasonality, acquisitions, exceptional items, dilution and base effects.'}


def point_in_time(records, decision_at):
    decision = datetime.fromisoformat(decision_at.replace('Z', '+00:00'))
    if decision.tzinfo is None:
        raise ValueError('decision_at must include timezone')
    violations = []
    for index, record in enumerate(records):
        raw = record.get('available_at')
        if not raw:
            violations.append({'index': index, 'reason': 'missing available_at'})
            continue
        available = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if available.tzinfo is None:
            violations.append({'index': index, 'reason': 'available_at missing timezone'})
        elif available > decision:
            violations.append({'index': index, 'reason': 'future information', 'available_at': raw})
    return {'decision_at': decision_at, 'records_checked': len(records),
            'passed': not violations, 'violations': violations,
            'warning': 'Timestamp pass does not prove complete vintages, historical membership or absence of other leakage.'}


def brier_binary(probabilities, outcomes):
    probabilities = [finite(v, 'probability') for v in probabilities]
    outcomes = [int(v) for v in outcomes]
    if not probabilities or len(probabilities) != len(outcomes):
        raise ValueError('Equal nonempty probability and outcome arrays required')
    if any(p < 0 or p > 1 for p in probabilities) or any(y not in (0, 1) for y in outcomes):
        raise ValueError('Probabilities must be in [0,1] and outcomes binary')
    score = sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)
    return {'brier_score': score, 'n': len(outcomes),
            'warning': 'Interpret against a base-rate forecast and inspect reliability by horizon; small samples are unstable.'}


def portfolio_risk(weights, covariance_matrix):
    weights = [finite(v, 'weight') for v in weights]
    matrix = [[finite(v, 'covariance') for v in row] for row in covariance_matrix]
    n = len(weights)
    if n == 0 or len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValueError('Covariance matrix must be square and match nonempty weights')
    if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError('Weights must sum to 1')
    for i in range(n):
        if matrix[i][i] < 0:
            raise ValueError('Covariance diagonal cannot be negative')
        for j in range(n):
            if not math.isclose(matrix[i][j], matrix[j][i], rel_tol=1e-8, abs_tol=1e-12):
                raise ValueError('Covariance matrix must be symmetric')
    variance = sum(weights[i] * matrix[i][j] * weights[j] for i in range(n) for j in range(n))
    if variance < -1e-12:
        raise ValueError('Supplied covariance matrix produces negative portfolio variance')
    variance = max(variance, 0.0)
    component_numerators = [weights[i] * sum(matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]
    return {'portfolio_variance': variance, 'portfolio_volatility': math.sqrt(variance),
            'variance_contribution': [value / variance if variance else 0.0 for value in component_numerators],
            'warning': 'Historical covariance is window-dependent and may rise during stress; pair with exposure and scenario analysis.'}


def market_risk_metrics(periodic_returns, benchmark_returns, periods_per_year=252, confidence=0.95):
    """Calculate descriptive risk statistics from matched historical return series."""
    returns = [finite(v, 'periodic_return') for v in periodic_returns]
    benchmark = [finite(v, 'benchmark_return') for v in benchmark_returns]
    ppy = finite(periods_per_year, 'periods_per_year')
    confidence = finite(confidence, 'confidence')
    if (not returns or len(returns) != len(benchmark) or ppy <= 0
            or any(r <= -1 for r in returns + benchmark)):
        raise ValueError('Need matched nonempty returns greater than -100% and positive periods_per_year')
    if not 0.5 < confidence < 1:
        raise ValueError('confidence must be greater than 0.5 and less than 1')

    n = len(returns)
    asset_mean = sum(returns) / n
    benchmark_mean = sum(benchmark) / n
    asset_variance = sum((r - asset_mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    benchmark_variance = sum((r - benchmark_mean) ** 2 for r in benchmark) / (n - 1) if n > 1 else 0.0
    covariance = (sum((r - asset_mean) * (b - benchmark_mean)
                      for r, b in zip(returns, benchmark)) / (n - 1)) if n > 1 else 0.0
    beta = covariance / benchmark_variance if benchmark_variance else None

    wealth = peak = 1.0
    maximum_drawdown = 0.0
    for periodic_return in returns:
        wealth *= 1 + periodic_return
        peak = max(peak, wealth)
        maximum_drawdown = min(maximum_drawdown, wealth / peak - 1)

    downside_deviation = math.sqrt(sum(min(0.0, r) ** 2 for r in returns) / n * ppy)
    losses = sorted(-r for r in returns)
    quantile_index = math.ceil(confidence * n) - 1
    historical_var = losses[quantile_index]
    tail_losses = [loss for loss in losses if loss >= historical_var]
    historical_cvar = sum(tail_losses) / len(tail_losses)

    return {
        'n_periods': n,
        'annualized_volatility': math.sqrt(asset_variance * ppy),
        'beta': beta,
        'maximum_drawdown': maximum_drawdown,
        'annualized_downside_deviation': downside_deviation,
        'confidence': confidence,
        'historical_var_loss': historical_var,
        'historical_cvar_loss': historical_cvar,
        'worst_period_loss': max(losses),
        'warning': ('These statistics are backward-looking and window-dependent. Historical VaR/CVaR are not maximum-loss '
                    'estimates and can miss gaps, circuits, liquidity failure and regime change.')
    }


def liquidity_exit_days(position_value, average_daily_traded_value, max_participation_rate=0.10):
    """Estimate trading sessions needed to exit under a stated volume participation cap."""
    position = finite(position_value, 'position_value')
    adtv = finite(average_daily_traded_value, 'average_daily_traded_value')
    participation = finite(max_participation_rate, 'max_participation_rate')
    if position <= 0 or adtv <= 0:
        raise ValueError('position_value and average_daily_traded_value must be positive')
    if participation <= 0 or participation > 1:
        raise ValueError('max_participation_rate must be greater than 0 and at most 1')
    daily_capacity = adtv * participation
    raw_days = position / daily_capacity
    return {
        'daily_exit_capacity': daily_capacity,
        'raw_trading_days': raw_days,
        'minimum_whole_trading_sessions': math.ceil(raw_days),
        'warning': ('This is not a guarantee of execution. Refresh traded value, spread, depth, price bands, circuits, '
                    'ASM/GSM and stress liquidity before action.')
    }


def backtest_metrics(periodic_returns, benchmark_returns, periods_per_year=252, annual_risk_free_rate=0):
    returns = [finite(v, 'periodic_return') for v in periodic_returns]
    benchmark = [finite(v, 'benchmark_return') for v in benchmark_returns]
    ppy = finite(periods_per_year, 'periods_per_year')
    rf = finite(annual_risk_free_rate, 'annual_risk_free_rate')
    if not returns or len(returns) != len(benchmark) or ppy <= 0 or any(r <= -1 for r in returns + benchmark):
        raise ValueError('Need matched nonempty returns greater than -100% and positive periods_per_year')
    n = len(returns)
    total = math.prod(1 + r for r in returns) - 1
    benchmark_total = math.prod(1 + r for r in benchmark) - 1
    years = n / ppy
    annualized = (1 + total) ** (1 / years) - 1
    benchmark_annualized = (1 + benchmark_total) ** (1 / years) - 1
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    volatility = math.sqrt(variance * ppy)
    rf_period = (1 + rf) ** (1 / ppy) - 1 if rf > -1 else None
    if rf_period is None:
        raise ValueError('annual_risk_free_rate must be greater than -100%')
    sharpe = ((mean - rf_period) * ppy / volatility) if volatility else None
    downside_sq = [min(0.0, r - rf_period) ** 2 for r in returns]
    downside = math.sqrt(sum(downside_sq) / n * ppy)
    sortino = ((mean - rf_period) * ppy / downside) if downside else None
    wealth = peak = 1.0
    max_drawdown = 0.0
    for r in returns:
        wealth *= 1 + r
        peak = max(peak, wealth)
        max_drawdown = min(max_drawdown, wealth / peak - 1)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    payoff = ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))) if wins and losses else None
    return {'n_periods': n, 'years': years, 'total_return': total,
            'annualized_return': annualized, 'benchmark_total_return': benchmark_total,
            'benchmark_annualized_return': benchmark_annualized,
            'annualized_excess_return': annualized - benchmark_annualized,
            'annualized_volatility': volatility, 'sharpe': sharpe, 'sortino': sortino,
            'maximum_drawdown': max_drawdown, 'positive_period_rate': len(wins) / n,
            'average_win_to_average_loss': payoff,
            'warning': 'Metrics do not validate point-in-time inputs, execution, costs, taxes, selection bias or statistical significance.'}


FUNCTIONS = {
    'required_return': required_return,
    'gbm_target_probability': gbm_target_probability,
    'reverse_fcff_growth': reverse_fcff_growth,
    'earnings_acceleration': earnings_acceleration,
    'point_in_time': point_in_time,
    'brier_binary': brier_binary,
    'portfolio_risk': portfolio_risk,
    'market_risk_metrics': market_risk_metrics,
    'liquidity_exit_days': liquidity_exit_days,
    'backtest_metrics': backtest_metrics,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=sorted(FUNCTIONS))
    parser.add_argument('input_json', help='Path to a JSON object of named inputs')
    args = parser.parse_args()
    with open(args.input_json, encoding='utf-8') as handle:
        inputs = json.load(handle)
    print(json.dumps(FUNCTIONS[args.mode](**inputs), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
