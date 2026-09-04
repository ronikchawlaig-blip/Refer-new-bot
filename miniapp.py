from __future__ import annotations

import asyncio
import json
import logging
import base64
import zlib
from typing import Any

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
        except InitDataError:
            return self._error("Telegram verification expired or is invalid. Reopen the Mini App from the bot.", 401)
        fingerprint_hash = body.get("fingerprint_hash", "")
        if fingerprint_hash and not is_sha256(fingerprint_hash):
            return self._error("Verification data is invalid. Please try again.")
        client_nonce = str(body.get("client_nonce") or "")
        if len(client_nonce) > 128:
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
        if not token or len(token) > 256:
            return self._error("Verification session is invalid. Reopen the Mini App.", 400)
        try:
            verified = verify_telegram_init_data(init_data, self.bot_token, self.max_init_data_age)
        except InitDataError:
            return self._error("Telegram verification expired or is invalid. Reopen the Mini App.", 401)
        result = await self.db.finish_verification(
            privacy_hash(token, self.hash_secret) or "",
            verified.user_id,
            privacy_hash(init_data, self.hash_secret) or "",
        )
        if result["status"] == "passed":
            return web.json_response({"status": "passed", "message": "Device verification complete."}, headers={"Cache-Control": "no-store"})
        if result["status"] == "medium":
            return web.json_response({"status": "medium", "message": "Please make one more verification attempt."}, headers={"Cache-Control": "no-store"})
        if result["status"] == "suspicious":
            return self._error("We could not approve this verification. Contact Support if this is a mistake.", 403)
        if result["status"] == "expired":
            return self._error("This verification session expired. Reopen the Mini App.", 410)
        return self._error("Verification session is invalid. Reopen the Mini App.", 400)

    async def verification_status(self, request: web.Request) -> web.Response:
        ip = self._client_ip(request)
        if not await self._api_allowed(request, ip):
            return self._error("Too many verification requests. Please wait and try again.", 429)
        body = await self._json(request)
        try:
            verified = verify_telegram_init_data(str(body.get("init_data") or ""), self.bot_token, self.max_init_data_age)
        except InitDataError:
            return self._error("Telegram verification expired or is invalid. Reopen the Mini App.", 401)
        status = await self.db.device_verification_status(verified.user_id)
        return web.json_response({"status": status}, headers={"Cache-Control": "no-store"})
