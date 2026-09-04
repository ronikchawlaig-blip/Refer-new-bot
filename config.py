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
    miniapp_url: str
    web_host: str
    web_port: int
    ipinfo_token: str
    verification_hash_secret: str
    trust_proxy: bool
    verification_max_age: int
    verification_rate_window: int
    verification_max_attempts: int
    verification_max_api_requests: int
    reputation_cache_seconds: int


def _miniapp_url() -> str:
    configured = os.getenv("MINIAPP_URL", "").strip().rstrip("/")
    if configured:
        return configured
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
        if domain:
            base = f"https://{domain}"
    return f"{base}/miniapp" if base else ""


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
        support_username=os.getenv("SUPPORT_BOT_USERNAME", "@GrabSupportbot").strip(),
        support_link=os.getenv(
            "SUPPORT_BOT_LINK", "https://t.me/GrabSupportbot"
        ).strip(),
        support_button_text=os.getenv("SUPPORT_BUTTON_TEXT", "💬 Support"),
        support_instructions=os.getenv(
            "SUPPORT_INSTRUCTIONS",
            "Tap below to open our Support Bot. Our team will respond as soon as possible.",
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        miniapp_url=_miniapp_url(),
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
        web_port=int(os.getenv("PORT", "8080") or "8080"),
        ipinfo_token=os.getenv("IPINFO_TOKEN", "").strip(),
        verification_hash_secret=os.getenv("VERIFICATION_HASH_SECRET", "").strip() or token,
        trust_proxy=os.getenv("TRUST_PROXY", "true").strip().lower() not in {"0", "false", "no"},
        verification_max_age=max(60, int(os.getenv("VERIFICATION_MAX_AGE_SECONDS", "900") or "900")),
        verification_rate_window=max(60, int(os.getenv("VERIFICATION_RATE_WINDOW_SECONDS", "3600") or "3600")),
        verification_max_attempts=max(1, int(os.getenv("VERIFICATION_MAX_ATTEMPTS", "10") or "10")),
        verification_max_api_requests=max(10, int(os.getenv("VERIFICATION_MAX_API_REQUESTS", "60") or "60")),
        reputation_cache_seconds=max(60, int(os.getenv("REPUTATION_CACHE_SECONDS", "3600") or "3600")),
    )
