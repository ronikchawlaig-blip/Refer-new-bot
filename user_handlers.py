from __future__ import annotations

import asyncio
import logging
from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import Database
from services import animated, send_reward, send_stock_how_to_use
from states import SessionStore
from ui import (
    admin_home,
    disclaimer_keyboard,
    device_verification_keyboard,
    gate_keyboard,
    main_menu,
    progress_bar,
    screen,
    stock_product_keyboard,
    stock_products_keyboard,
)

log = logging.getLogger(__name__)
SUPPORT_BOT_LINK = "https://t.me/GrabSupportbot"


def _history_body(history: list[dict[str, Any]]) -> str:
    lines = []
    for row in history:
        status = str(row["status"]).title()
        points = (
            f" · {row['points_spent']} points"
            if row["source"] == "stock" and row["points_spent"]
            else ""
        )
        kind = "Stock" if row["source"] == "stock" else "Milestone"
        lines.append(
            f"• <b>{escape(str(row['name']))}</b> · {kind}{points}\n"
            f"  Status: {status} · {row['claimed_at']:%d %b %Y, %H:%M}"
        )
    return "\n\n".join(lines)


async def _is_subscribed(bot: Bot, channel: dict[str, Any], user_id: int) -> bool:
    username = str(channel.get("username") or "").strip()
    references: list[Any] = []
    if username:
        references.append(username if username.startswith("@") else f"@{username}")
    references.append(channel["chat_id"])

    seen: set[Any] = set()
    for chat_reference in references:
        if chat_reference in seen:
            continue
        seen.add(chat_reference)
        try:
            member = await bot.get_chat_member(chat_reference, user_id)
            status = getattr(member.status, "value", member.status)
            status = str(status).lower()
            if status in {"creator", "administrator", "member"}:
                return True
            if status == "restricted" and bool(getattr(member, "is_member", False)):
                return True
            log.info(
                "User %s is not a member of channel %s (status=%s); trying next reference",
                user_id,
                chat_reference,
                status,
            )
        except Exception as exc:
            log.warning(
                "Unable to verify user %s in channel %s using %s: %s",
                user_id,
                channel["chat_id"],
                chat_reference,
                exc,
            )
    return False


async def _find_missing_channels(
    bot: Bot, db: Database, user_id: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    channels = await db.active_channels()
    subscribed = await asyncio.gather(
        *(_is_subscribed(bot, channel, user_id) for channel in channels)
    )
    missing = [channel for channel, is_member in zip(channels, subscribed) if not is_member]
    return channels, missing


async def _refresh_verified_user(bot: Bot, db: Database, user: dict[str, Any]) -> bool:
    if not user["is_verified"]:
        return False
    _, missing = await _find_missing_channels(bot, db, user["telegram_id"])
    if missing:
        await db.invalidate_verification(user["telegram_id"])
        return False
    return True


async def _notify_new_referral(
    bot: Bot,
    referrer_id: int,
    referred_user: dict[str, Any],
) -> None:
    try:
        await bot.send_message(
            referrer_id,
            "🔔 <b>𝗡𝗘𝗪 𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟!</b>\n\n"
            f"👤 <b>{escape(str(referred_user.get('first_name') or 'Someone'))}</b> "
            "joined using your link! ⏳\n\n"
            "Waiting for them to join the required channels and accept the disclaimer.",
        )
    except Exception:
        log.exception("Unable to notify referrer %s about a new referral", referrer_id)


async def _notify_referral_success(
    bot: Bot,
    db: Database,
    referrer_id: int,
    referred_user: dict[str, Any],
) -> None:
    try:
        referrer = await db.get_user(referrer_id)
        stats = await db.referral_stats(referrer_id)
        if not referrer:
            return
        await bot.send_message(
            referrer_id,
            "🔔 <b>𝗥𝗘𝗙𝗘𝗥𝗥𝗔𝗟 𝗦𝗨𝗖𝗖𝗘𝗦𝗦!</b>\n\n"
            "You’ve got a new valid referral! 🎉\n\n"
            f"👤 Name: <b>{escape(str(referred_user.get('first_name') or 'Your referral'))}</b>\n\n"
            f"👥 Total: <b>{stats['total_referrals']}</b>\n"
            f"✅ Valid: <b>{stats['valid_referrals']}</b>\n"
            f"❌ Non-Valid: <b>{stats['invalid_referrals']}</b>\n\n"
            "🎁 Keep going — your next reward is getting closer!",
        )
    except Exception:
        log.exception("Unable to notify referrer %s about a successful referral", referrer_id)


async def _activate_user(user_id: int, db: Database) -> tuple[str, bool, int | None]:
    await db.accept_disclaimer(user_id)
    referrer_id = await db.complete_gate(user_id)
    support_text = await db.get_setting("support_button_text", "💬 Support")
    return support_text, await db.is_admin(user_id), referrer_id


async def _show_gate(message: Message, bot: Bot, db: Database, user: dict[str, Any], miniapp_url: str = "") -> bool:
    status = await message.answer("⠋ Checking access…")
    _, missing = await animated(
        status,
        lambda: _find_missing_channels(bot, db, user["telegram_id"]),
        "Checking access",
        finish=False,
    )
    if missing:
        await db.invalidate_verification(user["telegram_id"])
        content = await db.get_content("force_subscribe")
        await status.edit_text(
            screen("Complete access", content["body"]),
            reply_markup=gate_keyboard(missing, miniapp_url),
        )
        return False
    await db.mark_subscribed(user["telegram_id"])
    user = await db.get_user(user["telegram_id"]) or user
    if not await db.device_verification_passed(user["telegram_id"]):
        if not miniapp_url:
            await status.edit_text(
                screen("Verification unavailable", "The secure device verification service is not configured yet. Please contact Support.")
            )
            return False
        await status.edit_text(
            screen(
                "Verify your device",
                "Complete the secure Telegram Mini App verification before continuing. "
                "Your referral will only be credited after verification passes.",
            ),
            reply_markup=device_verification_keyboard(miniapp_url),
        )
        return False
    if await db.get_setting("disclaimer_enabled", "true") == "true" and not user["disclaimer_accepted"]:
        disclaimer = await db.get_content("disclaimer")
        await status.edit_text(
            screen("One important step", disclaimer["body"]),
            reply_markup=disclaimer_keyboard(),
        )
        return False
    referrer_id = await db.complete_gate(user["telegram_id"])
    if referrer_id:
        await _notify_referral_success(bot, db, referrer_id, user)
    await status.edit_text("✓ Access verified.")
    return True


async def _home(message: Message, db: Database, bot_name: str, support_text: str) -> None:
    content = await db.get_content("welcome")
    await message.answer(
        screen(bot_name, content["body"].replace("{bot_name}", bot_name)),
        reply_markup=main_menu(
            support_text,
            show_admin_panel=await db.is_admin(message.from_user.id),
        ),
    )


def setup_user_router(db: Database, bot: Bot, sessions: SessionStore, bot_name: str, miniapp_url: str = "") -> Router:
    router = Router(name="users")

    async def guard(message: Message) -> bool:
        user = await db.get_user(message.from_user.id)
        if not user or user["banned"]:
            await message.answer("Access is unavailable for this account.")
            return False
        if await db.get_setting("maintenance_enabled", "false") == "true" and not await db.is_admin(
            message.from_user.id
        ):
            content = await db.get_content("maintenance")
            await message.answer(screen("Temporarily unavailable", content["body"]))
            return False
        if (
            user["is_verified"]
            and await _refresh_verified_user(bot, db, user)
            and await db.device_verification_passed(user["telegram_id"])
        ):
            return True
        return await _show_gate(message, bot, db, user, miniapp_url)

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        argument = (message.text or "").split(maxsplit=1)
        referrer = None
        if len(argument) == 2 and argument[1].startswith("ref_"):
            try:
                referrer = int(argument[1][4:])
            except ValueError:
                referrer = None
        referral_enabled = await db.get_setting("referrals_enabled", "true") == "true"
        registered_user, created_referrer_id = await db.register_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            referrer if referral_enabled else None,
        )
        if created_referrer_id:
            if registered_user.get("is_verified"):
                await _notify_referral_success(bot, db, created_referrer_id, registered_user)
            else:
                await _notify_new_referral(bot, created_referrer_id, registered_user)
        if await db.get_setting("maintenance_enabled", "false") == "true" and not await db.is_admin(
            message.from_user.id
        ):
            content = await db.get_content("maintenance")
            await message.answer(screen("Temporarily unavailable", content["body"]))
            return
        user = await db.get_user(message.from_user.id)
        if user and user["is_verified"]:
            await _refresh_verified_user(bot, db, user)
            user = await db.get_user(message.from_user.id)
        if user and (not user["is_verified"] or not await db.device_verification_passed(message.from_user.id)):
            if not await _show_gate(message, bot, db, user, miniapp_url):
                return
        support_text = await db.get_setting("support_button_text", "💬 Support")
        await _home(message, db, bot_name, support_text)

    @router.callback_query(F.data == "u:verify")
    async def verify(callback: CallbackQuery) -> None:
        await callback.answer()
        user = await db.get_user(callback.from_user.id)
        if not user:
            return
        await animated(
            callback.message,
            lambda: _show_gate(callback.message, bot, db, user, miniapp_url),
            "Checking subscriptions",
        )
        latest = await db.get_user(callback.from_user.id)
        if latest and latest["is_verified"]:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            support_text = await db.get_setting("support_button_text", "💬 Support")
            await callback.message.answer(
                "✓ Access verified. Welcome in.",
                reply_markup=main_menu(
                    support_text,
                    show_admin_panel=await db.is_admin(callback.from_user.id),
                ),
            )

    @router.callback_query(F.data == "u:accept")
    async def accept(callback: CallbackQuery) -> None:
        await callback.answer()
        user = await db.get_user(callback.from_user.id)
        if not user:
            return
        _, missing = await animated(
            callback.message,
            lambda: _find_missing_channels(bot, db, callback.from_user.id),
            "Checking subscriptions",
            finish=False,
        )
        if missing:
            await callback.message.edit_text(
                "Please complete every required channel subscription first.",
                reply_markup=gate_keyboard(missing),
            )
            return
        await db.mark_subscribed(callback.from_user.id)
        if not await db.device_verification_passed(callback.from_user.id):
            if miniapp_url:
                await callback.message.edit_text(
                    screen("Verify your device", "Complete device verification before accepting the disclaimer."),
                    reply_markup=device_verification_keyboard(miniapp_url),
                )
            else:
                await callback.message.edit_text("Device verification is not configured yet. Please contact Support.")
            return
        support_text, is_admin, referrer_id = await animated(
            callback.message,
            lambda: _activate_user(callback.from_user.id, db),
            "Activating access",
            progress=True,
            finish=False,
        )
        if referrer_id:
            await _notify_referral_success(bot, db, referrer_id, user)
        await callback.message.edit_text(
            f"✓ Accepted. Your access is now active.\n{progress_bar(100)}"
        )
        await callback.message.answer(
            "Choose what you want to do next.",
            reply_markup=main_menu(
                support_text,
                show_admin_panel=is_admin,
            ),
        )

    @router.message(F.text)
    async def menu(message: Message) -> None:
        support_text = await db.get_setting("support_button_text", "💬 Support")
        if message.text not in {
            "👥 Refer & Earn",
            "🛍 Stock",
            "🎁 My Rewards",
            "📊 My Progress",
            support_text,
            "⚙️ Admin Panel",
        }:
            return
        if not await guard(message):
            return
        if message.text == "⚙️ Admin Panel":
            if not await db.is_admin(message.from_user.id):
                await message.answer("This command is restricted.")
                return
            status = await message.answer("⠋ Opening admin panel…")

            async def build_admin_home() -> InlineKeyboardMarkup:
                return admin_home()

            keyboard = await animated(
                status,
                build_admin_home,
                "Opening admin panel",
                finish=False,
            )
            await status.edit_text(
                screen("Admin Home", "Select a section to manage the bot."),
                reply_markup=keyboard,
            )
        elif message.text == "👥 Refer & Earn":
            status = await message.answer("⠋ Loading referral data…")

            async def load_referral_data() -> tuple[dict[str, Any], dict[str, int], str, int | None]:
                loaded_user = await db.get_user(message.from_user.id)
                stats = await db.referral_stats(message.from_user.id)
                bot_username = (await bot.get_me()).username or ""
                target_row = await db._p().fetchrow(
                    "SELECT required_referrals FROM milestones WHERE enabled AND required_referrals > $1 "
                    "ORDER BY required_referrals LIMIT 1",
                    stats["valid_referrals"],
                )
                return loaded_user, stats, bot_username, (
                    target_row["required_referrals"] if target_row else None
                )

            user, stats, bot_username, target = await animated(
                status,
                load_referral_data,
                "Loading referral data",
                finish=False,
            )
            link = f"https://t.me/{bot_username}?start=ref_{message.from_user.id}"
            successful = stats["valid_referrals"]
            next_target = str(target) if target is not None else "Not set"
            remaining = str(max(0, target - successful)) if target is not None else "—"
            await status.edit_text(
                screen(
                    "Refer & Earn",
                    f"Your personal link:\n<code>{link}</code>\n\n"
                    f"Successful referrals: <b>{successful}</b>\n"
                    f"Next reward target: <b>{next_target}</b>\n"
                    f"Remaining: <b>{remaining}</b>",
                )
            )
        elif message.text == "🛍 Stock":
            status = await message.answer("⠋ Loading stock…")

            async def load_stock() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
                return await db.list_stock_products(), await db.get_user(message.from_user.id)

            products, user = await animated(
                status,
                load_stock,
                "Loading stock",
                finish=False,
            )
            if not products:
                await status.edit_text(
                    screen("Stock", "There are no products available right now.")
                )
                return
            body = "\n\n".join(
                f"<b>{escape(str(product['name']))}</b>\n"
                f"Available: <b>{product['available_stock']}</b>\n"
                f"Cost: <b>{product['points_required']} points</b>"
                for product in products
            )
            await status.edit_text(
                screen(
                    "Stock",
                    f"Your points: <b>{user['points'] if user else 0}</b>\n\n{body}\n\n"
                    "Tap a product to view its details and claim it.",
                ),
                reply_markup=stock_products_keyboard(products),
            )
        elif message.text == "🎁 My Rewards":
            placeholder = await message.answer("⠋ Preparing your rewards…")

            async def claim_and_deliver() -> tuple[int, int, list[dict[str, Any]]]:
                rewards = await db.claim_rewards(message.from_user.id)
                failed = 0
                for reward in rewards:
                    try:
                        await send_reward(bot, message.from_user.id, reward)
                        await db.mark_reward(reward["id"], message.from_user.id, True)
                    except Exception as exc:
                        failed += 1
                        await db.mark_reward(reward["id"], message.from_user.id, False, str(exc))
                return len(rewards), failed, await db.user_claim_history(message.from_user.id)

            reward_count, failed_count, empty_body = await animated(
                placeholder,
                claim_and_deliver,
                "Processing rewards",
                progress=True,
                finish=False,
            )
            if not reward_count:
                if empty_body:
                    await placeholder.edit_text(
                        screen("My Rewards", _history_body(empty_body))
                    )
                else:
                    await placeholder.edit_text(
                        (await db.get_content("reward_empty"))["body"]
                    )
                return
            delivery_note = (
                f"\n\n⚠️ Failed deliveries: <b>{failed_count}</b>. An admin can retry them."
                if failed_count
                else ""
            )
            await placeholder.edit_text(
                screen(
                    "My Rewards",
                    f"✓ New rewards delivered: <b>{reward_count}</b>\n"
                    f"{progress_bar(100)}{delivery_note}\n\n"
                    "<b>Claim history</b>\n\n"
                    f"{_history_body(empty_body)}",
                )
            )
        elif message.text == "📊 My Progress":
            status = await message.answer("⠋ Loading progress…")

            async def load_progress() -> tuple[dict[str, Any], list[dict[str, Any]]]:
                return await db.get_user(message.from_user.id), await db.list_milestones()

            user, milestones = await animated(
                status,
                load_progress,
                "Loading progress",
                finish=False,
            )
            upcoming = next((m for m in milestones if m["required_referrals"] > user["referral_count"]), None)
            current = max(
                [m["required_referrals"] for m in milestones if m["required_referrals"] <= user["referral_count"]]
                or [0]
            )
            target = upcoming["required_referrals"] if upcoming else current
            span = max(1, target - current)
            percent = min(100, round((user["referral_count"] - current) / span * 100))
            await status.edit_text(
                screen(
                    "My Progress",
                    f"Successful referrals: <b>{user['referral_count']}</b>\n"
                    f"Current milestone: <b>{current or 'Getting started'}</b>\n"
                    f"Next milestone: <b>{target or '—'}</b>\n\n"
                    f"{progress_bar(percent)}",
                )
            )
        else:
            status = await message.answer("⠋ Opening support…")

            async def load_support() -> tuple[str, str]:
                # Keep Support useful even for databases created before the
                # default support bot was configured.
                link = await db.get_setting("support_link", SUPPORT_BOT_LINK)
                link = link or SUPPORT_BOT_LINK
                instructions = (await db.get_content("support"))["body"] or await db.get_setting(
                    "support_instructions",
                    "Tap below to open our Support Bot. Our team will respond as soon as possible.",
                )
                return link, instructions

            link, instructions = await animated(
                status,
                load_support,
                "Opening support",
                finish=False,
            )
            if link:
                await status.edit_text(
                    instructions,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="Open Support Bot", url=link)]
                        ]
                    ),
                )
            else:
                await status.edit_text(instructions)

    @router.callback_query(F.data == "u:stock_back")
    async def stock_back(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await callback.message.edit_text("Choose an option from the menu below.")

    async def callback_access(callback: CallbackQuery) -> dict[str, Any] | None:
        user = await db.get_user(callback.from_user.id)
        if not user or user["banned"]:
            await callback.answer("Access is unavailable for this account.", show_alert=True)
            return None
        if user["is_verified"] and not await _refresh_verified_user(bot, db, user):
            await callback.answer("Please verify your access first.", show_alert=True)
            return None
        if not user["is_verified"] or not await db.device_verification_passed(callback.from_user.id):
            await callback.answer("Please verify your access first.", show_alert=True)
            return None
        if await db.get_setting("maintenance_enabled", "false") == "true" and not await db.is_admin(
            callback.from_user.id
        ):
            await callback.answer("The bot is temporarily unavailable.", show_alert=True)
            return None
        return user

    @router.callback_query(F.data == "u:stock")
    async def stock_list_callback(callback: CallbackQuery) -> None:
        user = await callback_access(callback)
        if not user or not callback.message:
            return
        await callback.answer()
        products = await db.list_stock_products()
        if not products:
            await callback.message.edit_text(
                screen("Stock", "There are no products available right now.")
            )
            return
        body = "\n\n".join(
            f"<b>{escape(str(product['name']))}</b>\n"
            f"Available: <b>{product['available_stock']}</b>\n"
            f"Cost: <b>{product['points_required']} points</b>"
            for product in products
        )
        await callback.message.edit_text(
            screen(
                "Stock",
                f"Your points: <b>{user['points']}</b>\n\n{body}\n\n"
                "Tap a product to view its details and claim it.",
            ),
            reply_markup=stock_products_keyboard(products),
        )

    @router.callback_query(F.data.startswith("u:stock_claim:"))
    async def stock_claim(callback: CallbackQuery) -> None:
        user = await callback_access(callback)
        if not user or not callback.message:
            return
        try:
            product_id = int((callback.data or "").split(":")[-1])
        except ValueError:
            await callback.answer("Invalid product.", show_alert=True)
            return
        await callback.answer("Checking eligibility…")
        result, claim = await db.claim_stock_product(callback.from_user.id, product_id)
        if result != "claimed" or not claim:
            messages = {
                "already_claimed": "You have already claimed this product.",
                "out_of_stock": "This product is out of stock.",
                "insufficient_points": (
                    f"You need {claim['points_required'] - user['points']} more points "
                    "to claim this product."
                    if claim
                    else "You do not have enough points to claim this product."
                ),
                "not_verified": "Please verify your access before claiming a product.",
                "banned": "Access is unavailable for this account.",
                "unavailable": "This product is no longer available.",
            }
            await callback.message.answer(messages.get(result, "This product cannot be claimed right now."))
            return
        try:
            await send_reward(bot, callback.from_user.id, claim)
        except Exception as exc:
            try:
                await db.mark_stock_claim(claim["id"], callback.from_user.id, False, str(exc))
            except Exception:
                log.exception("Unable to record failed stock delivery %s", claim["id"])
            await callback.message.edit_text(
                "⚠️ Your claim was reserved, but delivery failed. "
                "Please contact Support so an admin can retry it.",
                reply_markup=stock_product_keyboard(claim["product_id"]),
            )
            return

        try:
            await db.mark_stock_claim(claim["id"], callback.from_user.id, True)
        except Exception:
            # The reward was already sent; never report a delivered reward as failed.
            log.exception("Unable to record successful stock delivery %s", claim["id"])
        try:
            await send_stock_how_to_use(
                bot,
                callback.from_user.id,
                claim.get("how_to_use"),
            )
        except Exception:
            log.exception("Unable to send How to Use for stock claim %s", claim["id"])
        await callback.message.edit_text(
            f"✅ <b>{escape(str(claim['name']))}</b> claimed successfully.\n\n"
            f"Points spent: <b>{claim['points_spent']}</b>\n"
            f"Remaining points: <b>{claim['remaining_points']}</b>\n\n"
            "Your reward has been sent.",
            reply_markup=stock_product_keyboard(claim["product_id"]),
        )

    @router.callback_query(F.data.startswith("u:stock:"))
    async def stock_product(callback: CallbackQuery) -> None:
        user = await callback_access(callback)
        if not user or not callback.message:
            return
        try:
            product_id = int((callback.data or "").split(":")[-1])
        except ValueError:
            await callback.answer("Invalid product.", show_alert=True)
            return
        product = await db.get_stock_product(product_id)
        if not product or not product["enabled"]:
            await callback.answer("This product is no longer available.", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(
            screen(
                escape(str(product["name"])),
                f"Available stock: <b>{product['available_stock']}</b>\n"
                f"Required points: <b>{product['points_required']}</b>\n"
                f"Your points: <b>{user['points']}</b>\n\n"
                "Reward details are hidden until you claim this product.\n"
                "Tap Claim now to redeem it.",
            ),
            reply_markup=stock_product_keyboard(product_id),
        )

    return router
