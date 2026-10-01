from __future__ import annotations

import asyncio
import html
from email.message import EmailMessage
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.email_config import get_email_settings
from northstar_api.onboarding_contract import SetupContract
from northstar_api.security import Principal
from northstar_api.services.email_verification import _smtp_send

from .contracts import EmailBranding, EmailTemplate
from .store import load_workspace, settings_document

router = APIRouter()
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]


class EmailPreviewRequest(SetupContract):
    template_name: str = Field(min_length=2, max_length=80)
    email: EmailBranding


class EmailPreviewResponse(SetupContract):
    subject: str
    text: str
    html: str


class EmailTestRequest(EmailPreviewRequest):
    recipient: EmailStr


def _interactive(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding session required")


def _template(email: EmailBranding, name: str) -> EmailTemplate:
    if name not in email.enabled_templates:
        raise HTTPException(status_code=422, detail="Enable this email template before previewing or testing it")
    value = email.templates.get(name)
    if value is None:
        raise HTTPException(status_code=422, detail="Email template is not configured")
    return value


def _render(email: EmailBranding, template_name: str, company_name: str, workspace_name: str) -> EmailPreviewResponse:
    template = _template(email, template_name)
    replacements = {"{{company_name}}": company_name, "{{workspace_name}}": workspace_name, "{{inviter_name}}": "Workspace administrator"}
    def fill(value: str) -> str:
        for key, replacement in replacements.items():
            value = value.replace(key, replacement)
        return value
    subject = fill(template.subject)
    heading = fill(template.heading)
    body = fill(template.body)
    button = fill(template.button_label)
    footer = fill(email.footer)
    text = "\n\n".join(part for part in (heading, body, "https://example.invalid/action" if button else "", footer) if part)
    logo = html.escape(email.logo, quote=True) if email.logo else ""
    markup = ""
    if logo:
        markup += f'<p><img src="{logo}" alt="{html.escape(company_name)}" style="max-height:48px;max-width:220px"></p>'
    markup += f"<h2>{html.escape(heading)}</h2><p>{html.escape(body).replace(chr(10), '<br>')}</p>"
    if button:
        markup += f'<p><a href="https://example.invalid/action">{html.escape(button)}</a></p>'
    if footer:
        markup += f"<p><small>{html.escape(footer)}</small></p>"
    return EmailPreviewResponse(subject=subject, text=text, html=markup)


@router.post("/branding/email/preview", response_model=EmailPreviewResponse)
async def preview_email(
    payload: EmailPreviewRequest,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> EmailPreviewResponse:
    _interactive(principal)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    company_name = document.branding_draft.identity.company_name or workspace.name
    return _render(payload.email, payload.template_name, company_name, workspace.name)


@router.post("/branding/email/test", response_model=EmailPreviewResponse)
async def test_email(
    payload: EmailTestRequest,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> EmailPreviewResponse:
    _interactive(principal)
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    company_name = document.branding_draft.identity.company_name or workspace.name
    rendered = _render(payload.email, payload.template_name, company_name, workspace.name)
    config = get_email_settings()
    if config.email_delivery_mode == "log":
        if get_settings().is_production:
            raise HTTPException(status_code=503, detail="Email delivery is not configured")
        return rendered
    message = EmailMessage()
    message["Subject"] = f"[Brand test] {rendered.subject}"
    message["From"] = f"{payload.email.sender_name or company_name} <{config.email_from_address}>"
    message["To"] = str(payload.recipient)
    if payload.email.reply_to:
        message["Reply-To"] = str(payload.email.reply_to)
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    await asyncio.to_thread(_smtp_send, message, config)
    return rendered
