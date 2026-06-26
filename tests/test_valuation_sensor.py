from __future__ import annotations

from src.score_engine.sensors.valuation import ValuationSensor
from src.score_engine.signals import Direction


def test_high_margin_of_safety_with_moderate_cagr_is_bullish():
    sensor = ValuationSensor()

    signal = sensor._to_signal(  # noqa: SLF001 - pure mapping helper
        "AMZN",
        {"implied_cagr": 13.0, "margin_of_safety": 46.0},
    )

    assert signal is not None
    assert signal.direction == Direction.BULL
    assert signal.strength >= 0.4

