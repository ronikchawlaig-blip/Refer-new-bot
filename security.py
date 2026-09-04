from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """Raised when Telegram Mini App initData cannot be trusted."""


@dataclass(frozen=True)
class TelegramInitData:
    user_id: int
    auth_date: int
    query_id: str | None
    user: dict


def verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 900) -> TelegramInitData:
    if not init_data or len(init_data) > 8192:
        raise InitDataError("missing init data")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed init data") from exc
    if not pairs:
        raise InitDataError("empty init data")
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise InitDataError("duplicate init data field")
    fields = dict(pairs)
    received_hash = fields.pop("hash", "")
    if len(received_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in received_hash):
        raise InitDataError("missing init data hash")
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash.lower()):
        raise InitDataError("invalid init data signature")
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("invalid auth date") from exc
    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > max_age_seconds:
        raise InitDataError("expired init data")
    try:
        user = json.loads(fields.get("user", "{}"))
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InitDataError("missing Telegram user") from exc
    if user_id <= 0:
        raise InitDataError("invalid Telegram user")
    return TelegramInitData(user_id=user_id, auth_date=auth_date, query_id=fields.get("query_id"), user=user)


def normalize_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().strip('"').strip("'")
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def privacy_hash(value: str | None, secret: str) -> str | None:
    if not value:
        return None
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def random_identifier() -> str:
    return secrets.token_urlsafe(32)


def is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def fallback_network(ip: str | None) -> tuple[str | None, str | None]:
    if not ip:
        return None, None
    try:
        address = ipaddress.ip_address(ip)
        prefix = 24 if address.version == 4 else 48
        network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
        return str(network), f"ip/{prefix}"
    except ValueError:
        return None, None


def score_risk(
    *,
    same_device_accounts: int,
    same_fingerprint_accounts: int,
    same_ip_accounts: int,
    same_network_accounts: int,
    recent_user_attempts: int,
    vpn: bool = False,
    proxy: bool = False,
    tor: bool = False,
    hosting: bool = False,
    referral_cycle: bool = False,
) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []
    if same_fingerprint_accounts:
        score += 55
        reasons.append("fingerprint linked to another Telegram account")
    if same_device_accounts:
        score += 40
        reasons.append("installation linked to another Telegram account")
    if same_ip_accounts >= 3:
        score += 12
        reasons.append("multiple accounts correlate on the same IP")
    if same_network_accounts >= 5:
        score += 10
        reasons.append("multiple accounts correlate on the same network")
    if recent_user_attempts >= 3:
        score += 20
        reasons.append("repeated verification attempts")
    if vpn:
        score += 18
        reasons.append("IP reputation indicates VPN")
    if proxy:
        score += 22
        reasons.append("IP reputation indicates proxy")
    if tor:
        score += 35
        reasons.append("IP reputation indicates Tor exit node")
    if hosting:
        score += 15
        reasons.append("IP reputation indicates hosting/datacenter network")
    if referral_cycle:
        score += 80
        reasons.append("referral graph contains a circular relationship")
    score = min(score, 100)
    if score >= 70:
        level = "high"
    elif score >= 30:
        level = "medium"
    else:
        level = "low"
    return score, level, reasons
