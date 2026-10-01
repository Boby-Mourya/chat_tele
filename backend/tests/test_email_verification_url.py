from __future__ import annotations

from northstar_api.email_config import EmailSettings
from northstar_api.services.email_verification import verification_url


def test_verification_url_uses_browser_fragment_for_token() -> None:
    settings = EmailSettings(
        email_verification_frontend_url="https://app.example.com/verify-email?source=signup"
    )

    url = verification_url("token-value-with_url-safe.characters", settings)

    assert url.startswith("https://app.example.com/verify-email?source=signup#token=")
    assert "?token=" not in url
    assert "&token=" not in url.split("#", 1)[0]
