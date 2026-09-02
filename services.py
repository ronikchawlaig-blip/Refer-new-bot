from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from db import Database
from ui import progress_bar

T = TypeVar("T")
log = logging.getLogger(__name__)
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
PROGRESS_LEVELS = (0, 20, 40, 60, 80)
ANIMATION_INTERVAL = 0.12


async def _edit_animation(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        # Telegram returns this when two adjacent frames are identical or
        # when the operation has already edited the message to its final state.
        pass


async def animated(
    message: Message,
    operation: Callable[[], Awaitable[T]],
    label: str = "Processing",
    progress: bool = False,
    finish: bool = True,
) -> T:
    task = asyncio.create_task(operation())
    frame = 0
    await _edit_animation(
        message,
        f"{SPINNER_FRAMES[0]} {label}…"
        + (f"\n{progress_bar(PROGRESS_LEVELS[0])}" if progress else ""),
    )
    while True:
        done, _ = await asyncio.wait({task}, timeout=ANIMATION_INTERVAL)
        if done:
            break
        frame += 1
        if progress:
            level = PROGRESS_LEVELS[min(frame // 2, len(PROGRESS_LEVELS) - 1)]
            suffix = f"\n{progress_bar(level)}"
        else:
            suffix = ""
        await _edit_animation(
            message,
            f"{SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]} {label}…{suffix}",
        )
    result = await task
    if finish:
        final = f"✓ {label} complete"
        if progress:
            final += f"\n{progress_bar(100)}"
        await _edit_animation(message, final)
    return result


async def send_reward(bot: Bot, user_id: int, reward: dict[str, Any]) -> None:
    kind = reward["kind"]
    body = reward.get("text_content") or ""
    file_id = reward.get("file_id")
    if kind == "photo" and file_id:
        await bot.send_photo(user_id, file_id, caption=body or None)
    elif kind == "video" and file_id:
        await bot.send_video(user_id, file_id, caption=body or None)
    elif kind == "animation" and file_id:
        await bot.send_animation(user_id, file_id, caption=body or None)
    elif kind in {"document", "file"} and file_id:
        await bot.send_document(user_id, file_id, caption=body or None)
    else:
        await bot.send_message(user_id, body or "Your reward is ready.")


async def send_stock_how_to_use(bot: Bot, user_id: int, how_to_use: str | None) -> None:
    if how_to_use:
        await bot.send_message(user_id, f"📖 <b>How to use</b>\n\n{how_to_use}")


async def send_broadcast(bot: Bot, user_id: int, job: dict[str, Any]) -> None:
    payload = job["payload"]
    kind = job["kind"]
    body = payload.get("body") or ""
    file_id = payload.get("file_id")
    if kind == "photo" and file_id:
        await bot.send_photo(user_id, file_id, caption=body or None)
    elif kind == "video" and file_id:
        await bot.send_video(user_id, file_id, caption=body or None)
    elif kind == "animation" and file_id:
        await bot.send_animation(user_id, file_id, caption=body or None)
    elif kind in {"document", "file"} and file_id:
        await bot.send_document(user_id, file_id, caption=body or None)
    else:
        await bot.send_message(user_id, body or "Update")


async def broadcast_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            job = await db.next_broadcast()
            if not job:
                await asyncio.sleep(2)
                continue
            users = await db.all_verified_users()
            sent = failed = 0
            total = len(users)
            await db.update_broadcast(job["id"], total, sent, failed, total == 0)
            await _broadcast_status(bot, job, total, sent, failed, total == 0)
            for index, user_id in enumerate(users, start=1):
                try:
                    await send_broadcast(bot, user_id, job)
                    sent += 1
                except (TelegramForbiddenError, TelegramBadRequest):
                    failed += 1
                except Exception:
                    failed += 1
                    log.exception("Broadcast delivery failed")
                await asyncio.sleep(0.04)
                done = index == total
                await db.update_broadcast(job["id"], total, sent, failed, done)
                if done or index == 1 or index % max(1, total // 10) == 0:
                    await _broadcast_status(bot, job, total, sent, failed, done)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Broadcast worker cycle failed")
            await asyncio.sleep(3)


async def _broadcast_status(
    bot: Bot,
    job: dict[str, Any],
    total: int,
    sent: int,
    failed: int,
    done: bool,
) -> None:
    payload = job.get("payload") or {}
    chat_id = payload.get("status_chat_id")
    message_id = payload.get("status_message_id")
    if not chat_id or not message_id:
        return
    processed = sent + failed
    percent = 100 if done else round(processed / max(1, total) * 100)
    if done:
        text = (
            f"✓ Broadcast complete\n{progress_bar(100)}\n\n"
            f"Delivered: <b>{sent}</b>\nFailed: <b>{failed}</b>"
        )
    else:
        text = (
            f"{SPINNER_FRAMES[processed % len(SPINNER_FRAMES)]} Broadcasting…\n"
            f"{progress_bar(percent)}\n\n"
            f"Delivered: <b>{sent}</b> · Failed: <b>{failed}</b>"
        )
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass
