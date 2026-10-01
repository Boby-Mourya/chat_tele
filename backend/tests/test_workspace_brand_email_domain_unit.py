from __future__ import annotations

from email.message import EmailMessage
from uuid import uuid4

from northstar_api.email_config import EmailSettings
from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import DomainRecord, ExtendedBranding, WorkspaceSettingsBundle
from northstar_api.modules.workspace.email_branding import render_workspace_email
from northstar_api.services import smtp as smtp_service


def test_branded_email_action_uses_only_active_custom_domain() -> None:
    bundle = WorkspaceSettingsBundle()
    published = ExtendedBranding()
    published.identity.company_name = "Acme Academy"
    published.identity.branded_emails = True
    bundle.branding_published = published
    bundle.domains.domains = [
        DomainRecord(
            hostname="portal.acme.example",
            verification_name="_northstar-verify.portal.acme.example",
            verification_value="verified-token",
            status="active",
        )
    ]
    workspace = Workspace(
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={"workspaceSettingsV2": bundle.model_dump(by_alias=True, mode="json")},
    )

    rendered = render_workspace_email(
        workspace,
        "password_reset",
        context={},
        action_url="https://app.northstar.example/reset-password#token=secret",
        fallback_subject="Reset",
        fallback_heading="Reset",
        fallback_body="Reset your password",
        fallback_button_label="Reset password",
    )

    assert "https://portal.acme.example/reset-password#token=secret" in rendered.text
    assert "app.northstar.example" not in rendered.text


def test_branded_email_keeps_platform_url_until_domain_is_active() -> None:
    bundle = WorkspaceSettingsBundle()
    published = ExtendedBranding()
    published.identity.branded_emails = True
    bundle.branding_published = published
    bundle.domains.domains = [
        DomainRecord(
            hostname="portal.acme.example",
            verification_name="_northstar-verify.portal.acme.example",
            verification_value="verified-token",
            status="verified",
        )
    ]
    workspace = Workspace(
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={"workspaceSettingsV2": bundle.model_dump(by_alias=True, mode="json")},
    )

    rendered = render_workspace_email(
        workspace,
        "email_verification",
        context={},
        action_url="https://app.northstar.example/verify-email#token=secret",
        fallback_subject="Verify",
        fallback_heading="Verify",
        fallback_body="Verify your email",
        fallback_button_label="Verify email",
    )

    assert "https://app.northstar.example/verify-email#token=secret" in rendered.text


def test_smtp_send_uses_starttls_authentication_and_closes_connection(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def starttls(self) -> None:
            calls.append(("starttls", None))

        def login(self, username: str, password: str) -> None:
            calls.append(("login", (username, password)))

        def send_message(self, message: EmailMessage) -> None:
            calls.append(("send", message["Subject"]))

        def quit(self) -> None:
            calls.append(("quit", None))

        def close(self) -> None:
            calls.append(("close", None))

    monkeypatch.setattr(smtp_service.smtplib, "SMTP", lambda *args, **kwargs: FakeClient())
    message = EmailMessage()
    message["Subject"] = "Verify"
    settings = EmailSettings(
        email_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_username="mailer",
        smtp_password="secret",
        smtp_starttls=True,
        smtp_ssl=False,
    )

    smtp_service.smtp_send(message, settings)

    assert calls == [
        ("starttls", None),
        ("login", ("mailer", "secret")),
        ("send", "Verify"),
        ("quit", None),
    ]


def test_smtp_send_ssl_does_not_starttls_or_login_without_credentials(monkeypatch) -> None:
    calls: list[str] = []

    class FakeClient:
        def starttls(self) -> None:
            calls.append("starttls")

        def login(self, username: str, password: str) -> None:
            calls.append("login")

        def send_message(self, message: EmailMessage) -> None:
            calls.append("send")

        def quit(self) -> None:
            calls.append("quit")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(smtp_service.smtplib, "SMTP_SSL", lambda *args, **kwargs: FakeClient())
    message = EmailMessage()
    settings = EmailSettings(
        email_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_ssl=True,
        smtp_starttls=False,
    )

    smtp_service.smtp_send(message, settings)

    assert calls == ["send", "quit"]
