from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from db import Database
from services import animated, send_reward
from states import SessionStore
from ui import admin_home, admin_section, back_keyboard, confirm_keyboard, progress_bar, screen


def _incoming(message: Message) -> tuple[str, str | None, str | None]:
    if message.text:
        return "text", message.text, None
    if message.photo:
        return "photo", message.caption or "", message.photo[-1].file_id
    if message.video:
        return "video", message.caption or "", message.video.file_id
    if message.animation:
        return "animation", message.caption or "", message.animation.file_id
    if message.document:
        return "document", message.caption or "", message.document.file_id
    return "text", "", None


def setup_admin_router(
    db: Database,
    bot: Bot,
    sessions: SessionStore,
    on_broadcast: Callable[[], Awaitable[None]],
) -> Router:
    router = Router(name="admins")

    async def allowed(user_id: int, permission: str | None = None) -> bool:
        return await db.is_admin(user_id, permission)

    async def admin_screen(callback: CallbackQuery, title: str, body: str, keyboard: Any) -> None:
        if callback.message:
            await callback.message.edit_text(screen(title, body), reply_markup=keyboard)

    @router.message(Command("admin"))
    async def admin_command(message: Message) -> None:
        if not await allowed(message.from_user.id):
            await message.answer("This command is restricted.")
            return
        status = await message.answer("⠋ Opening admin panel…")

        async def build_admin_home() -> Any:
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

    @router.callback_query(F.data.startswith("a:"))
    async def callbacks(callback: CallbackQuery) -> None:
        if not await allowed(callback.from_user.id):
            await callback.answer("Not authorized.", show_alert=True)
            return
        await callback.answer()
        data = callback.data or ""
        parts = data.split(":")
        action = parts[1]
        admin_id = callback.from_user.id
        permission_by_action = {
            "dashboard": "dashboard",
            "users": "users",
            "user_search": "users",
            "user_recent": "users",
            "user_banned": "users",
            "rewards": "rewards",
            "rew_add": "rewards",
            "rew_bulk": "rewards",
            "stock": "rewards",
            "stock_add": "rewards",
            "stock_restock": "rewards",
            "stock_toggle": "rewards",
            "milestones": "rewards",
            "inventory": "rewards",
            "history": "rewards",
            "failed": "rewards",
            "retry": "rewards",
            "referrals": "referrals",
            "force": "force",
            "force_add": "force",
            "content": "content",
            "cont_edit": "content",
            "cont_preview": "content",
            "broadcast": "broadcast",
            "broadcast_start": "broadcast",
            "broadcast_confirm": "broadcast",
            "settings": "settings",
            "toggle_referrals": "settings",
            "toggle_maintenance": "settings",
            "toggle_disclaimer": "settings",
            "support_setup": "settings",
        }
        if action in permission_by_action and not await allowed(
            admin_id, permission_by_action[action]
        ):
            await callback.message.answer("Your admin role does not have permission for this section.")
            return
        if action == "bulk_confirm":
            session = sessions.pop(admin_id)
            if not session or session["flow"] != "bulk_confirm":
                await callback.answer("Bulk session expired.", show_alert=True)
                return

            async def add_rewards() -> int:
                count = await db.bulk_add_rewards(session["required"], session["items"])
                await db.audit(
                    admin_id,
                    "bulk_rewards_added",
                    "milestone",
                    str(session["required"]),
                    {"count": count},
                )
                return count

            count = await animated(
                callback.message,
                add_rewards,
                "Adding rewards",
                progress=True,
                finish=False,
            )
            await callback.message.edit_text(
                f"✓ Added <b>{count}</b> rewards safely.\n{progress_bar(100)}"
            )
        elif action == "force_remove_confirm":
            session = sessions.pop(admin_id)
            if not session or session["flow"] != "force_remove_confirm":
                await callback.answer("Removal session expired.", show_alert=True)
                return
            async def remove_channel() -> None:
                await db.delete_channel(session["channel_id"])
                await db.audit(
                    admin_id,
                    "force_channel_removed",
                    "channel",
                    str(session["channel_id"]),
                )

            await animated(
                callback.message,
                remove_channel,
                "Removing channel",
                finish=False,
            )
            await callback.message.edit_text("✓ Channel removed.")
        elif action == "home":
            await admin_screen(callback, "Admin Home", "Select a section to manage the bot.", admin_home())
        elif action == "dashboard":
            stats = await animated(
                callback.message,
                db.dashboard,
                "Loading dashboard",
                finish=False,
            )
            body = "\n".join(
                [
                    f"Total users: <b>{stats['total_users']}</b>",
                    f"New users (24h): <b>{stats['new_users']}</b>",
                    f"Active / verified: <b>{stats['verified_users']}</b>",
                    f"Successful referrals: <b>{stats['completed_referrals']}</b>",
                    f"Pending referrals: <b>{stats['pending_referrals']}</b>",
                    "",
                    f"Available rewards: <b>{stats['available_rewards']}</b>",
                    f"Assigned: <b>{stats['assigned_rewards']}</b>",
                    f"Delivered: <b>{stats['delivered_rewards']}</b>",
                    f"Failed deliveries: <b>{stats['failed_deliveries']}</b>",
                    "",
                    f"Stock products: <b>{stats['stock_products']}</b>",
                    f"Stock units available: <b>{stats['stock_units']}</b>",
                    f"Banned users: <b>{stats['banned_users']}</b>",
                ]
            )
            await admin_screen(
                callback, "Dashboard", body, admin_section([[("🔄 Refresh", "a:dashboard")]])
            )
        elif action == "rewards":
            await admin_screen(
                callback,
                "Reward Management",
                "Manage content, milestones, inventory and delivery safety.",
                admin_section(
                    [
                        [("➕ Add Reward", "a:rew_add"), ("📦 Bulk Add", "a:rew_bulk")],
                        [("🛍 Stock", "a:stock"), ("🎯 Milestones", "a:milestones")],
                        [("📊 Inventory", "a:inventory")],
                        [("📜 Delivery History", "a:history"), ("❌ Failed Deliveries", "a:failed")],
                    ]
                ),
            )
        elif action == "rew_add":
            sessions.set(admin_id, "reward_content")
            await callback.message.answer("Send the reward content now: text, link, code, photo, video, GIF, document or APK.")
        elif action == "rew_bulk":
            sessions.set(admin_id, "bulk_content")
            await callback.message.answer("Send one reward per line. Text, links and codes are supported.")
        elif action == "stock":
            products = await animated(
                callback.message,
                lambda: db.list_stock_products(include_disabled=True),
                "Loading stock",
                finish=False,
            )
            body = "\n".join(
                f"• {product['name']} · {product['stock']} available · "
                f"{product['points_required']} points · "
                f"{'enabled' if product['enabled'] else 'disabled'}"
                for product in products
            ) or "No stock products yet."
            product_rows = [
                [
                    (
                        f"{'🟢' if product['enabled'] else '🔴'} {product['name'][:18]}",
                        f"a:stock_toggle:{product['id']}",
                    ),
                    ("＋ Stock", f"a:stock_restock:{product['id']}"),
                ]
                for product in products
            ]
            await admin_screen(
                callback,
                "Stock Management",
                body
                + "\n\nTo add a product, send its reward content first, then "
                "<code>product name | points required | stock count</code>.",
                admin_section(
                    [[("➕ Add Product", "a:stock_add")], *product_rows],
                    "a:rewards",
                ),
            )
        elif action == "stock_add":
            sessions.set(admin_id, "stock_content")
            await callback.message.answer(
                "Send the product reward now: text, link, code, photo, video, GIF, document or APK."
            )
        elif action == "stock_restock" and len(parts) > 2:
            sessions.set(admin_id, "stock_restock", product_id=int(parts[2]))
            await callback.message.answer("Send the number of units to add to this product.")
        elif action == "stock_toggle" and len(parts) > 2:
            await db.toggle_stock_product(int(parts[2]))
            await db.audit(admin_id, "stock_product_toggled", "stock_product", parts[2])
            await callback.message.answer("✓ Stock product status updated.")
        elif action == "milestones":
            milestones = await animated(
                callback.message,
                db.list_milestones,
                "Loading milestones",
                finish=False,
            )
            body = "\n".join(
                f"• {m['required_referrals']} referrals — {m['name']} · "
                f"{'enabled' if m['enabled'] else 'disabled'} · {m['available_count']} available"
                for m in milestones
            ) or "No milestones yet."
            milestone_rows = [
                [
                    (f"{'🟢' if m['enabled'] else '🔴'} {m['required_referrals']}", f"a:milestone_toggle:{m['id']}"),
                    ("🗑️", f"a:milestone_delete:{m['id']}"),
                ]
                for m in milestones
            ]
            await admin_screen(
                callback,
                "Milestones",
                body + "\n\nTo create or edit: send <code>required referrals | name</code>.",
                admin_section([[("➕ Create / Edit", "a:milestone_add")], *milestone_rows], "a:rewards"),
            )
        elif action == "milestone_add":
            sessions.set(admin_id, "milestone")
            await callback.message.answer("Send: required referrals | milestone name")
        elif action == "milestone_toggle" and len(parts) > 2:
            await db.toggle_milestone(int(parts[2]))
            await db.audit(admin_id, "milestone_status_changed", "milestone", parts[2])
            await callback.message.answer("✓ Milestone status updated.")
        elif action == "milestone_delete" and len(parts) > 2:
            await callback.message.answer(
                "⚠️ Delete this milestone? Existing rewards will stay in inventory.",
                reply_markup=confirm_keyboard(f"a:milestone_delete_confirm:{parts[2]}", "a:milestones"),
            )
        elif action == "milestone_delete_confirm" and len(parts) > 2:
            await db.delete_milestone(int(parts[2]))
            await db.audit(admin_id, "milestone_deleted", "milestone", parts[2])
            await callback.message.edit_text("✓ Milestone deleted.")
        elif action == "inventory":
            rows = await animated(
                callback.message,
                db.inventory,
                "Loading inventory",
                finish=False,
            )
            body = "\n".join(f"• {row['status'].title()}: <b>{row['count']}</b>" for row in rows) or "Inventory is empty."
            await admin_screen(callback, "Reward Inventory", body, back_keyboard("a:rewards"))
        elif action in {"history", "failed"}:
            query = (
                "SELECT ra.*, r.name, r.kind FROM reward_assignments ra JOIN rewards r ON r.id=ra.reward_id "
                + ("WHERE ra.status='failed' " if action == "failed" else "")
                + "ORDER BY ra.assigned_at DESC LIMIT 15"
            )
            rows = await animated(
                callback.message,
                lambda: db._p().fetch(query),
                "Loading delivery history",
                finish=False,
            )
            body = "\n".join(
                f"• User <code>{r['user_id']}</code> · {r['name']} · {r['status']} · {r['assigned_at']:%d %b %H:%M}"
                for r in rows
            ) or "No delivery records."
            retry_rows = (
                [[("Retry reward " + str(r["reward_id"]), f"a:retry:{r['reward_id']}")] for r in rows]
                if action == "failed"
                else []
            )
            await admin_screen(
                callback,
                "Failed Deliveries" if action == "failed" else "Delivery History",
                body,
                admin_section(retry_rows, "a:rewards") if retry_rows else back_keyboard("a:rewards"),
            )
        elif action == "users":
            await admin_screen(
                callback,
                "User Management",
                "Search by Telegram ID or review recent and banned accounts.",
                admin_section(
                    [
                        [("🔍 Search User", "a:user_search"), ("📋 Recent Users", "a:user_recent")],
                        [("🚫 Banned Users", "a:user_banned")],
                    ]
                ),
            )
        elif action == "user_search":
            sessions.set(admin_id, "user_search")
            await callback.message.answer("Send the Telegram User ID to search.")
        elif action in {"user_recent", "user_banned"}:
            rows = await animated(
                callback.message,
                lambda: db.search_users(limit=15),
                "Loading users",
                finish=False,
            )
            if action == "user_banned":
                rows = [row for row in rows if row["banned"]]
            body = "\n".join(
                f"• <code>{row['telegram_id']}</code> · {row['first_name'][:18]} · referrals {row['referral_count']}"
                for row in rows
            ) or "No users found."
            await admin_screen(callback, "Users", body, back_keyboard("a:users"))
        elif action == "referrals":
            stats = await animated(
                callback.message,
                db.dashboard,
                "Loading referrals",
                finish=False,
            )
            body = (
                f"Completed: <b>{stats['completed_referrals']}</b>\n"
                f"Pending: <b>{stats['pending_referrals']}</b>\n\n"
                "Manual user adjustments are available from a user profile."
            )
            await admin_screen(callback, "Referrals", body, admin_section([[("🔍 Manage User", "a:user_search")]]))
        elif action == "force":
            channels = await animated(
                callback.message,
                db.list_channels,
                "Loading channels",
                finish=False,
            )
            body = "\n".join(
                f"• {c['title']} · {'enabled' if c['enabled'] else 'disabled'} · <code>{c['chat_id']}</code>"
                for c in channels
            ) or "No channels configured."
            rows = [[("➕ Add Channel", "a:force_add")]]
            rows += [
                [
                    (f"{'🟢' if c['enabled'] else '🔴'} {c['title'][:18]}", f"a:force_toggle:{c['id']}"),
                    ("↑", f"a:force_up:{c['id']}"),
                    ("↓", f"a:force_down:{c['id']}"),
                ]
                for c in channels
            ]
            rows += [[("🗑️ Remove a Channel", "a:force_remove")]]
            await admin_screen(callback, "Force Subscribe", body, admin_section(rows))
        elif action == "force_add":
            sessions.set(admin_id, "force_channel")
            await callback.message.answer("Send: chat_id | title | @username (optional) | invite URL (optional)")
        elif action == "force_toggle" and len(parts) > 2:
            async def toggle_channel() -> None:
                await db.toggle_channel(int(parts[2]))
                await db.audit(admin_id, "force_channel_toggled", "channel", parts[2])

            await animated(callback.message, toggle_channel, "Updating channel", finish=False)
            await callback.message.edit_text("✓ Channel status updated.")
        elif action in {"force_up", "force_down"} and len(parts) > 2:
            async def reorder_channel() -> None:
                await db.move_channel(int(parts[2]), -1 if action == "force_up" else 1)
                await db.audit(
                    admin_id,
                    "force_channel_reordered",
                    "channel",
                    parts[2],
                    {"direction": action},
                )

            await animated(callback.message, reorder_channel, "Updating channel order", finish=False)
            await callback.message.edit_text("✓ Channel order updated.")
        elif action == "force_remove":
            sessions.set(admin_id, "force_remove")
            await callback.message.answer("Send the channel database ID to remove. This requires confirmation in the next step.")
        elif action == "content":
            keys = ["welcome", "maintenance", "disclaimer", "force_subscribe", "support", "how_it_works", "reward_success", "reward_empty", "error"]
            rows = [
                [
                    (f"✏️ {key.replace('_',' ').title()}", f"a:cont_edit:{key}"),
                    ("👁️ Preview", f"a:cont_preview:{key}"),
                ]
                for key in keys
            ]
            await admin_screen(callback, "Content Management", "All key user-facing copy is stored in the database.", admin_section(rows))
        elif action == "cont_edit" and len(parts) > 2:
            key = parts[2]
            sessions.set(admin_id, "content", key=key)
            await callback.message.answer(f"Send the new content for <b>{key.replace('_',' ').title()}</b>.")
        elif action == "cont_preview" and len(parts) > 2:
            status = await callback.message.answer("⠋ Loading content preview…")
            content = await animated(
                status,
                lambda: db.get_content(parts[2]),
                "Loading content preview",
                finish=False,
            )
            await status.edit_text(content["body"] or "Empty content.")
        elif action == "settings":
            async def load_settings() -> tuple[str, str, str]:
                return (
                    await db.get_setting("referrals_enabled", "true"),
                    await db.get_setting("maintenance_enabled", "false"),
                    await db.get_setting("disclaimer_enabled", "true"),
                )

            enabled, maintenance, disclaimer = await animated(
                callback.message,
                load_settings,
                "Loading settings",
                finish=False,
            )
            await admin_screen(
                callback,
                "Settings",
                f"Referral system: <b>{enabled}</b>\nMaintenance: <b>{maintenance}</b>\nDisclaimer: <b>{disclaimer}</b>",
                admin_section(
                    [
                        [("🎯 Toggle Referrals", "a:toggle_referrals"), ("🚧 Toggle Maintenance", "a:toggle_maintenance")],
                        [("⚠️ Toggle Disclaimer", "a:toggle_disclaimer"), ("💬 Support Setup", "a:support_setup")],
                    ]
                ),
            )
        elif action in {"toggle_referrals", "toggle_maintenance", "toggle_disclaimer"}:
            key = {"toggle_referrals": "referrals_enabled", "toggle_maintenance": "maintenance_enabled", "toggle_disclaimer": "disclaimer_enabled"}[action]
            async def update_setting() -> str:
                current = await db.get_setting(key, "false")
                value = "false" if current == "true" else "true"
                await db.set_setting(key, value)
                await db.audit(admin_id, "setting_changed", "setting", key, {"value": value})
                return value

            value = await animated(
                callback.message,
                update_setting,
                "Saving setting",
                finish=False,
            )
            await callback.message.edit_text(f"✓ Setting updated: <b>{value}</b>")
        elif action == "support_setup":
            sessions.set(admin_id, "support_setup")
            await callback.message.answer("Send: support username | support link | button text | instructions")
        elif action == "broadcast":
            await admin_screen(callback, "Broadcast", "Send a preview, confirm it, then the queue delivers it with rate limiting.", admin_section([[("📢 Send Content", "a:broadcast_start")]]))
        elif action == "broadcast_start":
            sessions.set(admin_id, "broadcast")
            await callback.message.answer("Send broadcast content: text, photo, video, GIF or document.")
        elif action == "broadcast_confirm":
            session = sessions.pop(admin_id)
            if not session:
                await callback.message.answer("Broadcast session expired.")
                return

            async def queue_broadcast() -> int:
                job_id = await db.create_broadcast(
                    admin_id,
                    session["kind"],
                    {
                        "body": session["body"],
                        "file_id": session["file_id"],
                        "status_chat_id": callback.message.chat.id,
                        "status_message_id": callback.message.message_id,
                    },
                )
                await db.audit(admin_id, "broadcast_queued", "broadcast", str(job_id))
                return job_id

            job_id = await animated(
                callback.message,
                queue_broadcast,
                "Queueing broadcast",
                progress=True,
                finish=False,
            )
            await callback.message.edit_text(
                f"⠋ Broadcast queued as #{job_id}\n{progress_bar(0)}\n\n"
                "Delivery will continue safely in the background."
            )
            await on_broadcast()
        elif action == "broadcast_cancel":
            sessions.pop(admin_id)
            await callback.message.edit_text("Broadcast cancelled.")
        elif action == "admins":
            if await db.admin_role(admin_id) != "owner":
                await callback.message.answer("Only the Owner can manage administrators.")
                return
            admins = await animated(
                callback.message,
                db.list_admins,
                "Loading administrators",
                finish=False,
            )
            body = "\n".join(f"• <code>{a['telegram_id']}</code> · {a['role']}" for a in admins)
            admin_rows = [
                [(f"🔐 Permissions {a['telegram_id']}", f"a:admin_perms:{a['telegram_id']}")]
                for a in admins
                if a["role"] != "owner"
            ]
            await admin_screen(
                callback,
                "Administrators",
                body,
                admin_section(
                    [[("➕ Add Admin", "a:admin_add"), ("➖ Remove Admin", "a:admin_remove")], *admin_rows]
                ),
            )
        elif action == "admin_add":
            sessions.set(admin_id, "admin_add")
            await callback.message.answer("Send the Telegram User ID for the new Admin.")
        elif action == "admin_remove":
            sessions.set(admin_id, "admin_remove")
            await callback.message.answer("Send the Telegram User ID to remove.")
        elif action == "admin_perms" and len(parts) > 2:
            sessions.set(admin_id, "admin_perms", user_id=int(parts[2]))
            await callback.message.answer(
                "Send comma-separated permissions:\n"
                "<code>dashboard,users,rewards,referrals,force,content,broadcast,settings</code>"
            )
        elif action == "logs":
            page = int(parts[2]) if len(parts) > 2 else 0
            rows = await animated(
                callback.message,
                lambda: db.logs(offset=page * 12),
                "Loading audit logs",
                finish=False,
            )
            body = "\n".join(f"• {r['created_at']:%d %b %H:%M} · {r['action']} · {r['target_id'] or '—'}" for r in rows) or "No audit entries yet."
            rows_kb = []
            if page:
                rows_kb.append(("← Previous", f"a:logs:{page - 1}"))
            if len(rows) == 12:
                rows_kb.append(("Next →", f"a:logs:{page + 1}"))
            await admin_screen(callback, "Audit Logs", body, admin_section([rows_kb] if rows_kb else [], "a:home"))
        elif action == "retry" and len(parts) > 2:
            reward_id = int(parts[2])

            async def retry_reward() -> str:
                assignment = await db._p().fetchrow(
                    "SELECT ra.user_id, r.* FROM reward_assignments ra JOIN rewards r ON r.id=ra.reward_id "
                    "WHERE ra.reward_id=$1 AND ra.status='failed'",
                    reward_id,
                )
                if not assignment or not await db.retry_failed_reward(reward_id):
                    return "That failed delivery is no longer retryable."
                try:
                    await send_reward(bot, assignment["user_id"], dict(assignment))
                    await db.mark_reward(reward_id, assignment["user_id"], True)
                    result = "✓ Reward redelivered successfully."
                except Exception as exc:
                    await db.mark_reward(reward_id, assignment["user_id"], False, str(exc))
                    result = "Retry attempted; delivery failed again and remains tracked."
                await db.audit(admin_id, "failed_reward_retried", "reward", parts[2])
                return result

            result = await animated(
                callback.message,
                retry_reward,
                "Redelivering reward",
                progress=True,
                finish=False,
            )
            await callback.message.edit_text(
                f"{result}\n{progress_bar(100 if result.startswith('✓') else 0)}"
            )
        elif action == "urewards" and len(parts) > 2:
            status = await callback.message.answer("⠋ Loading user rewards…")
            history = await animated(
                status,
                lambda: db.user_reward_history(int(parts[2])),
                "Loading user rewards",
                finish=False,
            )
            body = "\n".join(
                f"• #{row['reward_id']} · {row['name']} · {row['status']} · {row['assigned_at']:%d %b %H:%M}"
                for row in history
            ) or "No reward history for this user."
            await status.edit_text(screen("User Reward History", body))
        elif action in {"ban", "unban", "reset", "addref", "addpts"} and len(parts) > 2:
            user_id = int(parts[2])
            if action == "ban":
                await callback.message.answer(
                    "⚠️ Ban this user? They will be blocked from protected features.",
                    reply_markup=confirm_keyboard(f"a:ban_confirm:{user_id}", "a:users"),
                )
                return
            if action == "reset":
                await callback.message.answer(
                    "⚠️ Reset this user's progress? This cannot easily be undone.",
                    reply_markup=confirm_keyboard(f"a:reset_confirm:{user_id}", "a:users"),
                )
                return
            if action == "unban":
                await db.set_banned(user_id, False)
            elif action == "addref" or action == "addpts":
                sessions.set(admin_id, "adjust", user_id=user_id, field="referral_count" if action == "addref" else "points")
                await callback.message.answer("Send a positive or negative number.")
                return
            await db.audit(admin_id, f"user_{action}", "user", str(user_id))
            await callback.message.answer("✓ User updated and the action was logged.")
        elif action in {"ban_confirm", "reset_confirm"} and len(parts) > 2:
            user_id = int(parts[2])
            if action == "ban_confirm":
                await db.set_banned(user_id, True)
                audit_action = "user_ban"
            else:
                await db.reset_progress(user_id)
                audit_action = "user_progress_reset"
            await db.audit(admin_id, audit_action, "user", str(user_id))
            await callback.message.edit_text("✓ User updated and the action was logged.")
        elif action == "confirm_reset" and len(parts) > 2:
            await callback.message.answer(
                "⚠️ Reset this user's progress? This cannot easily be undone.",
                reply_markup=confirm_keyboard(f"a:reset_confirm:{parts[2]}", "a:users"),
            )

    @router.message()
    async def conversational(message: Message) -> object:
        session = sessions.get(message.from_user.id)
        if not session or not await allowed(message.from_user.id):
            # This router is included before the user router. Returning
            # UNHANDLED lets normal user messages continue to the user
            # handlers when no admin flow is active.
            return UNHANDLED
        flow = session["flow"]
        kind, body, file_id = _incoming(message)

        async def animate_message(
            label: str,
            operation: Callable[[], Awaitable[Any]],
            progress: bool = False,
        ) -> tuple[Message, Any]:
            status = await message.answer(f"⠋ {label}…")
            result = await animated(
                status,
                operation,
                label,
                progress=progress,
                finish=False,
            )
            return status, result

        if flow == "reward_content":
            sessions.set(message.from_user.id, "reward_meta", kind=kind, body=body, file_id=file_id)
            await message.answer("Now send: milestone referral count | optional reward name")
        elif flow == "stock_content":
            sessions.set(
                message.from_user.id,
                "stock_meta",
                kind=kind,
                body=body,
                file_id=file_id,
            )
            await message.answer(
                "Now send: product name | points required | stock count"
            )
        elif flow == "reward_meta":
            try:
                required, _, name = (body or "").partition("|")
                required_count = int(required.strip())

                async def save_reward() -> None:
                    await db.add_reward(
                        required_count,
                        name.strip() or "Reward",
                        session["kind"],
                        session["body"],
                        session["file_id"],
                    )
                    await db.audit(message.from_user.id, "reward_added", "reward")

                status, _ = await animate_message(
                    "Saving reward",
                    save_reward,
                    progress=True,
                )
                sessions.pop(message.from_user.id)
                await status.edit_text(
                    f"✓ Reward added safely to inventory.\n{progress_bar(100)}"
                )
            except Exception:
                await message.answer("Use the format: 5 | Premium Reward")
        elif flow == "stock_meta":
            try:
                name, points, stock = [part.strip() for part in (body or "").split("|", 2)]
                points_required = int(points)
                stock_count = int(stock)
                if not name or points_required < 0 or stock_count < 0:
                    raise ValueError

                async def save_stock_product() -> int:
                    product_id = await db.add_stock_product(
                        name,
                        points_required,
                        stock_count,
                        session["kind"],
                        session["body"],
                        session["file_id"],
                    )
                    await db.audit(
                        message.from_user.id,
                        "stock_product_added",
                        "stock_product",
                        str(product_id),
                        {
                            "points_required": points_required,
                            "stock": stock_count,
                        },
                    )
                    return product_id

                status, product_id = await animate_message(
                    "Saving stock product",
                    save_stock_product,
                    progress=True,
                )
                sessions.pop(message.from_user.id)
                await status.edit_text(
                    f"✓ Stock product added: <b>{name}</b>\n"
                    f"Points: <b>{points_required}</b> · Stock: <b>{stock_count}</b>\n"
                    f"{progress_bar(100)}"
                )
            except (TypeError, ValueError):
                await message.answer(
                    "Use: product name | points required | stock count\n"
                    "Points and stock must be zero or greater."
                )
        elif flow == "bulk_content":
            items = [(line.strip(), "text", line.strip(), None) for line in (body or "").splitlines() if line.strip()]
            sessions.set(message.from_user.id, "bulk_meta", items=items)
            await message.answer(f"Detected <b>{len(items)}</b> rewards. Send: milestone referral count")
        elif flow == "bulk_meta":
            try:
                required = int((body or "").strip())
                preview = "\n".join(f"• {item[0][:45]}" for item in session["items"][:8])
                sessions.set(message.from_user.id, "bulk_confirm", items=session["items"], required=required)
                await message.answer(f"<b>Preview</b>\n{preview}\n\nQuantity: {len(session['items'])}", reply_markup=confirm_keyboard("a:bulk_confirm", "a:home"))
            except ValueError:
                await message.answer("Send only the milestone referral count.")
        elif flow == "bulk_confirm":
            # This path is reached only by text; callback handles confirmation.
            pass
        elif flow == "stock_restock":
            try:
                amount = int((body or "").strip())
                if amount <= 0:
                    raise ValueError

                async def add_stock() -> None:
                    if not await db.restock_product(session["product_id"], amount):
                        raise ValueError("Product not found")
                    await db.audit(
                        message.from_user.id,
                        "stock_restocked",
                        "stock_product",
                        str(session["product_id"]),
                        {"amount": amount},
                    )

                status, _ = await animate_message("Updating stock", add_stock)
                sessions.pop(message.from_user.id)
                await status.edit_text(f"✓ Added <b>{amount}</b> units to stock.")
            except (TypeError, ValueError):
                await message.answer("Send a positive whole number of units.")
        elif flow == "force_channel":
            try:
                chat, title, username, invite = [part.strip() for part in (body or "").split("|", 3)]
                async def save_channel() -> None:
                    await db.add_channel(int(chat), title, username or None, invite or None)
                    await db.audit(message.from_user.id, "force_channel_added", "channel", chat)

                status, _ = await animate_message("Saving channel", save_channel)
                sessions.pop(message.from_user.id)
                await status.edit_text("✓ Force Subscribe channel added.")
            except Exception:
                await message.answer("Use: chat_id | title | @username | invite URL")
        elif flow == "force_remove":
            try:
                channel_id = int((body or "").strip())
                sessions.set(message.from_user.id, "force_remove_confirm", channel_id=channel_id)
                await message.answer("Confirm channel removal?", reply_markup=confirm_keyboard("a:force_remove_confirm", "a:home"))
            except ValueError:
                await message.answer("Send a numeric channel database ID.")
        elif flow == "content":
            content_key = session["key"]

            async def save_user_content() -> None:
                await db.save_content(content_key, body or "", kind, file_id)
                await db.audit(message.from_user.id, "content_changed", "content", content_key)

            status, _ = await animate_message(
                "Updating content",
                save_user_content,
            )
            sessions.pop(message.from_user.id)
            await status.edit_text("✓ Content saved to the database.")
        elif flow == "support_setup":
            try:
                username, link, button, instructions = [part.strip() for part in (body or "").split("|", 3)]
                async def save_support() -> None:
                    await db.set_setting("support_username", username)
                    await db.set_setting("support_link", link)
                    await db.set_setting("support_button_text", button)
                    await db.save_content("support", instructions)
                    await db.audit(message.from_user.id, "support_settings_changed", "setting", "support")

                status, _ = await animate_message(
                    "Saving support settings",
                    save_support,
                )
                sessions.pop(message.from_user.id)
                await status.edit_text("✓ Support settings saved.")
            except ValueError:
                await message.answer("Use: username | link | button text | instructions")
        elif flow == "broadcast":
            sessions.set(message.from_user.id, "broadcast_confirm", kind=kind, body=body, file_id=file_id)
            await message.answer("Broadcast preview:", reply_markup=confirm_keyboard("a:broadcast_confirm", "a:broadcast_cancel"))
            if kind == "text":
                await message.answer(body or "Empty message")
            else:
                await message.answer(f"Media type: {kind}\nCaption: {body or '—'}")
        elif flow == "admin_add":
            try:
                target = int((body or "").strip())

                async def add_admin() -> None:
                    await db.add_admin(target)
                    await db.audit(message.from_user.id, "admin_added", "admin", str(target))

                status, _ = await animate_message("Adding administrator", add_admin)
                sessions.pop(message.from_user.id)
                await status.edit_text("✓ Admin added.")
            except ValueError:
                await message.answer("Send a numeric Telegram User ID.")
        elif flow == "admin_remove":
            try:
                target = int((body or "").strip())

                async def remove_admin() -> None:
                    await db.remove_admin(target)
                    await db.audit(message.from_user.id, "admin_removed", "admin", str(target))

                status, _ = await animate_message("Removing administrator", remove_admin)
                sessions.pop(message.from_user.id)
                await status.edit_text("✓ Admin removed.")
            except ValueError:
                await message.answer("Send a numeric Telegram User ID.")
        elif flow == "admin_perms":
            permissions = {
                item.strip(): True
                for item in (body or "").split(",")
                if item.strip()
                in {"dashboard", "users", "rewards", "referrals", "force", "content", "broadcast", "settings"}
            }

            async def save_permissions() -> None:
                await db.set_admin_permissions(session["user_id"], permissions)
                await db.audit(
                    message.from_user.id,
                    "admin_permissions_changed",
                    "admin",
                    str(session["user_id"]),
                    permissions,
                )

            status, _ = await animate_message("Saving permissions", save_permissions)
            sessions.pop(message.from_user.id)
            await status.edit_text("✓ Admin permissions updated.")
        elif flow == "user_search":
            try:
                user_id = int((body or "").strip())
                status, rows = await animate_message(
                    "Searching users",
                    lambda: db.search_users(user_id, 1),
                )
                if not rows:
                    await status.edit_text("No user found.")
                    return
                user = rows[0]
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ Referrals", callback_data=f"a:addref:{user_id}"), InlineKeyboardButton(text="➕ Points", callback_data=f"a:addpts:{user_id}")],
                        [InlineKeyboardButton(text="🎁 Reward History", callback_data=f"a:urewards:{user_id}")],
                        [InlineKeyboardButton(text="🚫 Ban" if not user["banned"] else "✅ Unban", callback_data=f"a:{'ban' if not user['banned'] else 'unban'}:{user_id}")],
                        [InlineKeyboardButton(text="🔄 Reset Progress", callback_data=f"a:confirm_reset:{user_id}")],
                    ]
                )
                await status.edit_text(
                    screen(
                        "User Profile",
                        f"ID: <code>{user_id}</code>\nName: {user['first_name']}\n"
                        f"Username: @{user['username'] or '—'}\nJoined: {user['joined_at']:%d %b %Y}\n"
                        f"Referrals: {user['referral_count']}\nPoints: {user['points']}\n"
                        f"Verified: {user['is_verified']}\nDisclaimer: {user['disclaimer_accepted']}\n"
                        f"Banned: {user['banned']}",
                    ),
                    reply_markup=keyboard,
                )
                sessions.pop(message.from_user.id)
            except ValueError:
                await message.answer("Send a numeric Telegram User ID.")
        elif flow == "adjust":
            try:
                delta = int((body or "").strip())

                async def adjust_user() -> None:
                    await db.adjust_user(session["user_id"], session["field"], delta)
                    await db.audit(
                        message.from_user.id,
                        "user_value_adjusted",
                        "user",
                        str(session["user_id"]),
                        {"field": session["field"], "delta": delta},
                    )

                status, _ = await animate_message("Updating user data", adjust_user)
                sessions.pop(message.from_user.id)
                await status.edit_text("✓ User value updated and logged.")
            except ValueError:
                await message.answer("Send a whole number.")

    @router.callback_query(F.data == "a:bulk_confirm")
    async def bulk_confirm(callback: CallbackQuery) -> None:
        if not await allowed(callback.from_user.id):
            await callback.answer("Not authorized.", show_alert=True)
            return
        session = sessions.pop(callback.from_user.id)
        if not session or session["flow"] != "bulk_confirm":
            await callback.answer("Bulk session expired.", show_alert=True)
            return
        count = await db.bulk_add_rewards(session["required"], session["items"])
        await db.audit(callback.from_user.id, "bulk_rewards_added", "milestone", str(session["required"]), {"count": count})
        await callback.answer()
        await callback.message.edit_text(f"✓ Added {count} rewards safely.")

    @router.callback_query(F.data == "a:force_remove_confirm")
    async def force_remove_confirm(callback: CallbackQuery) -> None:
        if not await allowed(callback.from_user.id):
            await callback.answer("Not authorized.", show_alert=True)
            return
        session = sessions.pop(callback.from_user.id)
        if session and session["flow"] == "force_remove_confirm":
            await db.delete_channel(session["channel_id"])
            await db.audit(callback.from_user.id, "force_channel_removed", "channel", str(session["channel_id"]))
            await callback.answer()
            await callback.message.edit_text("✓ Channel removed.")

    return router
