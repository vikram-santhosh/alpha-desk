"""CLI for AlphaDesk backtesting.

Usage:
    python -m src.backtest --days 5 --skip-committee
    python -m src.backtest --days 30 --portfolio config/portfolio.yaml --dry-run

Options:
    --days N            Number of trading days to backtest (default: 5)
    --skip-committee    Skip analyst committee LLM calls (near-zero API cost)
    --portfolio PATH    Custom portfolio YAML file
    --output DIR        Custom output directory
    --dry-run           Print config and exit without running
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Setup project path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser(
        description="AlphaDesk Backtesting Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.backtest --days 5 --skip-committee
  python -m src.backtest --days 30 --portfolio private/portfolio.yaml
  python -m src.backtest --days 10 --output backtests/custom_run
        """,
    )
    parser.add_argument("--days", type=int, default=5,
                        help="Number of trading days to backtest (default: 5)")
    parser.add_argument("--skip-committee", action="store_true",
                        help="Skip analyst committee LLM calls (near-zero API cost)")
    parser.add_argument("--portfolio", type=str, default=None,
                        help="Custom portfolio YAML file")
    parser.add_argument("--output", type=str, default=None,
                        help="Custom output directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print config and exit without running")
    parser.add_argument("--skip-agents", type=str, nargs="*",
                        default=["street_ear", "news_desk"],
                        help="Agents to skip (default: street_ear news_desk)")

    args = parser.parse_args()

    # Validate
    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not set. Add it to .env or environment.")
        sys.exit(1)

    if args.portfolio and not Path(args.portfolio).exists():
        print(f"ERROR: Portfolio file not found: {args.portfolio}")
        sys.exit(1)

    # Build runner
    from src.backtest.runner import BacktestRunner

    runner = BacktestRunner(
        num_days=args.days,
        skip_committee=args.skip_committee,
        skip_agents=args.skip_agents,
        dry_run=args.dry_run,
        output_dir=args.output,
        portfolio_config=args.portfolio,
    )

    if args.dry_run:
        print("\nDry run — configuration:")
        print(f"  Days: {args.days}")
        print(f"  Skip committee: {args.skip_committee}")
        print(f"  Skip agents: {args.skip_agents}")
        print(f"  Portfolio: {args.portfolio or 'config/advisor.yaml (default)'}")
        print(f"  Output: {args.output or 'backtests/{date}/'}")
        print("\nEstimated cost:")
        if args.skip_committee:
            print(f"  ~$0.10-0.50 (rule-based only, no LLM calls)")
        else:
            print(f"  ~${args.days * 0.60:.2f}-${args.days * 0.80:.2f} ({args.days} days x $0.60-0.80/day)")
        return

    # Run
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
