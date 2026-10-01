"""Shared SMTP delivery primitive used by transactional email services."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from northstar_api.email_config import EmailSettings


def smtp_send(message: EmailMessage, settings: EmailSettings) -> None:
    client: smtplib.SMTP
    if settings.smtp_ssl:
        client = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    else:
        client = smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        )
    try:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            )
        client.send_message(message)
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:
            client.close()
