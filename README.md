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

Create a Railway service from this repository and use the repository root as the service root (the runnable bot.py, db.py and Mini App server are at the root). Add these variables in Railway:

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


## Additive device verification and anti-abuse layer

The existing referral and reward flow now has a server-side Telegram Mini App verification gate. The order is /start → Verify Device → Mini App verification → disclaimer acceptance → existing access/referral completion. Existing users, referral rows, rewards, admin tools and Firebase/legacy migration behavior are preserved; this project currently uses PostgreSQL via DATABASE_URL.

The add-on includes:

- Official Telegram initData HMAC validation with expiry checks, user binding and one-time server-side verification sessions.
- Privacy-conscious hashed installation IDs, browser signal fingerprints, IPs and network identifiers; restricted device identifiers are never requested.
- Optional IPinfo reputation checks for VPN, proxy, Tor and hosting signals, with caching and safe provider failure behavior.
- Database-backed rate limits for API, Telegram account, installation, fingerprint, IP, network and referral scopes.
- A combined risk engine: low risk passes, medium risk asks for a fresh attempt, and high risk marks the attempt suspicious without crediting the referral reward.
- Transactional, idempotent completion and security event logging, with concurrency-safe PostgreSQL locks.
- Admin Panel → Security for medium/high-risk attempts and their non-raw correlation signals.

### Deployment variables

Set PUBLIC_BASE_URL or MINIAPP_URL to the HTTPS Railway URL. Add VERIFICATION_HASH_SECRET as a long random secret. IPINFO_TOKEN is optional; without it, the app still records hashed local correlations and does not claim provider-grade VPN detection. The remaining VERIFICATION_* and REPUTATION_CACHE_SECONDS variables use safe defaults shown in .env.example.

### Mini App and BotFather

The Mini App is served by the same process at /miniapp and calls /api/verification/start, /api/verification/complete, and /api/verification/status on the same origin. In BotFather, configure the bot's Menu Button Web App URL to the same HTTPS /miniapp URL if you want a persistent entry point; the required /start inline button is generated by the bot itself. Telegram's Web App URL must be HTTPS and match the deployed public domain.

### Limitations

No browser fingerprint, cookie, IP reputation service or Telegram Web App can be bypass-proof. Users may clear storage, change networks, use multiple devices, or share a legitimate network. The system intentionally combines independent signals, never treats one shared IP as proof of abuse, and keeps final referral credit on the server.

### Local security tests

Run python -m unittest test_security.py to exercise initData signing, tamper/expiry rejection, IP normalization and core risk decisions. Full PostgreSQL integration, Telegram Bot API behavior, provider responses and Railway deployment must still be tested in the target environment.
