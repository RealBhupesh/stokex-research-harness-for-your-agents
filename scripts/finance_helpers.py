"""Deterministic research arithmetic. No data retrieval or order execution."""
import argparse
import json
import math


def finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


def size_cash_trade(entry, stop, risk_rupees, cash_cap, friction_per_share=0, liquidity_share_cap=None):
    values = [finite(v, n) for v, n in zip(
        [entry, stop, risk_rupees, cash_cap, friction_per_share],
        ['entry', 'stop', 'risk_rupees', 'cash_cap', 'friction_per_share'])]
    entry, stop, risk_rupees, cash_cap, friction_per_share = values
    if not entry > stop > 0 or min(risk_rupees, cash_cap, friction_per_share) < 0:
        raise ValueError('Require entry > stop > 0 and nonnegative budgets/friction')
    per_share_risk = entry - stop + friction_per_share
    shares = min(math.floor(risk_rupees / per_share_risk), math.floor(cash_cap / entry))
    if liquidity_share_cap is not None:
        cap = finite(liquidity_share_cap, 'liquidity_share_cap')
        if cap < 0 or cap != math.floor(cap):
            raise ValueError('liquidity_share_cap must be a nonnegative integer')
        shares = min(shares, int(cap))
    return {'shares': shares, 'position_value_rupees': shares * entry,
            'planned_loss_including_friction_rupees': shares * per_share_risk,
            'warning': 'Stop execution is uncertain; cash cap must reserve fixed charges and buy costs.'}


def fcff_dcf(fcff, discount_rate, terminal_growth, net_debt, diluted_shares,
             other_equity_adjustments=0):
    flows = [finite(x, 'fcff') for x in fcff]
    r = finite(discount_rate, 'discount_rate')
    g = finite(terminal_growth, 'terminal_growth')
    debt = finite(net_debt, 'net_debt')
    shares = finite(diluted_shares, 'diluted_shares')
    adjustments = finite(other_equity_adjustments, 'other_equity_adjustments')
    if not flows or r <= g or r <= 0 or g <= -1 or shares <= 0 or flows[-1] <= 0:
        raise ValueError('Require nonempty FCFF, positive terminal FCFF/shares, r > max(g,0), g > -1')
    present_flows = sum(f / (1+r)**t for t, f in enumerate(flows, 1))
    present_terminal = flows[-1] * (1+g) / (r-g) / (1+r)**len(flows)
    ev = present_flows + present_terminal
    equity = ev - debt + adjustments
    return {'enterprise_value': ev, 'common_equity_value': equity,
            'value_per_share': equity / shares,
            'terminal_share_of_ev': present_terminal / ev if ev > 0 else None,
            'warning': 'Use consistent currency units and share scaling; reconcile minority/lease/other claims in bridge.'}


def cagr(beginning, ending, years):
    beginning = finite(beginning, 'beginning')
    ending = finite(ending, 'ending')
    years = finite(years, 'years')
    if beginning <= 0 or ending <= 0 or years <= 0:
        raise ValueError('CAGR requires positive endpoints and years')
    return {'cagr': (ending / beginning) ** (1 / years) - 1,
            'warning': 'CAGR hides interim volatility, dilution and cyclicality.'}


def graham_number(eps, book_value_per_share):
    eps = finite(eps, 'eps')
    bvps = finite(book_value_per_share, 'book_value_per_share')
    if eps <= 0 or bvps <= 0:
        raise ValueError('Graham number requires positive EPS and BVPS')
    return {'graham_number': math.sqrt(22.5 * eps * bvps),
            'warning': 'Historical heuristic only; not intrinsic value or suitable for every sector.'}


def altman_z_public_manufacturing(working_capital, retained_earnings, ebit,
                                  market_value_equity, total_liabilities,
                                  sales, total_assets):
    wc, re, ebit, mve, tl, sales, ta = [finite(v, n) for v, n in zip(
        [working_capital, retained_earnings, ebit, market_value_equity,
         total_liabilities, sales, total_assets],
        ['working_capital', 'retained_earnings', 'ebit', 'market_value_equity',
         'total_liabilities', 'sales', 'total_assets'])]
    if ta <= 0 or tl <= 0:
        raise ValueError('Total assets and total liabilities must be positive')
    score = 1.2 * wc / ta + 1.4 * re / ta + 3.3 * ebit / ta + 0.6 * mve / tl + sales / ta
    return {'altman_z': score, 'variant': 'original public manufacturing',
            'warning': 'Distress screen from a specific historical sample; not a bankruptcy probability and not for financial firms.'}


def beneish_m(dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi):
    values = [finite(v, n) for v, n in zip(
        [dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi],
        ['dsri', 'gmi', 'aqi', 'sgi', 'depi', 'sgai', 'tata', 'lvgi'])]
    dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi = values
    score = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi +
             0.892 * sgi + 0.115 * depi - 0.172 * sgai +
             4.679 * tata - 0.327 * lvgi)
    return {'beneish_m': score,
            'commonly_cited_original_flag': score > -1.78,
            'warning': 'Forensic flag only. It is not a finding of manipulation or fraud; inspect components and accounting context.'}


def piotroski_f(roa_positive, cfo_positive, roa_improved, cfo_exceeds_net_income,
                leverage_decreased, current_ratio_improved, no_new_shares,
                gross_margin_improved, asset_turnover_improved):
    names = ['roa_positive', 'cfo_positive', 'roa_improved',
             'cfo_exceeds_net_income', 'leverage_decreased',
             'current_ratio_improved', 'no_new_shares',
             'gross_margin_improved', 'asset_turnover_improved']
    raw = [roa_positive, cfo_positive, roa_improved, cfo_exceeds_net_income,
           leverage_decreased, current_ratio_improved, no_new_shares,
           gross_margin_improved, asset_turnover_improved]
    if any(type(value) is not bool for value in raw):
        raise ValueError('Every Piotroski component must be JSON true or false')
    components = dict(zip(names, [int(value) for value in raw]))
    return {'piotroski_f': sum(components.values()), 'components': components,
            'warning': 'Original context was high book-to-market nonfinancial firms; not a universal quality or buy score.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['size', 'dcf', 'cagr', 'graham', 'altman', 'beneish', 'piotroski'])
    parser.add_argument('input_json', help='Path to JSON inputs, not a literal JSON string')
    args = parser.parse_args()
    with open(args.input_json, encoding='utf-8') as handle:
        inputs = json.load(handle)
    functions = {
        'size': size_cash_trade,
        'dcf': fcff_dcf,
        'cagr': cagr,
        'graham': graham_number,
        'altman': altman_z_public_manufacturing,
        'beneish': beneish_m,
        'piotroski': piotroski_f,
    }
    function = functions[args.mode]
    print(json.dumps(function(**inputs), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
