from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.enums import ButtonStyle


def main_menu(
    support_text: str = "💬 Support",
    show_admin_panel: bool = False,
) -> ReplyKeyboardMarkup:
    # Telegram supports primary (blue) and success (green) styles for bot buttons.
    # Keep the compact two-row layout from the reference.
    keyboard = [
        [
            KeyboardButton(text="👥 Refer & Earn", style=ButtonStyle.PRIMARY),
            KeyboardButton(text="🛍 Stock", style=ButtonStyle.PRIMARY),
        ],
        [
            KeyboardButton(text="🎁 My Rewards", style=ButtonStyle.PRIMARY),
            KeyboardButton(text="📊 My Progress", style=ButtonStyle.SUCCESS),
        ],
        [KeyboardButton(text=support_text, style=ButtonStyle.SUCCESS)],
    ]
    if show_admin_panel:
        keyboard.append(
            [KeyboardButton(text="⚙️ Admin Panel", style=ButtonStyle.PRIMARY)]
        )
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose an option",
    )


def back_keyboard(callback: str = "a:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Back", callback_data=callback)]]
    )


def gate_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        label = channel["title"][:28] or f"Channel {channel['id']}"
        if channel.get("invite_url"):
            rows.append([InlineKeyboardButton(text=f"🔒 {label}", url=channel["invite_url"])])
        elif channel.get("username"):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🔒 {label}",
                        url=f"https://t.me/{channel['username'].lstrip('@')}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="✓ Verify subscription", callback_data="u:verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def disclaimer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Accept & Continue", callback_data="u:accept")],
        ]
    )


def stock_products_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        name = str(product["name"])[:24]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{name} · {product['points_required']} pts · {product['available_stock']} left",
                    callback_data=f"u:stock:{product['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Back", callback_data="u:stock_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_product_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Claim now", callback_data=f"u:stock_claim:{product_id}")],
            [InlineKeyboardButton(text="← Back to Stock", callback_data="u:stock")],
        ]
    )


def admin_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Dashboard", callback_data="a:dashboard"),
                InlineKeyboardButton(text="🎁 Rewards", callback_data="a:rewards"),
            ],
            [
                InlineKeyboardButton(text="👥 Users", callback_data="a:users"),
                InlineKeyboardButton(text="🎯 Referrals", callback_data="a:referrals"),
            ],
            [
                InlineKeyboardButton(text="🔒 Force Subscribe", callback_data="a:force"),
                InlineKeyboardButton(text="📝 Content", callback_data="a:content"),
            ],
            [
                InlineKeyboardButton(text="📢 Broadcast", callback_data="a:broadcast"),
                InlineKeyboardButton(text="⚙️ Settings", callback_data="a:settings"),
            ],
            [
                InlineKeyboardButton(text="👑 Admins", callback_data="a:admins"),
                InlineKeyboardButton(text="📜 Audit Logs", callback_data="a:logs"),
            ],
        ]
    )


def admin_section(
    rows: list[list[tuple[str, str]]],
    back: str = "a:home",
) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows
    ]
    keyboard.append(
        [
            InlineKeyboardButton(text="← Back", callback_data=back),
            InlineKeyboardButton(text="🏠 Admin Home", callback_data="a:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def confirm_keyboard(yes: str, no: str = "a:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=yes),
                InlineKeyboardButton(text="Cancel", callback_data=no),
            ]
        ]
    )


def screen(title: str, body: str) -> str:
    return f"<b>{title}</b>\n\n{body}"


def progress_bar(percent: int, blocks: int = 10) -> str:
    filled = max(0, min(blocks, round(percent / 100 * blocks)))
    return "▰" * filled + "▱" * (blocks - filled) + f" {percent}%"
