"""
PROBOARD — Automated Alert Daemon
====================================
Standalone script (cron-schedulable) that emails personalised
reminders to at-risk students.  Uses ``smtplib`` over TLS with
full HTML-escaping and an ``email_log`` idempotency table to
prevent duplicate sends.

Usage
-----
::

    python notifier.py          # send alerts for today
    python notifier.py --dry    # preview without sending
"""

from __future__ import annotations

import argparse
import html
import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)
from database import get_session, init_db
from analytics import build_leaderboard, get_at_risk
from models import EmailLog

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Email Template
# ---------------------------------------------------------------------------
_SUBJECT = "PROBOARD Alert: Your Coding Progress Needs Attention"

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; color: #222;">
  <h2 style="color: #c0392b;">⚠️ Coding Progress Alert</h2>
  <p>Dear <strong>{name}</strong>,</p>
  <p>
    Our automated tracking system has flagged your profile for
    attention. Here is a summary:
  </p>
  <table style="border-collapse:collapse; margin:12px 0;" cellpadding="6">
    <tr style="background:#f8d7da;">
      <td><strong>Roll No</strong></td><td>{roll_no}</td>
    </tr>
    <tr>
      <td><strong>LeetCode Solved</strong></td><td>{lc_total}</td>
    </tr>
    <tr style="background:#f8d7da;">
      <td><strong>HackerRank Score</strong></td><td>{hr_score}</td>
    </tr>
    <tr>
      <td><strong>7-Day Velocity</strong></td><td>{velocity}</td>
    </tr>
    <tr style="background:#f8d7da;">
      <td><strong>Reason</strong></td><td>{reason}</td>
    </tr>
  </table>
  <p>
    Please log in to <a href="https://leetcode.com">LeetCode</a> or
    <a href="https://hackerrank.com">HackerRank</a> and solve at
    least a few problems this week.
  </p>
  <p style="color:#888; font-size:12px;">
    This is an automated message from PROBOARD. Do not reply.
  </p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Idempotency Check
# ---------------------------------------------------------------------------
def _already_sent_today(session, roll_no: str, today: date) -> bool:
    """Return True if an email was already logged for this student today."""
    return (
        session.query(EmailLog)
        .filter_by(date=today, roll_no=roll_no)
        .first()
        is not None
    )


def _log_sent(session, roll_no: str, today: date) -> None:
    """Record that an email was sent."""
    session.add(EmailLog(date=today, roll_no=roll_no))
    session.commit()


# ---------------------------------------------------------------------------
# Send One Email
# ---------------------------------------------------------------------------
def _send_email(
    smtp: smtplib.SMTP,
    to_addr: str,
    name: str,
    roll_no: str,
    lc_total: int,
    hr_score: float,
    velocity: float,
    reason: str,
) -> None:
    """Compose and send a single alert email (HTML-escaped)."""
    body = _HTML_TEMPLATE.format(
        name=html.escape(str(name)),
        roll_no=html.escape(str(roll_no)),
        lc_total=html.escape(str(lc_total)),
        hr_score=html.escape(str(hr_score)),
        velocity=html.escape(str(velocity)),
        reason=html.escape(str(reason)),
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = _SUBJECT
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "html", "utf-8"))

    smtp.send_message(msg)
    logger.info("Sent alert → %s (%s)", to_addr, roll_no)


# ---------------------------------------------------------------------------
# Main Daemon Entry Point
# ---------------------------------------------------------------------------
def run_alerts(dry_run: bool = False) -> int:
    """
    Identify at-risk students and send personalised emails.

    Parameters
    ----------
    dry_run : bool
        If True, log what *would* be sent without actually sending.

    Returns
    -------
    int
        Number of emails sent (or would-be-sent in dry mode).
    """
    init_db()
    session = get_session()
    today = date.today()

    leaderboard = build_leaderboard(session, snapshot_date=today)
    if leaderboard.empty:
        logger.warning("No leaderboard data — nothing to send.")
        return 0

    at_risk = get_at_risk(leaderboard)
    if at_risk.empty:
        logger.info("No at-risk students today. 🎉")
        return 0

    sent_count = 0
    smtp: smtplib.SMTP | None = None

    try:
        if not dry_run:
            if not SMTP_USER or not SMTP_PASSWORD:
                logger.error(
                    "SMTP credentials not configured. "
                    "Set SMTP_USER and SMTP_PASSWORD in .env"
                )
                return 0
            smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)

        for _, row in at_risk.iterrows():
            roll_no = row["roll_no"]
            email = row.get("email")

            if not email:
                logger.warning("No email for %s — skipping.", roll_no)
                continue

            # Idempotency gate
            if _already_sent_today(session, roll_no, today):
                logger.info("Already sent to %s today — skipping.", roll_no)
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] Would send to %s (%s) — %s",
                    email,
                    roll_no,
                    row.get("risk_reason", ""),
                )
            else:
                _send_email(
                    smtp,  # type: ignore[arg-type]
                    to_addr=email,
                    name=row.get("name", "Student"),
                    roll_no=roll_no,
                    lc_total=int(row.get("lc_total", 0)),
                    hr_score=float(row.get("hr_score", 0)),
                    velocity=float(row.get("velocity_7d", 0)),
                    reason=row.get("risk_reason", ""),
                )
                _log_sent(session, roll_no, today)

            sent_count += 1

    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", exc)
    finally:
        if smtp is not None:
            smtp.quit()
        session.close()

    logger.info(
        "%s %d alert(s) for %s.",
        "Would send" if dry_run else "Sent",
        sent_count,
        today,
    )
    return sent_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PROBOARD Alert Daemon")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Preview emails without sending.",
    )
    args = parser.parse_args()
    run_alerts(dry_run=args.dry)
