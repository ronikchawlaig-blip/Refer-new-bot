from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import Database
from services import animated, send_reward
from states import SessionStore
from ui import admin_home, disclaimer_keyboard, gate_keyboard, main_menu, progress_bar, screen

log = logging.getLogger(__name__)
SUPPORT_BOT_LINK = "https://t.me/Referrsupportt_bot"


async def _is_subscribed(bot: Bot, channel: dict[str, Any], user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel["chat_id"], user_id)
        return member.status not in {"left", "kicked"} and (
            member.status != "restricted" or bool(getattr(member, "is_member", True))
        )
    except Exception:
        log.warning("Unable to verify channel %s", channel["chat_id"])
        return False


async def _find_missing_channels(
    bot: Bot, db: Database, user_id: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    channels = await db.active_channels()
    missing = []
    for channel in channels:
        if not await _is_subscribed(bot, channel, user_id):
            missing.append(channel)
    return channels, missing


async def _activate_user(user_id: int, db: Database) -> tuple[str, bool]:
    await db.accept_disclaimer(user_id)
    await db.complete_gate(user_id)
    support_text = await db.get_setting("support_button_text", "💬 Support")
    return support_text, await db.is_admin(user_id)


async def _show_gate(message: Message, bot: Bot, db: Database, user: dict[str, Any]) -> bool:
    status = await message.answer("⠋ Checking access…")
    _, missing = await animated(
        status,
        lambda: _find_missing_channels(bot, db, user["telegram_id"]),
        "Checking access",
        finish=False,
    )
    if missing:
        content = await db.get_content("force_subscribe")
        await status.edit_text(
            screen("Complete access", content["body"]),
            reply_markup=gate_keyboard(missing),
        )
        return False
    await db.mark_subscribed(user["telegram_id"])
    user = await db.get_user(user["telegram_id"]) or user
    if await db.get_setting("disclaimer_enabled", "true") == "true" and not user["disclaimer_accepted"]:
        disclaimer = await db.get_content("disclaimer")
        await status.edit_text(
            screen("One important step", disclaimer["body"]),
            reply_markup=disclaimer_keyboard(),
        )
        return False
    await db.complete_gate(user["telegram_id"])
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


def setup_user_router(db: Database, bot: Bot, sessions: SessionStore, bot_name: str) -> Router:
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
        if not user["is_verified"]:
            return await _show_gate(message, bot, db, user)
        return True

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
        await db.register_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            referrer if referral_enabled else None,
        )
        if await db.get_setting("maintenance_enabled", "false") == "true" and not await db.is_admin(
            message.from_user.id
        ):
            content = await db.get_content("maintenance")
            await message.answer(screen("Temporarily unavailable", content["body"]))
            return
        user = await db.get_user(message.from_user.id)
        if user and not user["is_verified"]:
            if not await _show_gate(message, bot, db, user):
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
            lambda: _show_gate(callback.message, bot, db, user),
            "Checking subscriptions",
        )
        latest = await db.get_user(callback.from_user.id)
        if latest and latest["is_verified"]:
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
        support_text, is_admin = await animated(
            callback.message,
            lambda: _activate_user(callback.from_user.id, db),
            "Activating access",
            progress=True,
            finish=False,
        )
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

            async def load_referral_data() -> tuple[dict[str, Any], str, int | None]:
                loaded_user = await db.get_user(message.from_user.id)
                bot_username = (await bot.get_me()).username or ""
                target_row = await db._p().fetchrow(
                    "SELECT required_referrals FROM milestones WHERE enabled AND required_referrals > $1 "
                    "ORDER BY required_referrals LIMIT 1",
                    loaded_user["referral_count"],
                )
                return loaded_user, bot_username, (
                    target_row["required_referrals"] if target_row else None
                )

            user, bot_username, target = await animated(
                status,
                load_referral_data,
                "Loading referral data",
                finish=False,
            )
            link = f"https://t.me/{bot_username}?start=ref_{message.from_user.id}"
            next_target = target if target is not None else user["referral_count"]
            remaining = max(0, next_target - user["referral_count"])
            await status.edit_text(
                screen(
                    "Refer & Earn",
                    f"Your personal link:\n<code>{link}</code>\n\n"
                    f"Successful referrals: <b>{user['referral_count']}</b>\n"
                    f"Next reward target: <b>{next_target}</b>\n"
                    f"Remaining: <b>{remaining}</b>",
                )
            )
        elif message.text == "🎁 My Rewards":
            placeholder = await message.answer("⠋ Preparing your rewards…")

            async def claim_and_deliver() -> tuple[int, int, str]:
                rewards = await db.claim_rewards(message.from_user.id)
                failed = 0
                for reward in rewards:
                    try:
                        await send_reward(bot, message.from_user.id, reward)
                        await db.mark_reward(reward["id"], message.from_user.id, True)
                    except Exception as exc:
                        failed += 1
                        await db.mark_reward(reward["id"], message.from_user.id, False, str(exc))
                empty_body = ""
                if not rewards:
                    empty_body = (await db.get_content("reward_empty"))["body"]
                return len(rewards), failed, empty_body

            reward_count, failed_count, empty_body = await animated(
                placeholder,
                claim_and_deliver,
                "Processing rewards",
                progress=True,
                finish=False,
            )
            if not reward_count:
                await placeholder.edit_text(empty_body)
                return
            delivery_note = (
                f"\n\n⚠️ Failed deliveries: <b>{failed_count}</b>. An admin can retry them."
                if failed_count
                else ""
            )
            await placeholder.edit_text(
                f"✓ Rewards processed: <b>{reward_count}</b>\n{progress_bar(100)}{delivery_note}"
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

    return router
