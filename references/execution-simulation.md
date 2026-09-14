# Execution simulation

Research theoretical return and executable return separately.

Record quote timestamp, order value, average daily traded value window, free float, spread, depth when available, assumed participation, estimated slippage, fees, taxes, price bands, circuit history, trade-to-trade or surveillance status and corporate-action calendar.

Estimate one-way and round-trip friction and trading sessions required at the participation cap. Stress lower traded value, wider spread and adverse price movement. For event trades, model gaps and locked circuits. A stop price is an invalidation reference, not a guaranteed execution price.

Reject or reduce a theoretical opportunity when the intended position cannot be entered and exited without materially changing expected value. Refresh all execution inputs immediately before action.
