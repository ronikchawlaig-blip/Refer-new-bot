from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    token: str
    database_url: str
    owner_id: int
    bot_name: str
    support_username: str
    support_link: str
    support_button_text: str
    support_instructions: str
    log_level: str


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing")
    if owner_id <= 0:
        raise RuntimeError("OWNER_TELEGRAM_ID must be a valid Telegram user ID")
    return Settings(
        token=token,
        database_url=database_url,
        owner_id=owner_id,
        bot_name=os.getenv("BOT_NAME", "Refer & Earn"),
        support_username=os.getenv("SUPPORT_BOT_USERNAME", "@Referrsupportt_bot").strip(),
        support_link=os.getenv(
            "SUPPORT_BOT_LINK", "https://t.me/Referrsupportt_bot"
        ).strip(),
        support_button_text=os.getenv("SUPPORT_BUTTON_TEXT", "💬 Support"),
        support_instructions=os.getenv(
            "SUPPORT_INSTRUCTIONS",
            "Tap below to open our Support Bot. Our team will respond as soon as possible.",
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
