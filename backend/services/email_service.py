"""
CropGuard AI — Email alert service via Brevo (formerly Sendinblue).

Security
--------
CRITICAL: The Brevo API key is NEVER embedded in source code.
It is read exclusively from the BREVO_API_KEY environment variable
(or .env file, which must not be committed).

Architecture
------------
  Risk Engine
      ↓
  Alert Decision (risk_service.py)
      ↓
  FastAPI
      ↓
  email_service.send_alert()
      ↓
  Brevo Transactional Email API v3
      ↓
  Farmer Email

Flutter NEVER calls Brevo directly.

Alert deduplication
-------------------
Before sending, this service checks the alerts table for any alert
sent to the same farm_id within ALERT_COOLDOWN_HOURS.
If a recent alert exists, the email is suppressed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from backend.config import settings, ALERT_COOLDOWN_HOURS, ALERT_RISK_THRESHOLD

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _build_alert_email(
    to_email: str,
    district: str,
    risk_level: str,
    risk_probability: float,
    lat: float,
    lon: float,
    recommendation: str,
    timestamp: str,
    forecast_horizon: str = "current",
) -> Dict[str, Any]:
    """Build the Brevo email payload."""
    subject = f"CropGuard AI — {risk_level} Pest Risk Alert: {district}"

    html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:24px;border:1px solid #e0e0e0;border-radius:8px;">
  <h2 style="color:#2e7d32;">🌾 CropGuard AI — Pest Risk Alert</h2>
  <p>Your registered farm has entered <strong>{risk_level}</strong> pest-risk conditions.</p>

  <table style="width:100%;border-collapse:collapse;margin:16px 0;">
    <tr><td style="padding:8px;font-weight:bold;width:40%;">District</td><td style="padding:8px;">{district}</td></tr>
    <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Risk Level</td><td style="padding:8px;color:{'#c62828' if risk_level in ('HIGH','CRITICAL') else '#e65100'};">{risk_level}</td></tr>
    <tr><td style="padding:8px;font-weight:bold;">Risk Probability</td><td style="padding:8px;">{risk_probability:.0%}</td></tr>
    <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Forecast</td><td style="padding:8px;">{forecast_horizon}</td></tr>
    <tr><td style="padding:8px;font-weight:bold;">Location</td><td style="padding:8px;">{lat:.4f}° N, {lon:.4f}° E</td></tr>
    <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Updated</td><td style="padding:8px;">{timestamp}</td></tr>
  </table>

  <div style="background:#fff3e0;border-left:4px solid #ff6f00;padding:12px;margin:16px 0;">
    <strong>Recommended Action:</strong><br>
    {recommendation}
  </div>

  <p style="font-size:12px;color:#757575;margin-top:24px;">
    This is an AI-assisted early-warning alert, not a confirmed pest diagnosis.
    Please contact your local agricultural extension officer if symptoms are observed.
    <br><br>
    CropGuard AI — Punjab Pest Outbreak Early Warning System
  </p>
</div>
"""

    text_body = f"""CropGuard AI — Pest Risk Alert

Your registered farm has entered {risk_level} pest-risk conditions.

District:          {district}
Risk:              {risk_probability:.0%}
Forecast:          {forecast_horizon}
Recommended action: {recommendation}
Location:          {lat:.4f}, {lon:.4f}
Updated:           {timestamp}

This is an AI-assisted early-warning alert, not a confirmed pest diagnosis.
Contact your local agricultural extension officer if symptoms are observed.
"""

    return {
        "sender": {
            "name":  settings.brevo_sender_name,
            "email": settings.brevo_sender_email,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }


async def send_alert_email(
    to_email: str,
    district: str,
    risk_level: str,
    risk_probability: float,
    lat: float,
    lon: float,
    recommendation: str = "Increase field monitoring and contact your local agricultural extension officer if symptoms are observed.",
    timestamp: Optional[str] = None,
    forecast_horizon: str = "current",
) -> bool:
    """
    Send a pest-risk alert email via Brevo.

    Returns True on success, False on failure.

    Never raises — failures are logged and suppressed so they don't
    crash the main request flow.
    """
    if not settings.brevo_api_key:
        logger.warning("BREVO_API_KEY not configured. Email not sent to %s.", to_email)
        return False

    if not settings.brevo_sender_email:
        logger.warning("BREVO_SENDER_EMAIL not configured. Email not sent.")
        return False

    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    payload = _build_alert_email(
        to_email, district, risk_level, risk_probability,
        lat, lon, recommendation, timestamp, forecast_horizon,
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                BREVO_API_URL,
                json=payload,
                headers={
                    "api-key":      settings.brevo_api_key,
                    "Content-Type": "application/json",
                    "Accept":       "application/json",
                },
            )
            if resp.status_code in (200, 201):
                logger.info("Alert email sent to %s (risk=%s).", to_email, risk_level)
                return True
            else:
                logger.error(
                    "Brevo API error %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
    except Exception as exc:
        logger.error("Email send failed for %s: %s", to_email, exc)
        return False


async def check_and_send_alert(
    db_session: Any,
    farm_id: int,
    to_email: str,
    district: str,
    risk_level: str,
    risk_probability: float,
    lat: float,
    lon: float,
    recommendation: str = "Increase field monitoring.",
) -> bool:
    """
    Full alert flow with deduplication:
    1. Check if risk crosses threshold.
    2. Check if a recent alert was already sent.
    3. Send email.
    4. Record alert in database.
    """
    from sqlalchemy import select
    from backend.database.models import Alert

    # Step 1: threshold check
    if risk_probability < ALERT_RISK_THRESHOLD:
        return False

    # Step 2: deduplication
    cooldown_cutoff = datetime.utcnow() - timedelta(hours=ALERT_COOLDOWN_HOURS)
    stmt = (
        select(Alert)
        .where(Alert.farm_id == farm_id)
        .where(Alert.sent_at >= cooldown_cutoff)
        .limit(1)
    )
    result = await db_session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        logger.debug("Alert suppressed for farm %d (cooldown active).", farm_id)
        return False

    # Step 3: send
    success = await send_alert_email(
        to_email=to_email,
        district=district,
        risk_level=risk_level,
        risk_probability=risk_probability,
        lat=lat,
        lon=lon,
        recommendation=recommendation,
    )

    # Step 4: record regardless of send success (to prevent spam on API failures)
    alert = Alert(
        farm_id=farm_id,
        risk_level=risk_level,
        risk_probability=risk_probability,
        message=recommendation,
        alert_type="risk_threshold",
    )
    db_session.add(alert)
    await db_session.commit()

    return success
