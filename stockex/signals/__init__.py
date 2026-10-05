"""Short-term signals: indicators, F&O positioning, regime, setups, risk plans and the scanner."""

from .regime import classify_regime
from .risk_plan import DEFAULT_RISK_PARAMS, Rejection, TradePlan, build_plan
from .scan import evaluate_day, prepare_universe, scan, to_markdown
from .setups import DEFAULT_SETUP_PARAMS, SETUP_VERSIONS, SETUPS, SetupContext, Signal, evaluate_setups

__all__ = [
    "classify_regime", "DEFAULT_RISK_PARAMS", "Rejection", "TradePlan", "build_plan",
    "evaluate_day", "prepare_universe", "scan", "to_markdown",
    "DEFAULT_SETUP_PARAMS", "SETUP_VERSIONS", "SETUPS", "SetupContext", "Signal", "evaluate_setups",
]
