"""Load sensor weights from config/advisor.yaml score_engine block."""
from __future__ import annotations

from src.shared.config_loader import load_config

DEFAULT_WEIGHTS: dict[str, float] = {
    "earnings":      1.8,
    "reddit":        0.8,
    "news":          1.0,
    "superinvestor": 1.5,
    "valuation":     1.4,
    "prediction":    1.2,
    "youtube":       0.7,
    "substack":      1.0,
    "x":             0.6,
    "cognition":     1.0,
}

WEIGHTS_VERSION = "v1-config"


def load_weights() -> dict[str, float]:
    """Return sensor weights, merging config overrides over defaults."""
    cfg = load_config("advisor")
    overrides = cfg.get("score_engine", {}).get("weights", {})
    return {**DEFAULT_WEIGHTS, **overrides}


def load_score_engine_config() -> dict:
    """Return full score_engine config block with defaults filled in."""
    cfg = load_config("advisor")
    se = cfg.get("score_engine", {})
    return {
        "breadth_min":  se.get("breadth_min",  2),
        "top_tier_min": se.get("top_tier_min", 3),
        "top_n":        se.get("top_n",        10),
        "weights":      load_weights(),
    }
