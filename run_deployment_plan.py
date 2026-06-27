"""Generate a capital-deployment plan and write it to data/reports/.

Usage:
    python run_deployment_plan.py                       # $100k, default mandate
    python run_deployment_plan.py --capital 250000
    python run_deployment_plan.py --target "20-30% over 12 months"
    python run_deployment_plan.py --print               # also echo to stdout

Loads .env (OPENROUTER_API_KEY) before importing anything under src.* so the
score-engine DB paths and LLM backend bind correctly.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("ALPHADESK_DATA_DIR", "data")


def main() -> None:
    parser = argparse.ArgumentParser(description="AlphaDesk capital-deployment plan")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--target", type=str, default="30-40% total return over 12 months")
    parser.add_argument("--account", type=str, default="taxable")
    parser.add_argument("--constraints", type=str, default=None)
    parser.add_argument("--print", dest="echo", action="store_true", help="echo report to stdout")
    args = parser.parse_args()

    from src.advisor.deployment_planner import DeploymentInputs, generate_deployment_plan

    inputs = DeploymentInputs(
        capital=args.capital,
        return_target=args.target,
        account_type=args.account,
    )
    if args.constraints:
        inputs.constraints = args.constraints

    print(f"Generating deployment plan for ${args.capital:,.0f} ({args.target}) …")
    result = asyncio.run(generate_deployment_plan(inputs))

    out_dir = Path(os.environ["ALPHADESK_DATA_DIR"]) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    out_path = out_dir / f"deployment_plan_{stamp}.md"
    out_path.write_text(result["markdown"], encoding="utf-8")

    print(f"\nModel: {result['model']}")
    print(f"Report written to: {out_path}  ({len(result['markdown']):,} chars)")
    if args.echo:
        print("\n" + "=" * 80 + "\n")
        print(result["markdown"])


if __name__ == "__main__":
    main()
