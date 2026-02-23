"""CLI for AlphaDesk report delivery.

Usage:
    python -m src.report --channel email --date today --preview
    python -m src.report --channel email --date 2026-02-22
    python -m src.report --preview

Options:
    --channel CHANNEL   Delivery channel: email (default: email)
    --date DATE         Report date (default: today)
    --preview           Open HTML in browser instead of sending
"""

import argparse
import os
import sys
import webbrowser
from datetime import date
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
        description="AlphaDesk Report Delivery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.report --preview                    # Open today's report in browser
  python -m src.report --channel email              # Send today's report via email
  python -m src.report --channel email --date 2026-02-22
        """,
    )
    parser.add_argument("--channel", choices=["email"], default="email",
                        help="Delivery channel (default: email)")
    parser.add_argument("--date", type=str, default="today",
                        help="Report date or 'today' (default: today)")
    parser.add_argument("--preview", action="store_true",
                        help="Open HTML in browser instead of sending")

    args = parser.parse_args()

    # Resolve date
    if args.date == "today":
        report_date = date.today().isoformat()
    else:
        report_date = args.date

    # Find report files
    report_dir = Path("reports") / report_date
    html_path = report_dir / "full_report.html"
    md_path = report_dir / "full_report.md"

    if not html_path.exists():
        print(f"No report found for {report_date}")
        print(f"Expected: {html_path}")
        print("\nRun the advisor first to generate a report:")
        print('  python -c "import asyncio; from src.advisor.main import run; asyncio.run(run())"')
        sys.exit(1)

    print(f"Found report: {html_path}")

    if args.preview:
        # Open in browser
        abs_path = html_path.resolve()
        url = f"file://{abs_path}"
        print(f"Opening in browser: {url}")
        webbrowser.open(url)
        return

    if args.channel == "email":
        from src.shared.email_reporter import EmailReporter

        reporter = EmailReporter()
        if not reporter.is_configured():
            print("Email not configured. Set these env vars:")
            print("  SMTP_HOST (default: smtp.gmail.com)")
            print("  SMTP_PORT (default: 587)")
            print("  SMTP_USER (your email)")
            print("  SMTP_PASS (your app password)")
            print("  REPORT_EMAIL_TO (recipient email)")
            print("  REPORT_EMAIL_FROM (optional, defaults to SMTP_USER)")
            sys.exit(1)

        md_str = str(md_path) if md_path.exists() else None
        success = reporter.send_report_from_file(str(html_path), md_str)

        if success:
            print(f"Report sent to {reporter.email_to}")
        else:
            print("Failed to send report. Check logs for details.")
            sys.exit(1)


if __name__ == "__main__":
    main()
