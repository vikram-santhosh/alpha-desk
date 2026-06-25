"""Earnings sensor signal-quality guarantees.

Locks in the self-improvement fixes: evidence names the real driver,
strength tracks beat magnitude (no early saturation), and confidence
reflects whether we have hard EPS data.
"""
from __future__ import annotations

from src.score_engine.sensors.earnings import EarningsSensor
from src.score_engine.signals import Direction


def _sig(data: dict):
    return EarningsSensor()._to_signal("TEST", data)


def test_eps_beat_drives_bull_and_evidence_names_it():
    sig = _sig({"eps_actual": 2.81, "eps_estimate": 2.0, "guidance_sentiment": None})
    assert sig.direction == Direction.BULL
    assert "EPS beat" in sig.evidence
    assert "%" in sig.evidence
    # Must NOT misleadingly claim guidance when there is none
    assert "guidance=neutral" not in sig.evidence


def test_eps_miss_drives_bear():
    sig = _sig({"eps_actual": 0.80, "eps_estimate": 1.00})
    assert sig.direction == Direction.BEAR
    assert "EPS miss" in sig.evidence


def test_bigger_beat_has_higher_strength():
    small = _sig({"eps_actual": 1.05, "eps_estimate": 1.00})   # +5%
    big   = _sig({"eps_actual": 1.40, "eps_estimate": 1.00})   # +40%
    assert big.strength > small.strength, "larger beat must score stronger"
    # And neither saturates to an identical 1.0 the way /10 clamping did
    assert small.strength < 0.99


def test_hard_eps_data_is_higher_confidence_than_soft_guidance_only():
    hard = _sig({"eps_actual": 1.20, "eps_estimate": 1.00})              # quantitative
    soft = _sig({"guidance_sentiment": "raised"})                        # prose only
    assert hard.confidence >= soft.confidence


def test_guidance_and_surprise_agree_is_highest_confidence():
    both = _sig({"eps_actual": 1.20, "eps_estimate": 1.00, "guidance_sentiment": "raised"})
    assert both.confidence >= 0.85


def test_no_data_yields_neutral_low_confidence():
    sig = _sig({"eps_actual": None, "eps_estimate": None, "guidance_sentiment": None})
    assert sig.direction == Direction.NEUTRAL
    assert sig.confidence < 0.6
