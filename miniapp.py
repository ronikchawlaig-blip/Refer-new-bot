from __future__ import annotations

import asyncio
import json
import logging
import base64
import zlib
from typing import Any
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout, web

from db import Database
from security import (
    InitDataError,
    fallback_network,
    is_sha256,
    normalize_ip,
    privacy_hash,
    random_identifier,
    score_risk,
    verify_telegram_init_data,
)


log = logging.getLogger(__name__)
COOKIE_NAME = "refer_device_install"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


MINIAPP_HTML = zlib.decompress(base64.b64decode("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")).decode("utf-8")


class MiniAppServer:
    def __init__(
        self,
        db: Database,
        bot_token: str,
        hash_secret: str,
        ipinfo_token: str = "",
        trust_proxy: bool = True,
        max_init_data_age: int = 900,
        rate_window_seconds: int = 3600,
        max_user_attempts: int = 10,
        max_api_requests: int = 60,
        reputation_cache_seconds: int = 3600,
    ) -> None:
        self.db = db
        self.bot_token = bot_token
        self.hash_secret = hash_secret
        self.ipinfo_token = ipinfo_token
        self.trust_proxy = trust_proxy
        self.max_init_data_age = max_init_data_age
        self.rate_window_seconds = rate_window_seconds
        self.max_user_attempts = max_user_attempts
        self.max_api_requests = max_api_requests
        self.reputation_cache_seconds = reputation_cache_seconds
        self._reputation_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self, host: str, port: int) -> None:
        app = web.Application()
        app.router.add_get("/healthz", self.health)
        app.router.add_get("/miniapp", self.miniapp)
        app.router.add_post("/api/verification/start", self.start_verification)
        app.router.add_post("/api/verification/complete", self.complete_verification)
        app.router.add_post("/api/verification/status", self.verification_status)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()
        log.info("Telegram Mini App server listening on %s:%s", host, port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    @staticmethod
    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def miniapp(self, request: web.Request) -> web.Response:
        response = web.Response(text=MINIAPP_HTML, content_type="text/html")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://telegram.org 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org; base-uri 'none'"
        if not request.cookies.get(COOKIE_NAME):
            response.set_cookie(COOKIE_NAME, random_identifier(), max_age=COOKIE_MAX_AGE, httponly=True, secure=True, samesite="Lax")
        return response

    def _client_ip(self, request: web.Request) -> str | None:
        if self.trust_proxy:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                for candidate in forwarded.split(","):
                    normalized = normalize_ip(candidate)
                    if normalized:
                        return normalized
        return normalize_ip(request.remote)

    async def _json(self, request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise web.HTTPBadRequest(text=json.dumps({"message": "Invalid request."}), content_type="application/json") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text=json.dumps({"message": "Invalid request."}), content_type="application/json")
        return body

    async def _api_allowed(self, request: web.Request, ip: str | None) -> bool:
        key = privacy_hash("api:" + (ip or "unknown"), self.hash_secret) or "api:unknown"
        return await self.db.consume_rate_limit(key, self.max_api_requests, self.rate_window_seconds)

    async def _lookup_reputation(self, ip: str | None) -> dict[str, Any]:
        if not ip:
            return {"status": "unavailable", "network": None, "network_label": None}
        now = asyncio.get_running_loop().time()
        cached = self._reputation_cache.get(ip)
        if cached and now - cached[0] < self.reputation_cache_seconds:
            return cached[1]
        result: dict[str, Any] = {"status": "not_configured", "network": None, "network_label": None}
        if self.ipinfo_token:
            try:
                timeout = ClientTimeout(total=2.5)
                url = "https://ipinfo.io/" + ip + "/json?token=" + self.ipinfo_token
                async with ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            payload = await response.json(content_type=None)
                            privacy = payload.get("privacy") or {}
                            asn = str((payload.get("asn") or {}).get("asn") or "").strip()
                            org = str(payload.get("org") or "").strip()
                            result = {
                                "status": "available",
                                "vpn": bool(privacy.get("vpn")), "proxy": bool(privacy.get("proxy")),
                                "tor": bool(privacy.get("tor")), "hosting": bool(privacy.get("hosting")),
                                "network": asn or org or None, "network_label": asn or (org[:80] if org else None),
                            }
                        else:
                            result["status"] = "unavailable"
            except Exception:
                log.warning("IP reputation provider unavailable", exc_info=True)
                result["status"] = "unavailable"
        if not result.get("network"):
            fallback, label = fallback_network(ip)
            result["network"] = fallback
            result["network_label"] = label
        self._reputation_cache[ip] = (now, result)
        return result

    @staticmethod
    def _error(message: str, status: int = 400) -> web.Response:
        return web.json_response({"message": message}, status=status, headers={"Cache-Control": "no-store"})

    async def _verified_request(self, request: web.Request) -> tuple[dict[str, Any], int, str, str, str | None, str, str] | web.Response:
        body = await self._json(request)
        init_data = body.get("init_data")
        try:
            verified = verify_telegram_init_data(str(init_data or ""), self.bot_token, self.max_init_data_age)
        except InitDataError as exc:
            log.warning("Telegram init data rejected: %s", exc)
            message = (
                "Telegram session expired. Reopen Verify Device from the bot."
                if str(exc) == "expired init data"
                else "Telegram session signature could not be verified. Open the Mini App from the bot."
            )
            return self._error(message, 401)
        fingerprint_hash = str(body.get("fingerprint_hash") or "").lower()
        if not is_sha256(fingerprint_hash):
            return self._error("Verification data is invalid. Please try again.")
        client_nonce = str(body.get("client_nonce") or "")
        try:
            UUID(client_nonce)
        except (ValueError, TypeError, AttributeError):
            return self._error("Verification data is invalid. Please try again.")
        user = await self.db.get_user(verified.user_id)
        if not user or user["banned"]:
            return self._error("Open the bot with /start before verifying this device.", 403)
        ip = self._client_ip(request)
        install_id = request.cookies.get(COOKIE_NAME) or random_identifier()
        return (user, verified.user_id, fingerprint_hash.lower() or "missing", client_nonce or random_identifier(), ip, install_id, str(init_data or ""))

    async def start_verification(self, request: web.Request) -> web.Response:
        ip = self._client_ip(request)
        if not await self._api_allowed(request, ip):
            return self._error("Too many verification requests. Please wait and try again.", 429)
        verified_request = await self._verified_request(request)
        if isinstance(verified_request, web.Response):
            return verified_request
        user, user_id, fingerprint_hash, client_nonce, ip, install_id, init_data = verified_request
        user_key = privacy_hash("user:" + str(user_id), self.hash_secret) or "user:unknown"
        if not await self.db.consume_rate_limit(user_key, self.max_user_attempts, self.rate_window_seconds):
            return self._error("Too many verification attempts. Please wait before trying again.", 429)
        reputation = await self._lookup_reputation(ip)
        network_hash = privacy_hash("network:" + str(reputation.get("network") or "unknown"), self.hash_secret)
        risk_context = await self.db.verification_risk_context(
            user_id=user_id,
            install_hash=privacy_hash(install_id, self.hash_secret) or "missing",
            fingerprint_hash=fingerprint_hash,
            ip_hash=privacy_hash(ip, self.hash_secret),
            network_hash=network_hash,
        )
        limit_values = [("device", privacy_hash(install_id, self.hash_secret)), ("ip", privacy_hash(ip, self.hash_secret)), ("network", network_hash)]
        if fingerprint_hash != "missing":
            limit_values.append(("fingerprint", fingerprint_hash))
        for scope, value in limit_values:
            if value and not await self.db.consume_rate_limit(
                privacy_hash("attempt:" + scope + ":" + value, self.hash_secret) or scope,
                self.max_user_attempts,
                self.rate_window_seconds,
            ):
                return self._error("Too many verification attempts. Please wait before trying again.", 429)
        if risk_context.get("referrer_id") and not await self.db.consume_rate_limit(
            privacy_hash("referral:" + str(risk_context["referrer_id"]), self.hash_secret) or "referral",
            self.max_user_attempts,
            self.rate_window_seconds,
        ):
            return self._error("Too many referral verification attempts. Please wait before trying again.", 429)
        score, level, reasons = score_risk(
            same_device_accounts=risk_context["same_device_accounts"],
            same_fingerprint_accounts=risk_context["same_fingerprint_accounts"],
            same_ip_accounts=risk_context["same_ip_accounts"],
            same_network_accounts=risk_context["same_network_accounts"],
            recent_user_attempts=risk_context["recent_user_attempts"],
            vpn=bool(reputation.get("vpn")), proxy=bool(reputation.get("proxy")),
            tor=bool(reputation.get("tor")), hosting=bool(reputation.get("hosting")),
            referral_cycle=risk_context["referral_cycle"],
        )
        session_token = random_identifier()
        await self.db.create_verification_attempt(
            session_hash=privacy_hash(session_token, self.hash_secret) or "",
            init_data_hash=privacy_hash(init_data, self.hash_secret) or "",
            user_id=user_id,
            install_hash=privacy_hash(install_id, self.hash_secret),
            fingerprint_hash=fingerprint_hash if fingerprint_hash != "missing" else None,
            ip_hash=privacy_hash(ip, self.hash_secret),
            network_hash=network_hash,
            network_label=reputation.get("network_label"),
            provider_status=str(reputation.get("status") or "unavailable"),
            provider_flags={key: bool(reputation.get(key)) for key in ("vpn", "proxy", "tor", "hosting")},
            risk_score=score,
            risk_level=level,
            risk_reasons=reasons,
            expires_seconds=self.max_init_data_age,
        )
        response = web.json_response({"session_token": session_token, "status": "ready"}, headers={"Cache-Control": "no-store"})
        if not request.cookies.get(COOKIE_NAME):
            response.set_cookie(COOKIE_NAME, install_id, max_age=COOKIE_MAX_AGE, httponly=True, secure=True, samesite="Lax")
        return response

    async def complete_verification(self, request: web.Request) -> web.Response:
        ip = self._client_ip(request)
        if not await self._api_allowed(request, ip):
            return self._error("Too many verification requests. Please wait and try again.", 429)
        body = await self._json(request)
        token = str(body.get("session_token") or "")
        init_data = str(body.get("init_data") or "")
        fingerprint_hash = str(body.get("fingerprint_hash") or "").lower()
        install_id = request.cookies.get(COOKIE_NAME)
        if not token or len(token) > 256 or not is_sha256(fingerprint_hash):
            return self._error("Verification data is invalid. Reopen the Mini App.", 400)
        if not install_id:
            return self._error("The verification browser session was not preserved. Close and reopen Verify Device from the bot.", 400)
        try:
            verified = verify_telegram_init_data(init_data, self.bot_token, self.max_init_data_age)
        except InitDataError as exc:
            log.warning("Telegram init data rejected: %s", exc)
            message = (
                "Telegram session expired. Reopen Verify Device from the bot."
                if str(exc) == "expired init data"
                else "Telegram session signature could not be verified. Open the Mini App from the bot."
            )
            return self._error(message, 401)
        result = await self.db.finish_verification(
            privacy_hash(token, self.hash_secret) or "",
            verified.user_id,
            privacy_hash(init_data, self.hash_secret) or "",
            privacy_hash(install_id, self.hash_secret) or "",
            fingerprint_hash,
        )
        if result["status"] == "passed":
            return web.json_response({"status": "passed", "message": "Device verification complete."}, headers={"Cache-Control": "no-store"})
        if result["status"] == "medium":
            return web.json_response({"status": "medium", "message": "Please make one more verification attempt."}, headers={"Cache-Control": "no-store"})
        if result["status"] == "suspicious":
            return self._error("We could not approve this verification. Contact Support if this is a mistake.", 403)
        if result["status"] == "expired":
            return self._error("This verification session expired. Reopen the Mini App.", 410)
        return self._error("The verification browser session changed. Close and reopen Verify Device from the bot.", 400)

    async def verification_status(self, request: web.Request) -> web.Response:
        ip = self._client_ip(request)
        if not await self._api_allowed(request, ip):
            return self._error("Too many verification requests. Please wait and try again.", 429)
        body = await self._json(request)
        try:
            verified = verify_telegram_init_data(str(body.get("init_data") or ""), self.bot_token, self.max_init_data_age)
        except InitDataError as exc:
            log.warning("Telegram init data rejected: %s", exc)
            message = (
                "Telegram session expired. Reopen Verify Device from the bot."
                if str(exc) == "expired init data"
                else "Telegram session signature could not be verified. Open the Mini App from the bot."
            )
            return self._error(message, 401)
        status = await self.db.device_verification_status(verified.user_id)
        return web.json_response({"status": status}, headers={"Cache-Control": "no-store"})
