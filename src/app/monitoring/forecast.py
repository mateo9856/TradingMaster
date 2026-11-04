"""Versioned log random walk with drift and strictly chronological validation."""

from bisect import bisect_right
from datetime import date, timedelta
from math import exp, isfinite, log, sqrt
from statistics import mean, stdev

from app.monitoring.calendar import sessions

MODEL_VERSION = "log-drift-v1"
TRAIN = 365
ORIGINS = 60


def estimate(prices: list[float], steps: int) -> tuple[float, float, float]:
    changes = [log(b / a) for a, b in zip(prices, prices[1:])]
    drift = mean(changes)
    # Includes uncertainty in the estimated drift, which matters at long horizons.
    spread = 1.281551565545 * stdev(changes) * sqrt(steps * (1 + steps / len(changes)))
    center = log(prices[-1]) + steps * drift
    return exp(center), exp(center - spread), exp(center + spread)


def forecast(rows: list[tuple[date, float]], horizon: int, venue: str | None = None) -> dict:
    base = {"model_version": MODEL_VERSION, "horizon_days": horizon}
    if len(rows) < TRAIN + ORIGINS:
        return {**base, "status": "insufficient_history"}
    days, prices = map(list, zip(*rows))
    if any(not isfinite(p) or p <= 0 for p in prices):
        return {**base, "status": "invalid_history"}
    if days != sessions(days[0], days[-1], venue):
        return {**base, "status": "incomplete_history"}
    # Backfill normalizes known splits. A remaining discontinuity fails closed.
    if venue and any(abs(log(b / a)) > log(1.8) for a, b in zip(prices, prices[1:])):
        return {**base, "status": "discontinuous_history"}
    errors, naive_errors = [], []
    try:
        for origin in range(len(prices) - 1, TRAIN - 2, -1):
            target_day = days[origin] + timedelta(days=horizon)
            if target_day > days[-1]:
                continue
            target = bisect_right(days, target_day) - 1
            if target <= origin:
                continue
            prediction, _, _ = estimate(prices[origin - TRAIN + 1:origin + 1], target - origin)
            errors.append(abs(prediction - prices[target]))
            naive_errors.append(abs(prices[origin] - prices[target]))
            if len(errors) == ORIGINS:
                break
        if len(errors) < ORIGINS:
            return {**base, "status": "insufficient_history"}
        metrics = {"mae": mean(errors), "baseline_mae": mean(naive_errors), "origins": len(errors)}
        if metrics["mae"] >= metrics["baseline_mae"]:
            return {**base, "status": "not_validated", "validation": metrics}
        target_day = days[-1] + timedelta(days=horizon)
        steps = len(sessions(days[-1] + timedelta(days=1), target_day, venue))
        center, lower, upper = estimate(prices[-TRAIN:], steps)
        if not all(isfinite(p) and p > 0 for p in (center, lower, upper)):
            raise OverflowError
        return {**base, "status": "ready", "target_date": target_day.isoformat(),
                "reference_date": days[-1].isoformat(),
                "reference_price": str(prices[-1]), "price": str(center), "lower": str(lower),
                "upper": str(upper), "interval_percent": 80,
                "change_percent": str((center / prices[-1] - 1) * 100), "validation": metrics}
    except (OverflowError, ValueError):
        return {**base, "status": "invalid_history"}
