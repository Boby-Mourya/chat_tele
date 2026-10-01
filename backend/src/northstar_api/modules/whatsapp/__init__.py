"""Canonical WhatsApp feature boundary.

The legacy service modules remain import-compatible while callers migrate to this
feature-owned namespace. Keeping the exports here prevents routers and workers
from growing a second provider contract during the staged reorganization.
"""

from .accounts import account_client, connection_client
from .graph import (
    MAX_WHATSAPP_TEXT_LENGTH,
    REQUIRED_SCOPES,
    TRANSIENT_META_ERROR_CODES,
    MetaTokenCipher,
    WhatsAppCloudClient,
    WhatsAppConfigurationError,
    WhatsAppGraphError,
    WhatsAppSetup,
    split_whatsapp_text,
    token_cipher,
    token_expiry_is_current,
    whatsapp_client,
)
from .messages import format_whatsapp_reply
from .status import attach_contact_details, attach_whatsapp_message_status, delivery_status
from .templates import build_template, template_fields

__all__ = [
    "MAX_WHATSAPP_TEXT_LENGTH",
    "REQUIRED_SCOPES",
    "TRANSIENT_META_ERROR_CODES",
    "MetaTokenCipher",
    "WhatsAppCloudClient",
    "WhatsAppConfigurationError",
    "WhatsAppGraphError",
    "WhatsAppSetup",
    "account_client",
    "attach_contact_details",
    "attach_whatsapp_message_status",
    "build_template",
    "connection_client",
    "delivery_status",
    "format_whatsapp_reply",
    "split_whatsapp_text",
    "token_cipher",
    "template_fields",
    "token_expiry_is_current",
    "whatsapp_client",
]
