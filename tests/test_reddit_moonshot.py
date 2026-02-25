"""Test Reddit moonshot candidate sourcing."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock anthropic before any imports that cascade into it
from unittest.mock import patch, MagicMock
sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("fredapi", MagicMock())

import pytest


def _make_reddit_post(title, selftext="", score=50, num_comments=10, subreddit="smallstreetbets"):
    return {
        "title": title, "selftext": selftext, "score": score,
        "num_comments": num_comments, "subreddit": subreddit,
        "permalink": f"/r/{subreddit}/comments/abc/test",
        "stickied": False, "created_utc": 1708700000,
    }


def test_extract_tickers_from_text():
    from src.alpha_scout.reddit_moonshot_sourcer import _extract_tickers_from_text
    tickers = _extract_tickers_from_text("Just bought $IONQ and $PLTR")
    assert "IONQ" in tickers
    assert "PLTR" in tickers
    tickers = _extract_tickers_from_text("IONQ is the real quantum play, also looking at RGTI")
    assert "IONQ" in tickers
    assert "RGTI" in tickers
    tickers = _extract_tickers_from_text("THE BIG BUY opportunity FOR ALL")
    for word in ["THE", "BIG", "BUY", "FOR", "ALL"]:
        assert word not in tickers
    print("  ✅ Ticker extraction works correctly")


def test_source_moonshot_candidates():
    from src.alpha_scout.reddit_moonshot_sourcer import source_moonshot_candidates

    mock_posts_sub1 = [
        _make_reddit_post("$IONQ is the real quantum play", "Great DD on IONQ quantum", 150, 30, "smallstreetbets"),
        _make_reddit_post("Why I'm loading IONQ calls", "IONQ has huge potential", 200, 25, "smallstreetbets"),
        _make_reddit_post("RGTI vs IONQ - quantum battle", "Both interesting but RGTI...", 100, 20, "smallstreetbets"),
        _make_reddit_post("$PLTR is overvalued", "Palantir at these prices...", 80, 15, "smallstreetbets"),
        _make_reddit_post("AAPL earnings tomorrow", "Apple looking strong", 300, 50, "smallstreetbets"),
    ]
    mock_posts_sub2 = [
        _make_reddit_post("Deep dive: IONQ fundamentals", "Revenue growing 40%+", 120, 40, "SecurityAnalysis"),
        _make_reddit_post("$RGTI quantum computing analysis", "Rigetti has...", 90, 15, "SecurityAnalysis"),
        _make_reddit_post("PLTR government contracts expanding", "", 75, 10, "SecurityAnalysis"),
    ]
    mock_posts_sub3 = [
        _make_reddit_post("IONQ quantum breakthrough incoming", "", 60, 8, "valueinvesting"),
        _make_reddit_post("SMR nuclear play undervalued", "NuScale has...", 45, 5, "valueinvesting"),
    ]

    def mock_fetch(sub, limit, session):
        return {"smallstreetbets": mock_posts_sub1, "SecurityAnalysis": mock_posts_sub2,
                "valueinvesting": mock_posts_sub3}.get(sub, [])

    mock_valid_tickers = {
        "IONQ": {"market_cap": 5_000_000_000, "name": "IonQ"},
        "RGTI": {"market_cap": 1_500_000_000, "name": "Rigetti"},
        "PLTR": {"market_cap": 45_000_000_000, "name": "Palantir"},
        "AAPL": {"market_cap": 3_000_000_000_000, "name": "Apple"},
        "SMR": {"market_cap": 3_000_000_000, "name": "NuScale"},
    }
    mock_config = {"moonshot": ["smallstreetbets", "SecurityAnalysis", "valueinvesting"],
                   "settings": {"min_score": 5, "posts_per_sub": 50}}
    portfolio_tickers = {"NVDA", "AMZN", "GOOG", "META", "AVGO", "MRVL", "NFLX", "MSFT", "AMD", "TSM"}

    with patch("src.alpha_scout.reddit_moonshot_sourcer._fetch_subreddit_posts", side_effect=mock_fetch), \
         patch("src.alpha_scout.reddit_moonshot_sourcer._validate_tickers", return_value=mock_valid_tickers), \
         patch("src.alpha_scout.reddit_moonshot_sourcer.load_subreddits", return_value=mock_config), \
         patch("time.sleep"):
        candidates = source_moonshot_candidates(exclude_tickers=portfolio_tickers, config=mock_config)

    print(f"\n{'='*60}")
    print("Reddit Moonshot Sourcer Test")
    print(f"{'='*60}")
    print(f"\nFound {len(candidates)} candidates:\n")
    for i, c in enumerate(candidates, 1):
        sd = c["signal_data"]
        print(f"  {i}. {c['ticker']} (composite: {c['scores']['composite']})")
        print(f"     Source: {c['source']}")
        print(f"     Mentions: {sd['mention_count']}, Score: {sd['total_score']}")
        print(f"     Subreddits: {', '.join(sd['top_subreddits'])}")
        print(f"     Market cap: ${sd.get('market_cap', 0)/1e9:.1f}B\n")

    candidate_tickers = [c["ticker"] for c in candidates]
    assert "IONQ" in candidate_tickers, "IONQ should be in candidates"
    assert "AAPL" not in candidate_tickers, "AAPL should be excluded (mega-cap)"
    for pt in portfolio_tickers:
        assert pt not in candidate_tickers, f"{pt} should be excluded"
    for c in candidates:
        assert c["signal_data"]["mention_count"] >= 2
        assert c["signal_data"]["sample_titles"]
        assert c["source"].startswith("reddit_moonshot/")
        assert c["signal_type"] == "reddit_moonshot"

    print("  ✅ All moonshot candidates validated!")
    print("  ✅ Mega-caps excluded, portfolio tickers excluded!")
