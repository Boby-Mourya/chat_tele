from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from northstar_api.config import get_settings
from northstar_api.email_config import EmailSettings, get_email_settings
from northstar_api.models import Workspace
from northstar_api.services.smtp import smtp_send

from .contracts import EmailBranding, EmailTemplate
from .store import settings_document


@dataclass(frozen=True, slots=True)
class RenderedWorkspaceEmail:
    subject: str
    text: str
    html: str
    sender_name: str
    reply_to: str | None


def published_email_branding(workspace: Workspace) -> EmailBranding | None:
    published = settings_document(workspace).branding_published
    if published is None or not published.identity.branded_emails:
        return None
    return published.email


def _replace(value: str, context: Mapping[str, str]) -> str:
    result = value
    for key, replacement in context.items():
        result = result.replace("{{" + key + "}}", replacement)
    return result


def _workspace_action_url(workspace: Workspace, action_url: str) -> str:
    """Route branded email actions through the workspace's active custom domain.

    Domain ownership/TLS activation is server-controlled, so only a domain that
    already reached the active state can replace the platform frontend host.
    The original path, query string, and fragment/token are preserved.
    """
    if not action_url:
        return ""
    document = settings_document(workspace)
    active_domain = next(
        (domain.hostname for domain in document.domains.domains if domain.status == "active"),
        "",
    )
    if not active_domain:
        return action_url
    parsed = urlsplit(action_url)
    if parsed.scheme not in {"http", "https"}:
        return action_url
    return urlunsplit(("https", active_domain, parsed.path, parsed.query, parsed.fragment))


def render_workspace_email(
    workspace: Workspace,
    template_name: str,
    *,
    context: Mapping[str, str],
    action_url: str = "",
    fallback_subject: str,
    fallback_heading: str,
    fallback_body: str,
    fallback_button_label: str = "",
) -> RenderedWorkspaceEmail:
    document = settings_document(workspace)
    published = document.branding_published
    brand = published.email if published is not None and published.identity.branded_emails else None
    identity = published.identity if published is not None and published.identity.branded_emails else None
    company_name = identity.company_name if identity and identity.company_name else "Northstar"
    action_url = _workspace_action_url(workspace, action_url) if brand is not None else action_url
    full_context = {"company_name": company_name, "workspace_name": workspace.name, **context}
    template = (
        brand.templates.get(template_name)
        if brand is not None and template_name in brand.enabled_templates
        else None
    )
    template = template or EmailTemplate(
        subject=fallback_subject,
        heading=fallback_heading,
        body=fallback_body,
        button_label=fallback_button_label,
    )
    subject = _replace(template.subject, full_context)
    heading = _replace(template.heading, full_context)
    body = _replace(template.body, full_context)
    button_label = _replace(template.button_label, full_context)
    footer = _replace(brand.footer, full_context) if brand is not None else ""
    text_parts = [heading, body]
    if action_url:
        text_parts.append(action_url)
    if footer:
        text_parts.append(footer)
    text = "\n\n".join(part for part in text_parts if part)
    safe_heading = html.escape(heading)
    safe_body = html.escape(body).replace("\n", "<br>")
    safe_url = html.escape(action_url, quote=True)
    safe_label = html.escape(button_label or action_url)
    safe_footer = html.escape(footer).replace("\n", "<br>")
    logo = html.escape(brand.logo, quote=True) if brand and brand.logo else ""
    html_parts = []
    if logo:
        html_parts.append(f'<p><img src="{logo}" alt="{html.escape(company_name)}" style="max-height:48px;max-width:220px"></p>')
    if safe_heading:
        html_parts.append(f"<h2>{safe_heading}</h2>")
    if safe_body:
        html_parts.append(f"<p>{safe_body}</p>")
    if action_url:
        html_parts.append(f'<p><a href="{safe_url}">{safe_label}</a></p>')
    if safe_footer:
        html_parts.append(f"<p><small>{safe_footer}</small></p>")
    return RenderedWorkspaceEmail(
        subject=subject,
        text=text,
        html="".join(html_parts),
        sender_name=brand.sender_name if brand and brand.sender_name else company_name,
        reply_to=str(brand.reply_to) if brand and brand.reply_to else None,
    )


async def deliver_workspace_email(
    recipient_email: str,
    rendered: RenderedWorkspaceEmail,
    *,
    settings: EmailSettings | None = None,
) -> None:
    # Import lazily: email_verification uses this branding module for its
    # templates, while both paths share the SMTP transport helper.
    from northstar_api.services.email_verification import _smtp_send

    config = settings or get_email_settings()
    if config.email_delivery_mode == "log":
        if get_settings().is_production:
            raise RuntimeError("Email delivery is not configured")
        return
    message = EmailMessage()
    message["Subject"] = rendered.subject
    message["From"] = f"{rendered.sender_name} <{config.email_from_address}>"
    message["To"] = recipient_email
    if rendered.reply_to:
        message["Reply-To"] = rendered.reply_to
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    await asyncio.to_thread(smtp_send, message, config)
