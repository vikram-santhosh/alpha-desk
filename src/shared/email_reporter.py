"""Email delivery for AlphaDesk verbose reports.

Sends the verbose HTML report via SMTP email (Gmail + generic SMTP).
Gracefully degrades if not configured — silently skips when env vars missing.
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


class EmailReporter:
    """SMTP email delivery for AlphaDesk reports."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.email_to = os.getenv("REPORT_EMAIL_TO", "")
        self.email_from = os.getenv("REPORT_EMAIL_FROM", self.smtp_user)

    def is_configured(self) -> bool:
        """Check if all required email env vars are set."""
        return bool(self.smtp_user and self.smtp_pass and self.email_to)

    def send_report(
        self,
        html_content: str,
        subject: str | None = None,
        plain_text: str | None = None,
    ) -> bool:
        """Send the verbose report via email.

        Args:
            html_content: Full HTML content of the report.
            subject: Email subject (auto-generated if not provided).
            plain_text: Optional plain-text fallback.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.is_configured():
            log.debug("Email not configured — skipping delivery")
            return False

        if not subject:
            today = datetime.now().strftime("%b %d, %Y")
            subject = f"AlphaDesk Daily Report — {today}"

        recipients = [r.strip() for r in self.email_to.split(",") if r.strip()]

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = ", ".join(recipients)

        # Plain text fallback
        if plain_text:
            msg.attach(MIMEText(plain_text, "plain", "utf-8"))

        # HTML body
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            context = ssl.create_default_context()

            if self.smtp_port == 465:
                # SSL
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(self.email_from, recipients, msg.as_string())
            else:
                # STARTTLS (default for Gmail port 587)
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(self.smtp_user, self.smtp_pass)
                    server.sendmail(self.email_from, recipients, msg.as_string())

            log.info("Email report sent to %s", self.email_to)
            return True

        except smtplib.SMTPAuthenticationError:
            log.error("SMTP authentication failed. Check SMTP_USER and SMTP_PASS. "
                      "For Gmail, use an App Password: https://myaccount.google.com/apppasswords")
            return False
        except Exception:
            log.exception("Failed to send email report")
            return False

    def send_report_from_file(self, html_path: str, md_path: str | None = None) -> bool:
        """Send a report by reading from saved files.

        Args:
            html_path: Path to the HTML report file.
            md_path: Optional path to Markdown file for plain-text fallback.

        Returns:
            True if sent successfully.
        """
        from pathlib import Path

        html_file = Path(html_path)
        if not html_file.exists():
            log.error("HTML report file not found: %s", html_path)
            return False

        html_content = html_file.read_text(encoding="utf-8")

        plain_text = None
        if md_path:
            md_file = Path(md_path)
            if md_file.exists():
                plain_text = md_file.read_text(encoding="utf-8")

        return self.send_report(html_content, plain_text=plain_text)
