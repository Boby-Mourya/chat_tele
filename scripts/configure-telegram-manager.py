"""Validate a locally supplied manager token and discover its username.

Run with backend/.venv/Scripts/python.exe scripts/configure-telegram-manager.py.
Never prints Telegram credentials or provider exception details.
"""
import asyncio
import secrets
from pathlib import Path

from dotenv import dotenv_values
from northstar_api.services.telegram import TelegramAPIError, telegram_client


async def main():
    path = Path(__file__).resolve().parents[1] / ".env"
    values = dotenv_values(path)
    token = values.get("TELEGRAM_MANAGER_BOT_TOKEN")
    if not token:
        raise SystemExit("Add TELEGRAM_MANAGER_BOT_TOKEN to .env, then run this command again.")
    identity = await telegram_client.get_me(token)
    if not identity.get("is_bot") or not identity.get("username"):
        raise SystemExit("The configured token did not identify a Telegram bot.")
    if not identity.get("can_manage_bots"):
        raise SystemExit("Enable Bot Management Mode for this bot in @BotFather, then retry.")
    updates = {"TELEGRAM_MANAGER_BOT_USERNAME": identity["username"]}
    if not values.get("TELEGRAM_MANAGER_WEBHOOK_SECRET"):
        updates["TELEGRAM_MANAGER_WEBHOOK_SECRET"] = secrets.token_urlsafe(32)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    lines = [line for line in lines if line.split("=", 1)[0].strip() not in updates]
    lines.extend(f"{key}={value}" for key, value in updates.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Manager identity verified; username and secret saved locally.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (TelegramAPIError, OSError, ValueError):
        raise SystemExit("Could not verify the manager. Check the local token and Telegram connectivity.") from None
