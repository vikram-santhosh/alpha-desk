"""Sector Scanner — LLM-based analysis of sector news articles.

Batches articles and sends to Haiku with a prompt listing all 10 sectors.
Scores each article for sector_relevance, direction, catalyst_type, summary.
Filters to relevance >= threshold.
"""
from __future__ import annotations

import json
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "sector_scanner"
MODEL = "claude-haiku-4-5"
BATCH_SIZE = 15
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are a sector analyst for AlphaDesk, scanning broad market sectors for momentum and catalysts.

THEMATIC SECTORS:
- space_tech: RKLB, ASTS, LUNR, RDW, MNTS
- quantum_computing: IONQ, RGTI, QBTS
- nuclear_energy: SMR, OKLO, NNE, LEU
- robotics_ai: PLTR, PATH, SERV
- defense_aerospace: LMT, RTX, NOC, GD, LHX
- gold_miners: NEM, GOLD, AEM, FNV, WPM
- energy_infrastructure: ET, WMB, KMI, OKE, TRGP
- uranium: CCJ, UEC, NXE, DNN
- infrastructure_build: CAT, DE, VMC, MLM, URI
- commodity_supercycle: BHP, RIO, VALE, FCX, SCCO

For each article, provide:
1. **sector** (string): Which sector this article is most relevant to (use exact names above)
2. **sector_relevance** (0-10): How important is this for the sector's investment thesis?
   - 8-10: Major catalyst, policy change, or earnings surprise directly affecting sector
   - 6-7: Notable development worth tracking
   - 4-5: Minor or tangential relevance
   - 0-3: Not relevant
3. **direction** ("bullish", "bearish", "neutral"): Directional impact on the sector
4. **catalyst_type** (string): One of "earnings", "policy", "macro", "geopolitical", "supply_demand", "sentiment", "regulatory", "other"
5. **summary** (string): 1-sentence summary focused on sector impact
6. **tickers** (list): Specific tickers from the sector that are most affected

Respond with ONLY a JSON array of objects, one per article, in the same order as provided."""


def _build_batch_prompt(articles: list[dict[str, Any]]) -> str:
    """Build user prompt for a batch of articles."""
    lines = [f"Analyze these {len(articles)} articles for sector relevance:\n"]
    for i, article in enumerate(articles, 1):
        title = article.get("title", "Untitled")
        source = article.get("source", "Unknown")
        summary = article.get("summary", "")[:300]
        tickers = ", ".join(article.get("related_tickers", [])[:5])
        sector = article.get("sector", "unknown")
        lines.append(
            f"[{i}] ({sector}) {title}\n"
            f"    Source: {source} | Tickers: {tickers}\n"
            f"    {summary}\n"
        )
    return "\n".join(lines)


def _parse_response(text: str, batch_size: int) -> list[dict[str, Any]]:
    """Parse LLM JSON response into list of analysis dicts."""
    text = text.strip()
    # Find JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        log.warning("No JSON array found in response")
        return []

    try:
        results = json.loads(text[start : end + 1])
        if not isinstance(results, list):
            return []
        return results
    except json.JSONDecodeError as e:
        log.warning("Failed to parse analysis response: %s", e)
        return []


def analyze_sector_articles(
    articles: list[dict[str, Any]],
    min_relevance: int = 6,
) -> list[dict[str, Any]]:
    """Analyze articles in batches, filter by relevance.

    Args:
        articles: List of normalized article dicts (with 'sector' tag).
        min_relevance: Minimum sector_relevance score to keep.

    Returns:
        List of enriched article dicts that passed the relevance filter.
    """
    if not articles:
        return []

    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping sector analysis", spent, cap)
        return []

    client = anthropic.Anthropic()
    analyzed: list[dict[str, Any]] = []

    for batch_start in range(0, len(articles), BATCH_SIZE):
        batch = articles[batch_start : batch_start + BATCH_SIZE]
        prompt = _build_batch_prompt(batch)

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            record_usage(AGENT_NAME, response.usage.input_tokens, response.usage.output_tokens, model=MODEL)

            text = response.content[0].text if response.content else ""
            results = _parse_response(text, len(batch))

            for i, result in enumerate(results):
                if i >= len(batch):
                    break
                relevance = result.get("sector_relevance", 0)
                if relevance < min_relevance:
                    continue

                enriched = dict(batch[i])
                enriched["sector_relevance"] = relevance
                enriched["direction"] = result.get("direction", "neutral")
                enriched["catalyst_type"] = result.get("catalyst_type", "other")
                enriched["sector_summary"] = result.get("summary", "")
                enriched["sector"] = result.get("sector", enriched.get("sector", "unknown"))
                enriched["sector_tickers"] = result.get("tickers", [])
                analyzed.append(enriched)

        except Exception as e:
            log.error("Sector analysis batch failed: %s", e, exc_info=True)

    log.info(
        "Sector analysis: %d/%d articles passed relevance >= %d",
        len(analyzed),
        len(articles),
        min_relevance,
    )
    return analyzed
