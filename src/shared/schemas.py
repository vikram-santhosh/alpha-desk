"""Structured recommendation schema for AlphaDesk v2.

Provides rigorous dataclass-based schemas for recommendations, evidence,
bear cases, invalidation conditions, and analyst scores. Every recommendation
must include structured bear case, invalidation conditions, evidence quality
scoring, and "why now" reasoning.

Uses stdlib dataclasses (not Pydantic) with to_dict() / from_dict() methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any


# ═══════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════

def compute_recency_decay(recency_days: int) -> float:
    """Compute recency decay multiplier for evidence weighting.

    Returns:
        1.0 if < 14 days, 0.7 if 14-30, 0.4 if 30-60,
        0.2 if 60-90, 0.1 if > 90 days.
    """
    if recency_days < 14:
        return 1.0
    elif recency_days <= 30:
        return 0.7
    elif recency_days <= 60:
        return 0.4
    elif recency_days <= 90:
        return 0.2
    else:
        return 0.1


def compute_evidence_quality_score(evidence: list[EvidenceItem]) -> float:
    """Compute evidence quality score from a list of evidence items.

    For each item: weighted_score = base_weight * recency_decay.
    Uses fixed denominator of 15.0 (three strong signals at 5.0 each)
    so adding weak evidence never lowers the score.

    Returns:
        Score 0-100.
    """
    if not evidence:
        return 0.0
    total = 0.0
    for item in evidence:
        decay = compute_recency_decay(item.recency_days)
        item.weighted_score = item.base_weight * decay
        total += item.weighted_score
    # Fixed denominator: 15.0 = "fully evidenced" (three strong signals at 5.0)
    # Adding weak evidence adds to the numerator without inflating denominator
    score = (total / 15.0) * 100
    return max(0.0, min(score, 100.0))


def compute_composite_score(scores: AnalystScores) -> float:
    """Compute weighted composite score from analyst scores.

    Weights: growth 0.25, value 0.25, risk 0.15,
    catalyst_proximity 0.15, novelty 0.10, diversification 0.10.
    Result multiplied by skeptic_confidence_modifier.
    """
    weighted = (
        scores.growth_score * 0.25
        + scores.value_score * 0.25
        + scores.risk_score * 0.15
        + scores.catalyst_proximity_score * 0.15
        + scores.novelty_score * 0.10
        + scores.diversification_score * 0.10
    )
    return round(weighted * scores.skeptic_confidence_modifier, 2)


def validate_recommendation(rec: Recommendation) -> list[str]:
    """Validate a Recommendation object. Returns list of error strings.

    Rules:
        - bear_case fields must not be empty
        - At least 1 invalidation_condition
        - why_now.what_changed must not be empty
        - If action is BUY, sizing must not be None
        - Evidence must have at least 2 items
        - High conviction requires evidence_quality_score >= 60
        - High conviction requires composite_score >= 65
    """
    errors = []

    # Bear case mandatory
    if not rec.bear_case.primary_risk:
        errors.append("bear_case.primary_risk is empty")
    if not rec.bear_case.whats_priced_in:
        errors.append("bear_case.whats_priced_in is empty")
    if not rec.bear_case.base_rate:
        errors.append("bear_case.base_rate is empty")

    # Invalidation conditions
    if not rec.invalidation_conditions:
        errors.append("At least 1 invalidation_condition required")

    # Why now
    if not rec.why_now.what_changed:
        errors.append("why_now.what_changed is empty")

    # Sizing for BUY
    if rec.action == "BUY" and rec.sizing is None:
        errors.append("BUY action requires sizing")

    # Evidence minimum
    if len(rec.thesis.supporting_evidence) < 2:
        errors.append(f"Need at least 2 evidence items, got {len(rec.thesis.supporting_evidence)}")

    # High conviction gates
    if rec.conviction_level == "high":
        if rec.thesis.evidence_quality_score < 60:
            errors.append(
                f"High conviction requires evidence_quality_score >= 60, "
                f"got {rec.thesis.evidence_quality_score:.1f}"
            )
        if rec.analyst_scores.composite_score < 65:
            errors.append(
                f"High conviction requires composite_score >= 65, "
                f"got {rec.analyst_scores.composite_score:.1f}"
            )

    return errors


# ═══════════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════════

@dataclass
class EvidenceItem:
    """A single piece of evidence supporting or undermining a thesis."""
    source: str           # "earnings_transcript", "insider_filing", "superinvestor_13f", etc.
    date: str             # ISO date
    claim: str            # What this evidence says
    base_weight: float    # Source-type weight
    recency_days: int     # Days since evidence was produced
    weighted_score: float = 0.0  # base_weight * recency_decay (computed)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "date": self.date,
            "claim": self.claim,
            "base_weight": self.base_weight,
            "recency_days": self.recency_days,
            "weighted_score": self.weighted_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EvidenceItem:
        return cls(
            source=d.get("source", ""),
            date=d.get("date", ""),
            claim=d.get("claim", ""),
            base_weight=d.get("base_weight", 0.0),
            recency_days=d.get("recency_days", 0),
            weighted_score=d.get("weighted_score", 0.0),
        )


@dataclass
class CatalystEvent:
    """An upcoming event that could move a stock."""
    event_type: str       # "earnings", "fomc", "product_launch", etc.
    date: str             # ISO date or "TBD"
    description: str
    days_away: int        # Computed
    impact_estimate: str  # "high", "medium", "low"

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "date": self.date,
            "description": self.description,
            "days_away": self.days_away,
            "impact_estimate": self.impact_estimate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CatalystEvent:
        return cls(
            event_type=d.get("event_type", ""),
            date=d.get("date", "TBD"),
            description=d.get("description", ""),
            days_away=d.get("days_away", 0),
            impact_estimate=d.get("impact_estimate", "medium"),
        )


@dataclass
class InvalidationCondition:
    """A specific, testable condition that would prove the thesis wrong."""
    condition: str
    monitoring: str         # How/when to check
    action_if_triggered: str
    triggered: bool = False
    triggered_date: str | None = None

    def to_dict(self) -> dict:
        return {
            "condition": self.condition,
            "monitoring": self.monitoring,
            "action_if_triggered": self.action_if_triggered,
            "triggered": self.triggered,
            "triggered_date": self.triggered_date,
        }

    @classmethod
    def from_dict(cls, d: dict) -> InvalidationCondition:
        return cls(
            condition=d.get("condition", ""),
            monitoring=d.get("monitoring", ""),
            action_if_triggered=d.get("action_if_triggered", ""),
            triggered=d.get("triggered", False),
            triggered_date=d.get("triggered_date"),
        )


@dataclass
class BearCase:
    """Structured bear case for a recommendation."""
    primary_risk: str
    secondary_risks: list[str] = field(default_factory=list)
    base_rate: str = ""          # Historical success rate for similar theses
    whats_priced_in: str = ""    # What does the market already expect?
    skeptic_confidence: float = 0.85  # 0.0 to 1.0

    def to_dict(self) -> dict:
        return {
            "primary_risk": self.primary_risk,
            "secondary_risks": self.secondary_risks,
            "base_rate": self.base_rate,
            "whats_priced_in": self.whats_priced_in,
            "skeptic_confidence": self.skeptic_confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BearCase:
        return cls(
            primary_risk=d.get("primary_risk", ""),
            secondary_risks=d.get("secondary_risks", []),
            base_rate=d.get("base_rate", ""),
            whats_priced_in=d.get("whats_priced_in", ""),
            skeptic_confidence=d.get("skeptic_confidence", 0.85),
        )


@dataclass
class Sizing:
    """Position sizing recommendation."""
    recommended_weight_pct: float
    max_weight_pct: float
    entry_strategy: str       # "Scale in: 50% now, 25% on pullback, 25% post-earnings"
    portfolio_impact: str     # "Increases semiconductor exposure from 35% to 39%"

    def to_dict(self) -> dict:
        return {
            "recommended_weight_pct": self.recommended_weight_pct,
            "max_weight_pct": self.max_weight_pct,
            "entry_strategy": self.entry_strategy,
            "portfolio_impact": self.portfolio_impact,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Sizing:
        return cls(
            recommended_weight_pct=d.get("recommended_weight_pct", 0.0),
            max_weight_pct=d.get("max_weight_pct", 0.0),
            entry_strategy=d.get("entry_strategy", ""),
            portfolio_impact=d.get("portfolio_impact", ""),
        )


@dataclass
class WhyNow:
    """Explains the timing rationale for a recommendation."""
    catalyst: str              # The specific catalyst making this timely
    catalyst_date: str | None = None  # When the catalyst hits
    what_changed: str = ""     # What's different from last week/month
    timing_signal: str = ""    # The trigger (insider buy, guidance raise, etc.)

    def to_dict(self) -> dict:
        return {
            "catalyst": self.catalyst,
            "catalyst_date": self.catalyst_date,
            "what_changed": self.what_changed,
            "timing_signal": self.timing_signal,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WhyNow:
        return cls(
            catalyst=d.get("catalyst", ""),
            catalyst_date=d.get("catalyst_date"),
            what_changed=d.get("what_changed", ""),
            timing_signal=d.get("timing_signal", ""),
        )


@dataclass
class Thesis:
    """Investment thesis with structured evidence."""
    core_argument: str                            # 2-3 sentence core thesis
    supporting_evidence: list[EvidenceItem] = field(default_factory=list)
    evidence_quality_score: float = 0.0           # Computed

    def to_dict(self) -> dict:
        return {
            "core_argument": self.core_argument,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "evidence_quality_score": self.evidence_quality_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Thesis:
        evidence = [EvidenceItem.from_dict(e) for e in d.get("supporting_evidence", [])]
        return cls(
            core_argument=d.get("core_argument", ""),
            supporting_evidence=evidence,
            evidence_quality_score=d.get("evidence_quality_score", 0.0),
        )


@dataclass
class AnalystScores:
    """Quantitative scores from analyst evaluation."""
    growth_score: int = 50          # 0-100
    value_score: int = 50           # 0-100
    risk_score: int = 50            # 0-100 (higher = less risky)
    catalyst_proximity_score: int = 50  # 0-100
    novelty_score: int = 50         # 0-100
    diversification_score: int = 50 # 0-100
    composite_score: float = 50.0   # Weighted combination
    skeptic_confidence_modifier: float = 1.0  # 0.5 - 1.2

    def to_dict(self) -> dict:
        return {
            "growth_score": self.growth_score,
            "value_score": self.value_score,
            "risk_score": self.risk_score,
            "catalyst_proximity_score": self.catalyst_proximity_score,
            "novelty_score": self.novelty_score,
            "diversification_score": self.diversification_score,
            "composite_score": self.composite_score,
            "skeptic_confidence_modifier": self.skeptic_confidence_modifier,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnalystScores:
        return cls(
            growth_score=d.get("growth_score", 50),
            value_score=d.get("value_score", 50),
            risk_score=d.get("risk_score", 50),
            catalyst_proximity_score=d.get("catalyst_proximity_score", 50),
            novelty_score=d.get("novelty_score", 50),
            diversification_score=d.get("diversification_score", 50),
            composite_score=d.get("composite_score", 50.0),
            skeptic_confidence_modifier=d.get("skeptic_confidence_modifier", 1.0),
        )


@dataclass
class Recommendation:
    """Complete structured recommendation with all required fields."""
    ticker: str
    recommendation_date: str
    action: str               # "BUY", "WATCH", "TRIM", "SELL", "HOLD"
    category: str             # "conviction_add", "watchlist", "portfolio_trim", "moonshot"
    conviction_level: str     # "high", "medium", "low"

    why_now: WhyNow
    thesis: Thesis
    valuation: dict           # Flexible — from valuation_engine output
    bear_case: BearCase
    invalidation_conditions: list[InvalidationCondition]
    sizing: Sizing | None     # None for WATCH recommendations
    analyst_scores: AnalystScores
    catalysts: list[CatalystEvent] = field(default_factory=list)

    # Metadata
    source: str = ""          # Discovery source
    prior_recommendation: str | None = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "recommendation_date": self.recommendation_date,
            "action": self.action,
            "category": self.category,
            "conviction_level": self.conviction_level,
            "why_now": self.why_now.to_dict(),
            "thesis": self.thesis.to_dict(),
            "valuation": self.valuation,
            "bear_case": self.bear_case.to_dict(),
            "invalidation_conditions": [ic.to_dict() for ic in self.invalidation_conditions],
            "sizing": self.sizing.to_dict() if self.sizing else None,
            "analyst_scores": self.analyst_scores.to_dict(),
            "catalysts": [c.to_dict() for c in self.catalysts],
            "source": self.source,
            "prior_recommendation": self.prior_recommendation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Recommendation:
        return cls(
            ticker=d.get("ticker", ""),
            recommendation_date=d.get("recommendation_date", ""),
            action=d.get("action", "WATCH"),
            category=d.get("category", "watchlist"),
            conviction_level=d.get("conviction_level", "medium"),
            why_now=WhyNow.from_dict(d.get("why_now", {})),
            thesis=Thesis.from_dict(d.get("thesis", {})),
            valuation=d.get("valuation", {}),
            bear_case=BearCase.from_dict(d.get("bear_case", {})),
            invalidation_conditions=[
                InvalidationCondition.from_dict(ic)
                for ic in d.get("invalidation_conditions", [])
            ],
            sizing=Sizing.from_dict(d["sizing"]) if d.get("sizing") else None,
            analyst_scores=AnalystScores.from_dict(d.get("analyst_scores", {})),
            catalysts=[CatalystEvent.from_dict(c) for c in d.get("catalysts", [])],
            source=d.get("source", ""),
            prior_recommendation=d.get("prior_recommendation"),
        )

    def to_legacy_dict(self) -> dict:
        """Produce the old-style dict format for backward compatibility with formatters.

        Returns a dict that matches the structure expected by existing
        format_conviction_section / format_strategy_section / synthesizer output.
        """
        legacy = {
            "ticker": self.ticker,
            "category": self.category,
            "conviction": self.conviction_level,
            "thesis": self.thesis.core_argument,
            "scores": {
                "composite": self.analyst_scores.composite_score,
                "growth": self.analyst_scores.growth_score,
                "value": self.analyst_scores.value_score,
                "risk": self.analyst_scores.risk_score,
                "catalyst_proximity": self.analyst_scores.catalyst_proximity_score,
                "novelty": self.analyst_scores.novelty_score,
                "diversification": self.analyst_scores.diversification_score,
            },
            "fundamentals_summary": self.valuation,
            "action": self.action,
            "source": self.source,
            # Evidence in legacy format
            "pros": [
                f"PASS {e.source}: {e.claim}"
                for e in self.thesis.supporting_evidence
                if e.base_weight > 0
            ],
            "cons": [
                f"FAIL {e.source}: {e.claim}"
                for e in self.thesis.supporting_evidence
                if e.base_weight < 0
            ],
            # Bear case summary
            "bear_case": self.bear_case.primary_risk,
            "invalidation": (
                self.invalidation_conditions[0].condition
                if self.invalidation_conditions else ""
            ),
        }
        if self.sizing:
            legacy["sizing"] = {
                "weight_pct": self.sizing.recommended_weight_pct,
                "entry_strategy": self.sizing.entry_strategy,
            }
        return legacy


# ═══════════════════════════════════════════════════════
# JSON SERIALIZATION HELPERS
# ═══════════════════════════════════════════════════════

def recommendation_to_json(rec: Recommendation) -> str:
    """Serialize a Recommendation to JSON string."""
    return json.dumps(rec.to_dict(), indent=2)


def recommendation_from_json(json_str: str) -> Recommendation:
    """Deserialize a Recommendation from JSON string."""
    d = json.loads(json_str)
    return Recommendation.from_dict(d)


def recommendations_to_json(recs: list[Recommendation]) -> str:
    """Serialize a list of Recommendations to JSON string."""
    return json.dumps([r.to_dict() for r in recs], indent=2)


def recommendations_from_json(json_str: str) -> list[Recommendation]:
    """Deserialize a list of Recommendations from JSON string."""
    data = json.loads(json_str)
    return [Recommendation.from_dict(d) for d in data]


# ═══════════════════════════════════════════════════════
# BASE WEIGHT CONSTANTS
# ═══════════════════════════════════════════════════════

BASE_WEIGHTS = {
    # Smart money (strongest signals)
    "insider_purchase_large": 5.0,     # CEO/CFO buy > $500K
    "insider_purchase_small": 3.5,
    "insider_selling_large": -5.0,     # C-suite cluster sell (raised per advisor review)
    "insider_selling_small": -2.5,     # Single director sell
    # Earnings guidance
    "earnings_guidance_raised_confident": 5.0,
    "earnings_guidance_raised": 4.0,
    "earnings_guidance_maintained": 2.0,
    "earnings_guidance_lowered": -4.5,  # Raised from -3.0 per advisor review
    "earnings_guidance_withdrawn": -5.0,  # New: most bearish guidance signal
    "earnings_miss": -3.5,             # New: missed estimates
    # Superinvestors
    "superinvestor_new_position": 3.5,  # Raised from 3.0 — new position is more informative
    "superinvestor_3plus": 3.0,
    "superinvestor_2": 2.0,
    "superinvestor_existing": 0.7,      # Lowered from 1.0 — holding = inertia, weak signal
    "superinvestor_exit": -3.5,         # New: fund exited position
    # Reddit (reduced ~40% per advisor review — noisy source)
    "reddit_strong_positive": 1.5,     # Was 2.5
    "reddit_moderate_positive": 0.8,   # Was 1.5
    "reddit_weak_positive": 0.5,       # Was 1.0
    "reddit_negative": -1.5,           # Kept — negative Reddit is more informative
    # Prediction markets
    "prediction_market_favorable": 2.0,
    "prediction_market_unfavorable": -1.5,
    # Fundamentals
    "fundamentals_strong": 4.0,
    "fundamentals_moderate": 3.0,
    "fundamentals_weak": 2.0,
    "fundamentals_declining": -2.0,
    "fundamentals_decelerating": -1.0,  # New: growth slowing (not yet negative)
    # Valuation
    "valuation_attractive": 4.0,
    "valuation_fair": 3.0,
    "valuation_moderate": 1.5,
    "valuation_stretched": -2.0,
    # Technical
    "technical_signal": 1.5,
}
