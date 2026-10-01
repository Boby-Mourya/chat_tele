"""Run once: python -m northstar_api.services.telegram_manager_setup."""

import asyncio

from northstar_api.config import get_settings
from northstar_api.services.telegram import TelegramAPIError, telegram_client
from northstar_api.services.telegram_provisioning import current_public_base, manager_config


async def setup() -> None:
    token, username, secret = manager_config()
    identity = await telegram_client.get_me(token)
    if identity.get("username", "").lower() != username.lower() or not identity.get("can_manage_bots"):
        raise TelegramAPIError("Verify manager username and enable Bot Management Mode in BotFather")
    url = f"{await current_public_base()}{get_settings().app_api_prefix}/webhooks/telegram/manager"
    await telegram_client.set_webhook(
        token, url=url, secret_token=secret, allowed_updates=["message", "managed_bot", "callback_query"]
    )
    if (await telegram_client.get_webhook_info(token)).get("url") != url:
        raise TelegramAPIError("Manager webhook verification failed")
    print("Telegram manager webhook registered and verified.")


if __name__ == "__main__":
    try:
        asyncio.run(setup())
    except Exception:
        # Do not print credential-bearing HTTP exception chains.
        raise SystemExit(
            "Manager setup failed. Check manager settings, management mode, and public HTTPS connectivity."
        ) from None
