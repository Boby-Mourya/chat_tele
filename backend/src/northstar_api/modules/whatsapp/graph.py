"""WhatsApp provider contract during the staged feature migration."""

from northstar_api.services.whatsapp import (
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

__all__ = [
    "MAX_WHATSAPP_TEXT_LENGTH",
    "REQUIRED_SCOPES",
    "TRANSIENT_META_ERROR_CODES",
    "MetaTokenCipher",
    "WhatsAppCloudClient",
    "WhatsAppConfigurationError",
    "WhatsAppGraphError",
    "WhatsAppSetup",
    "split_whatsapp_text",
    "token_cipher",
    "token_expiry_is_current",
    "whatsapp_client",
]
