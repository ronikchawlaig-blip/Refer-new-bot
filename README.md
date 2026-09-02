# Telegram Refer & Reward Bot

Production Telegram-native referral and reward bot. There is no website, no Vite
application, no React frontend, and no browser-based admin panel. Every user and
admin action happens inside Telegram using messages, inline keyboards, callbacks,
message editing, confirmations, pagination-ready database queries, and media uploads.

## Stack and architecture

- Python 3.12+
- aiogram 3 for Telegram updates, inline keyboards, media and long polling
- PostgreSQL via asyncpg for persistent state and transactional reward allocation
- Railway runs one worker process with `python bot.py`

The important database rules are enforced with primary keys, unique constraints,
foreign keys, row locks, `SKIP LOCKED`, and transactions. A referral is counted
only after force subscription and disclaimer acceptance. A reward is locked before
delivery and is never returned silently to the public pool after a failure.

## Included Telegram features

- Four-option user menu: Refer & Earn, My Rewards, My Progress, Support
- Permanent Admin Panel button shown only to registered admins and the Owner
- Permanent referral registration with no referrer switching or duplicate counting
- Multiple force-subscribe channels with enable/disable and removal
- Database-driven mandatory disclaimer and editable user-facing content
- Maintenance mode with admin bypass
- Text, links, codes, JSON-as-text, documents, APKs, photos, videos and GIF rewards
- Single and bulk reward ingestion with preview and confirmation
- Milestones, inventory, assignment and delivery history
- User search by Telegram ID, ban/unban, progress reset, points/referral adjustment
- Multi-admin Owner/Admin roles and audit logging
- Confirmation-first broadcast queue with persistent progress and rate limiting
- Fast edit-in-place Unicode spinner and progress-bar states during real work

## Local setup

1. Create a PostgreSQL database.
2. Copy `.env.example` to `.env`.
3. Add the BotFather token and the numeric Telegram ID of the Owner.
4. Set `DATABASE_URL`.
5. Install and run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

The bot must be an administrator in every force-subscribe channel so Telegram
can verify membership. `OWNER_TELEGRAM_ID` is also seeded as the database Owner.

## Railway deployment

Create a Railway service from this folder and set the service root directory to
`telegram-bot`. Add these variables in Railway:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL` (Railway PostgreSQL variable or external PostgreSQL URL)
- `OWNER_TELEGRAM_ID`
- Optional support and branding variables from `.env.example`

The start command is:

```bash
python bot.py
```

Use exactly one running replica for long polling. Scaling to multiple polling
replicas causes duplicate Telegram update consumers. Railway restarts are safe:
the referral, reward, delivery, audit and broadcast state is persisted in PostgreSQL.

## Telegram animation behavior

All in-chat loading states use only two programmatic animations and edit the
same bot message in place:

- Quick actions use the braille spinner frames `⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏`.
- Important reward, bulk and broadcast work uses the Unicode bar
  `▱▱▱▱▱▱▱▱▱▱` through `▰▰▰▰▰▰▰▰▰▰`, ending at `100%`.

Frames refresh quickly while the real operation is running. There are no
artificial loading delays, dice animations, random emoji loaders or
`Loading...`-only placeholders.

## Telegram button appearance

The keyboard uses Telegram's supported `primary` (blue) and `success` (green)
button styles in the compact two-row layout. Telegram clients may still apply
minor theme-specific differences to the final shade.
