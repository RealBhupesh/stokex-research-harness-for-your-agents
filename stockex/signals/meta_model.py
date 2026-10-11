"""A transparent, walk-forward logistic model that predicts whether a candidate reaches T1.

It is the baseline Jev must beat, and a meta-labeler in its own right. It
uses only the anonymized candidate state (see ``stockex.jev.candidates``),
is retrained during backtests on trades that had already closed, and has to
pass the same calibration proof as Jev before it can affect a scan.
"""

import math


MODEL_FEATURE_VERSION = "1"
_REGIMES = ("RISK_ON", "NEUTRAL", "RISK_OFF")
_LIQUIDITY = {"under_10_crore": 0, "10_to_50_crore": 1, "50_to_200_crore": 2, "over_200_crore": 3}


def feature_vector(state: dict, setups: list[str]) -> dict[str, float]:
    """Numeric features from an anonymized candidate state; missing values become 0."""
    def num(value):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    features = {
        "stop_pct": num(state["plan"]["stop_pct"]),
        "t1_pct": num(state["plan"]["t1_pct"]),
        "reward_risk": num(state["plan"]["reward_risk_after_costs"]),
        "time_stop": num(state["plan"]["time_stop_sessions"]),
        "liquidity": float(_LIQUIDITY.get(state["liquidity"], 0)),
        "catalyst": 1.0 if state.get("catalyst") else 0.0,
        "catalyst_verified": 1.0 if (state.get("catalyst") or {}).get("verified") else 0.0,
        "in_fo": 1.0 if state.get("fo") else 0.0,
        "oi_chg1": num((state.get("fo") or {}).get("oi_chg1")),
        "oi_chg5": num((state.get("fo") or {}).get("oi_chg5")),
        "breadth": num(state["market"].get("breadth_above_sma50")),
        "nifty_ret20": num(state["market"].get("nifty_ret20")),
        "vix": num(state["market"].get("vix")),
        "vix_chg5": num(state["market"].get("vix_chg5")),
        "other_setups": float(len(state.get("other_setups", []))),
    }
    for key, value in state["technicals"].items():
        features[f"t_{key}"] = num(value)
    for regime in _REGIMES:
        features[f"regime_{regime}"] = 1.0 if state["market"].get("regime") == regime else 0.0
    for setup in setups:
        features[f"setup_{setup}"] = 1.0 if state["setup"] == setup else 0.0
    return features


class LogisticModel:
    """L2-regularised logistic regression on standardised features (batch gradient descent).

    Ridge shrinkage keeps the probabilities calibrated: without it the model
    ranks well but becomes overconfident, which the Brier-skill gate rejects.
    """

    def __init__(self, names: list[str], means: list[float], scales: list[float], weights: list[float],
                 bias: float, trained_on: int):
        self.names, self.means, self.scales = names, means, scales
        self.weights, self.bias, self.trained_on = weights, bias, trained_on

    @classmethod
    def fit(cls, rows: list[dict[str, float]], labels: list[int], *, l2: float = 0.1,
            iterations: int = 250, learning_rate: float = 0.5) -> "LogisticModel":
        """Fit with ridge strength ``l2`` per standardized feature (a fixed default, not tuned per run)."""
        names = sorted({name for row in rows for name in row})
        n = len(rows)
        columns = [[row.get(name, 0.0) for row in rows] for name in names]
        means = [sum(column) / n for column in columns]
        scales = []
        for column, mean in zip(columns, means):
            variance = sum((value - mean) ** 2 for value in column) / n
            scales.append(math.sqrt(variance) or 1.0)
        x = [[(columns[j][i] - means[j]) / scales[j] for j in range(len(names))] for i in range(n)]
        weights, bias = [0.0] * len(names), math.log((sum(labels) + 1) / (n - sum(labels) + 1))
        for _ in range(iterations):
            gradient, bias_gradient = [0.0] * len(names), 0.0
            for row, label in zip(x, labels):
                error = _sigmoid(bias + sum(w * v for w, v in zip(weights, row))) - label
                bias_gradient += error
                for j, value in enumerate(row):
                    gradient[j] += error * value
            bias -= learning_rate * bias_gradient / n
            for j in range(len(weights)):
                weights[j] -= learning_rate * (gradient[j] / n + l2 * weights[j])
        return cls(names, means, scales, weights, bias, n)

    def predict(self, features: dict[str, float]) -> float:
        z = self.bias
        for name, mean, scale, weight in zip(self.names, self.means, self.scales, self.weights):
            z += weight * (features.get(name, 0.0) - mean) / scale
        return _sigmoid(z)

    def to_dict(self) -> dict:
        return {"feature_version": MODEL_FEATURE_VERSION, "names": self.names, "means": self.means,
                "scales": self.scales, "weights": self.weights, "bias": self.bias, "trained_on": self.trained_on}

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticModel":
        return cls(data["names"], data["means"], data["scales"], data["weights"], data["bias"], data["trained_on"])


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1 + exp)


class WalkForwardModel:
    """Retrains every ``refit_every`` sessions on trades that closed before the current day."""

    def __init__(self, setups: list[str], *, min_train: int = 60, refit_every: int = 20):
        self.setups, self.min_train, self.refit_every = setups, min_train, refit_every
        self.model: LogisticModel | None = None
        self.sessions_since_fit = refit_every
        self.fits = 0

    def maybe_refit(self, day: str, completed: list[dict]) -> None:
        self.sessions_since_fit += 1
        if self.sessions_since_fit < self.refit_every:
            return
        known = [t for t in completed if t["exit_date"] < day]
        if len(known) < self.min_train or len({t["t1_hit"] for t in known}) < 2:
            return
        self.model = LogisticModel.fit([t["model_features"] for t in known], [int(t["t1_hit"]) for t in known])
        self.sessions_since_fit = 0
        self.fits += 1

    def predict(self, features: dict[str, float]) -> float | None:
        return None if self.model is None else self.model.predict(features)
