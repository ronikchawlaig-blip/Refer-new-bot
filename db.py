from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  telegram_id BIGINT PRIMARY KEY,
  username TEXT,
  first_name TEXT NOT NULL DEFAULT '',
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  points INTEGER NOT NULL DEFAULT 0,
  referral_count INTEGER NOT NULL DEFAULT 0,
  force_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
  disclaimer_accepted BOOLEAN NOT NULL DEFAULT FALSE,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  banned BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS referrals (
  id BIGSERIAL PRIMARY KEY,
  referrer_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  referred_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('pending','subscribed','disclaimer_accepted','completed','invalid')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS force_channels (
  id BIGSERIAL PRIMARY KEY,
  chat_id BIGINT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  username TEXT,
  invite_url TEXT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  mandatory BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS milestones (
  id BIGSERIAL PRIMARY KEY,
  required_referrals INTEGER NOT NULL UNIQUE CHECK (required_referrals > 0),
  name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS rewards (
  id BIGSERIAL PRIMARY KEY,
  milestone_id BIGINT REFERENCES milestones(id) ON DELETE SET NULL,
  name TEXT NOT NULL DEFAULT 'Reward',
  kind TEXT NOT NULL,
  text_content TEXT,
  file_id TEXT,
  status TEXT NOT NULL DEFAULT 'available'
    CHECK (status IN ('available','reserved','assigned','delivered','failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS reward_assignments (
  id BIGSERIAL PRIMARY KEY,
  reward_id BIGINT NOT NULL UNIQUE REFERENCES rewards(id),
  user_id BIGINT NOT NULL REFERENCES users(telegram_id),
  milestone_id BIGINT REFERENCES milestones(id),
  status TEXT NOT NULL DEFAULT 'assigned'
    CHECK (status IN ('reserved','assigned','delivered','failed')),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  delivered_at TIMESTAMPTZ,
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_reward_per_user_milestone
  ON reward_assignments(user_id, milestone_id) WHERE milestone_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS stock_products (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  points_required INTEGER NOT NULL DEFAULT 0 CHECK (points_required >= 0),
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  kind TEXT NOT NULL DEFAULT 'text',
  text_content TEXT,
  file_id TEXT,
  how_to_use TEXT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE stock_products ADD COLUMN IF NOT EXISTS how_to_use TEXT;
CREATE TABLE IF NOT EXISTS stock_items (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES stock_products(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'text',
  text_content TEXT,
  file_id TEXT,
  status TEXT NOT NULL DEFAULT 'available'
    CHECK (status IN ('available','claimed','failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS stock_claims (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES stock_products(id) ON DELETE RESTRICT,
  item_id BIGINT REFERENCES stock_items(id) ON DELETE RESTRICT,
  user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'reserved'
    CHECK (status IN ('reserved','delivered','failed')),
  points_spent INTEGER NOT NULL DEFAULT 0,
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  delivered_at TIMESTAMPTZ,
  error TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (product_id, user_id)
);
ALTER TABLE stock_claims ADD COLUMN IF NOT EXISTS item_id BIGINT REFERENCES stock_items(id) ON DELETE RESTRICT;
ALTER TABLE stock_claims DROP CONSTRAINT IF EXISTS stock_claims_product_id_user_id_key;
CREATE TABLE IF NOT EXISTS admins (
  telegram_id BIGINT PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('owner','admin')),
  permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS content (
  key TEXT PRIMARY KEY,
  body TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'text',
  file_id TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS broadcasts (
  id BIGSERIAL PRIMARY KEY,
  sender_id BIGINT NOT NULL REFERENCES admins(telegram_id),
  kind TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','processing','completed','failed','cancelled')),
  total INTEGER NOT NULL DEFAULT 0,
  sent INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  admin_id BIGINT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

LEGACY_ID_MIGRATION = """
DO $body$
DECLARE
  r RECORD;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public'
      AND (table_name, column_name) IN (
        VALUES ('users','telegram_id'), ('referrals','referrer_id'),
               ('referrals','referred_id'), ('referrals','referred_user_id'),
               ('force_channels','chat_id'), ('reward_assignments','user_id'),
               ('stock_claims','user_id'), ('admins','telegram_id'),
               ('broadcasts','sender_id')
      )
      AND data_type IN ('smallint','integer')
  ) THEN
    CREATE TEMP TABLE bot_fk_backup (
      schema_name TEXT NOT NULL,
      table_name TEXT NOT NULL,
      constraint_name TEXT NOT NULL,
      constraint_definition TEXT NOT NULL
    ) ON COMMIT DROP;
    INSERT INTO bot_fk_backup (schema_name, table_name, constraint_name, constraint_definition)
    SELECT n.nspname, cls.relname, c.conname, pg_get_constraintdef(c.oid)
    FROM pg_constraint c
    JOIN pg_class cls ON cls.oid=c.conrelid
    JOIN pg_namespace n ON n.oid=cls.relnamespace
    WHERE c.contype='f' AND n.nspname='public';
    FOR r IN SELECT * FROM bot_fk_backup LOOP
      EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I', r.schema_name, r.table_name, r.constraint_name);
    END LOOP;
    FOR r IN
      SELECT table_name, column_name
      FROM information_schema.columns
      WHERE table_schema='public'
        AND (table_name, column_name) IN (
          VALUES ('users','telegram_id'), ('referrals','referrer_id'),
                 ('referrals','referred_id'), ('referrals','referred_user_id'),
                 ('force_channels','chat_id'), ('reward_assignments','user_id'),
                 ('stock_claims','user_id'), ('admins','telegram_id'),
                 ('broadcasts','sender_id')
        )
        AND data_type IN ('smallint','integer')
    LOOP
      EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I TYPE BIGINT USING %I::BIGINT', r.table_name, r.column_name, r.column_name);
    END LOOP;
    FOR r IN SELECT * FROM bot_fk_backup LOOP
      EXECUTE format('ALTER TABLE %I.%I ADD CONSTRAINT %I %s', r.schema_name, r.table_name, r.constraint_name, r.constraint_definition);
    END LOOP;
  END IF;
END
$body$;
"""

DEFAULT_CONTENT = {
    "welcome": "Welcome to <b>{bot_name}</b>.\n\nInvite friends, complete milestones, and unlock Telegram rewards.",
    "maintenance": "We are making a few improvements. Please check back shortly.",
    "disclaimer": (
        "⚠️ <b>IMPORTANT WARNING</b>\n\n"
        "Rewards are added to the bot in bulk, so occasionally you may receive a duplicate, "
        "expired, already-used, invalid, or non-working reward. If you receive only 1–2 such "
        "rewards, please do not contact Support, as minor issues can happen during bulk "
        "distribution. However, if you repeatedly receive the same issue across multiple "
        "rewards, you may contact the Support Bot and an admin will review the situation and "
        "assist where possible.\n\nBy clicking Accept & Continue, you confirm that you understand "
        "and accept these terms."
    ),
    "force_subscribe": "🔒 Please join every required channel below, then tap Verify subscription.",
    "support": "Tap below to open our Support Bot. Our team will respond as soon as possible.",
    "how_it_works": "Share your personal link. A referral becomes valid only after subscription verification and disclaimer acceptance.",
    "reward_success": "🎁 Your reward has been delivered.",
    "reward_empty": "Your next reward is not available yet. Please check back soon.",
    "error": "Something went wrong. Please try again in a moment.",
}


log = logging.getLogger(__name__)


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        self.referral_user_column = "referred_user_id"
        self.referral_state_column = "status"

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=10,
            command_timeout=30,
            max_inactive_connection_lifetime=300,
        )
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)
            # Some legacy Railway databases kept referred_id/status but omitted
            # the owner column. Add it without deleting or rewriting old rows.
            await conn.execute("ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
            await conn.execute(LEGACY_ID_MIGRATION)

            # Existing Railway databases may have an older audit_logs table.
            # Add the columns used by the current bot without deleting old data.
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS admin_id BIGINT")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS action TEXT")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS target_type TEXT")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS target_id TEXT")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS details JSONB DEFAULT '{}'::jsonb")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
            await conn.execute(
                "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ"
            )
            referral_columns = await conn.fetchrow(
                """
                SELECT
                  CASE
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='referred_user_id' AND NOT attisdropped
                    ) THEN 'referred_user_id'
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='referred_id' AND NOT attisdropped
                    ) THEN 'referred_id'
                    ELSE NULL
                  END AS user_column,
                  CASE
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='status' AND NOT attisdropped
                    ) THEN 'status'
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='state' AND NOT attisdropped
                    ) THEN 'state'
                    ELSE NULL
                  END AS state_column
                """
            )
            if referral_columns["user_column"] not in {"referred_id", "referred_user_id"}:
                raise RuntimeError("The referrals table has no referred_id/referred_user_id column")
            if referral_columns["state_column"] not in {"state", "status"}:
                raise RuntimeError("The referrals table has no state/status column")
            self.referral_user_column = referral_columns["user_column"]
            self.referral_state_column = referral_columns["state_column"]
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER NOT NULL DEFAULT 0")
            state_column = self._referral_state_column()
            await conn.execute(
                f"""
                UPDATE users AS u
                SET referral_count = (
                    SELECT COUNT(*)::int
                    FROM referrals AS r
                    WHERE r.referrer_id = u.telegram_id
                      AND r.{state_column} = 'completed'
                )
                """
            )
            await conn.execute(
                "UPDATE broadcasts SET status='queued' WHERE status='processing'"
            )
            await conn.execute(
                "INSERT INTO admins (telegram_id, role) VALUES ($1, 'owner') "
                "ON CONFLICT (telegram_id) DO UPDATE SET role='owner'",
                int(__import__("os").getenv("OWNER_TELEGRAM_ID", "0") or "0"),
            )
            for key, body in DEFAULT_CONTENT.items():
                await conn.execute(
                    "INSERT INTO content (key, body) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    key,
                    body,
                )
            for key, value in (
                ("referrals_enabled", "true"),
                ("maintenance_enabled", "false"),
                ("disclaimer_enabled", "true"),
                ("support_link", "https://t.me/Referrsupportt_bot"),
                ("support_username", "@Referrsupportt_bot"),
                ("support_button_text", "💬 Support"),
            ):
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    key,
                    value,
                )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _p(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Database is not connected")
        return self.pool

    def _referral_user_column(self) -> str:
        if self.referral_user_column not in {"referred_id", "referred_user_id"}:
            raise RuntimeError("Unsupported referrals user column")
        return self.referral_user_column

    def _referral_state_column(self) -> str:
        if self.referral_state_column not in {"state", "status"}:
            raise RuntimeError("Unsupported referrals state column")
        return self.referral_state_column

    async def _execute_referral_variants(
        self, conn: asyncpg.Connection, queries: tuple[str, ...], *args: Any
    ) -> str:
        last_error: asyncpg.exceptions.UndefinedColumnError | None = None
        for query in queries:
            try:
                async with conn.transaction():
                    return await conn.execute(query, *args)
            except asyncpg.exceptions.UndefinedColumnError as error:
                last_error = error
        if last_error:
            raise last_error
        raise RuntimeError("No referral query variants provided")

    async def _fetchrow_referral_variants(
        self, conn: asyncpg.Connection, queries: tuple[str, ...], *args: Any
    ) -> asyncpg.Record | None:
        last_error: asyncpg.exceptions.UndefinedColumnError | None = None
        for query in queries:
            try:
                async with conn.transaction():
                    return await conn.fetchrow(query, *args)
            except asyncpg.exceptions.UndefinedColumnError as error:
                last_error = error
        if last_error:
            raise last_error
        raise RuntimeError("No referral query variants provided")

    async def register_user(
        self, telegram_id: int, username: str | None, first_name: str, referrer_id: int | None
    ) -> tuple[dict[str, Any], int | None]:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT * FROM users WHERE telegram_id=$1 FOR UPDATE", telegram_id
                )
                if existing:
                    await conn.execute(
                        "UPDATE users SET username=$2, first_name=$3 WHERE telegram_id=$1",
                        telegram_id,
                        username,
                        first_name,
                    )
                    created_referrer_id = None
                    # A user may have opened the bot before clicking a referral link.
                    # Attribute the link only while their access is still unverified,
                    # and never replace an existing referral attribution.
                    if referrer_id and referrer_id != telegram_id and not existing["is_verified"]:
                        referrer_exists = await conn.fetchval(
                            "SELECT 1 FROM users WHERE telegram_id=$1", referrer_id
                        )
                        if referrer_exists:
                            user_column = self._referral_user_column()
                            state_column = self._referral_state_column()
                            referral = await conn.fetchrow(
                                f"INSERT INTO referrals (referrer_id, {user_column}, {state_column}) "
                                f"VALUES ($1,$2,'pending') ON CONFLICT ({user_column}) DO NOTHING "
                                "RETURNING referrer_id",
                                referrer_id,
                                telegram_id,
                            )
                            if referral:
                                created_referrer_id = referral["referrer_id"]
                    return (
                        dict(await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)),
                        created_referrer_id,
                    )
                await conn.execute(
                    "INSERT INTO users (telegram_id, username, first_name) VALUES ($1,$2,$3)",
                    telegram_id,
                    username,
                    first_name,
                )
                created_referrer_id = None
                if referrer_id and referrer_id != telegram_id:
                    referrer_exists = await conn.fetchval(
                        "SELECT 1 FROM users WHERE telegram_id=$1", referrer_id
                    )
                    if referrer_exists:
                        user_column = self._referral_user_column()
                        state_column = self._referral_state_column()
                        referral = await conn.fetchrow(
                            f"INSERT INTO referrals (referrer_id, {user_column}, {state_column}) "
                            f"VALUES ($1,$2,'pending') ON CONFLICT ({user_column}) DO NOTHING "
                            "RETURNING referrer_id",
                            referrer_id,
                            telegram_id,
                        )
                        if referral:
                            created_referrer_id = referral["referrer_id"]
                return (
                    dict(await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)),
                    created_referrer_id,
                )
    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = await self._p().fetchrow("SELECT * FROM users WHERE telegram_id=$1", user_id)
        return dict(row) if row else None

    async def referral_stats(self, referrer_id: int) -> dict[str, int]:
        state_column = self._referral_state_column()
        async with self._p().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT
                      COUNT(*)::int AS total_referrals,
                      COUNT(*) FILTER (WHERE {state_column}='completed')::int AS valid_referrals,
                      COUNT(*) FILTER (WHERE {state_column}<>'completed')::int AS invalid_referrals
                    FROM referrals
                    WHERE referrer_id=$1
                    """,
                    referrer_id,
                )
        return dict(row)

    async def is_admin(self, user_id: int, permission: str | None = None) -> bool:
        row = await self._p().fetchrow(
            "SELECT role, permissions FROM admins WHERE telegram_id=$1", user_id
        )
        if not row:
            return False
        if row["role"] == "owner" or not permission:
            return True
        permissions = row["permissions"] or {}
        return bool(permissions.get(permission))

    async def admin_role(self, user_id: int) -> str | None:
        return await self._p().fetchval("SELECT role FROM admins WHERE telegram_id=$1", user_id)

    async def get_setting(self, key: str, default: str = "") -> str:
        return await self._p().fetchval("SELECT value FROM settings WHERE key=$1", key) or default

    async def set_setting(self, key: str, value: str) -> None:
        await self._p().execute(
            "INSERT INTO settings (key,value) VALUES ($1,$2) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            key,
            value,
        )

    async def get_content(self, key: str) -> dict[str, Any]:
        row = await self._p().fetchrow(
            "SELECT key,body,kind,file_id FROM content WHERE key=$1", key
        )
        return dict(row) if row else {"key": key, "body": ""}

    async def save_content(self, key: str, body: str, kind: str = "text", file_id: str | None = None) -> None:
        await self._p().execute(
            "INSERT INTO content (key,body,kind,file_id) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (key) DO UPDATE SET body=EXCLUDED.body, kind=EXCLUDED.kind, "
            "file_id=EXCLUDED.file_id, updated_at=NOW()",
            key,
            body,
            kind,
            file_id,
        )

    async def active_channels(self) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            "SELECT * FROM force_channels WHERE enabled AND mandatory ORDER BY sort_order,id"
        )
        return [dict(row) for row in rows]

    async def list_channels(self) -> list[dict[str, Any]]:
        rows = await self._p().fetch("SELECT * FROM force_channels ORDER BY sort_order,id")
        return [dict(row) for row in rows]

    async def add_channel(
        self, chat_id: int, title: str, username: str | None, invite_url: str | None
    ) -> None:
        order = await self._p().fetchval("SELECT COALESCE(MAX(sort_order),0)+1 FROM force_channels")
        await self._p().execute(
            "INSERT INTO force_channels (chat_id,title,username,invite_url,sort_order) "
            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (chat_id) DO UPDATE SET title=EXCLUDED.title, "
            "username=EXCLUDED.username, invite_url=EXCLUDED.invite_url, enabled=TRUE",
            chat_id,
            title,
            username,
            invite_url,
            order,
        )

    async def toggle_channel(self, channel_id: int) -> None:
        await self._p().execute(
            "UPDATE force_channels SET enabled=NOT enabled WHERE id=$1", channel_id
        )

    async def delete_channel(self, channel_id: int) -> None:
        await self._p().execute("DELETE FROM force_channels WHERE id=$1", channel_id)

    async def move_channel(self, channel_id: int, direction: int) -> None:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "SELECT id,sort_order FROM force_channels WHERE id=$1 FOR UPDATE", channel_id
                )
                if not current:
                    return
                target = await conn.fetchrow(
                    "SELECT id,sort_order FROM force_channels WHERE sort_order "
                    + ("<" if direction < 0 else ">")
                    + " $1 ORDER BY sort_order "
                    + ("DESC" if direction < 0 else "ASC")
                    + " LIMIT 1 FOR UPDATE",
                    current["sort_order"],
                )
                if target:
                    await conn.execute(
                        "UPDATE force_channels SET sort_order=$1 WHERE id=$2",
                        target["sort_order"],
                        current["id"],
                    )
                    await conn.execute(
                        "UPDATE force_channels SET sort_order=$1 WHERE id=$2",
                        current["sort_order"],
                        target["id"],
                    )

    async def mark_subscribed(self, user_id: int) -> None:
        async with self._p().acquire() as conn:
            await conn.execute(
                "UPDATE users SET force_subscribed=TRUE WHERE telegram_id=$1", user_id
            )
            user_column = self._referral_user_column()
            state_column = self._referral_state_column()
            await conn.execute(
                f"UPDATE referrals SET {state_column}='subscribed' "
                f"WHERE {user_column}=$1 AND {state_column}='pending'",
                user_id,
            )

    async def accept_disclaimer(self, user_id: int) -> None:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE users SET disclaimer_accepted=TRUE WHERE telegram_id=$1", user_id
                )
                user_column = self._referral_user_column()
                state_column = self._referral_state_column()
                await conn.execute(
                    f"UPDATE referrals SET {state_column}='disclaimer_accepted' "
                    f"WHERE {user_column}=$1 AND {state_column} IN ('pending','subscribed')",
                    user_id,
                )

    async def complete_gate(self, user_id: int) -> int | None:
        user_column = self._referral_user_column()
        state_column = self._referral_state_column()
        async with self._p().acquire() as conn:
            async with conn.transaction():
                # Keep verification and referral accounting in one transaction.
                # If either update fails, neither state is committed.
                row = await conn.fetchrow(
                    f"UPDATE referrals SET {state_column}='completed', completed_at=NOW() "
                    f"WHERE {user_column}=$1 AND {state_column} IN "
                    "('pending','subscribed','disclaimer_accepted') "
                    "RETURNING referrer_id",
                    user_id,
                )
                await conn.execute(
                    "UPDATE users SET is_verified=TRUE WHERE telegram_id=$1", user_id
                )
                if not row:
                    return None
                await conn.execute(
                    "UPDATE users SET referral_count=referral_count+1, points=points+1 "
                    "WHERE telegram_id=$1",
                    row["referrer_id"],
                )
                return row["referrer_id"]
    async def dashboard(self) -> dict[str, int]:
        try:
            row = await self._p().fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM users)::int total_users,
              (SELECT COUNT(*) FROM users WHERE joined_at >= NOW()-INTERVAL '24 hours')::int new_users,
              (SELECT COUNT(*) FROM users WHERE is_verified)::int verified_users,
              (SELECT COUNT(*) FROM referrals WHERE status='completed')::int completed_referrals,
              (SELECT COUNT(*) FROM referrals WHERE status IN ('pending','subscribed','disclaimer_accepted'))::int pending_referrals,
              (SELECT COUNT(*) FROM rewards WHERE status='available')::int available_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status IN ('assigned','delivered'))::int assigned_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status='delivered')::int delivered_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status='failed')::int failed_deliveries,
              (SELECT COUNT(*) FROM stock_products WHERE enabled)::int stock_products,
              (SELECT COALESCE(SUM(
                p.stock + (SELECT COUNT(*) FROM stock_items si
                           WHERE si.product_id=p.id AND si.status='available')
              ),0) FROM stock_products p WHERE p.enabled)::int stock_units,
              (SELECT COUNT(*) FROM users WHERE banned)::int banned_users
            """
            )
        except asyncpg.exceptions.UndefinedColumnError:
            row = await self._p().fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM users)::int total_users,
              (SELECT COUNT(*) FROM users WHERE joined_at >= NOW()-INTERVAL '24 hours')::int new_users,
              (SELECT COUNT(*) FROM users WHERE is_verified)::int verified_users,
              (SELECT COUNT(*) FROM referrals WHERE state='completed')::int completed_referrals,
              (SELECT COUNT(*) FROM referrals WHERE state IN ('pending','subscribed','disclaimer_accepted'))::int pending_referrals,
              (SELECT COUNT(*) FROM rewards WHERE status='available')::int available_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status IN ('assigned','delivered'))::int assigned_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status='delivered')::int delivered_rewards,
              (SELECT COUNT(*) FROM rewards WHERE status='failed')::int failed_deliveries,
              (SELECT COUNT(*) FROM stock_products WHERE enabled)::int stock_products,
              (SELECT COALESCE(SUM(
                p.stock + (SELECT COUNT(*) FROM stock_items si
                           WHERE si.product_id=p.id AND si.status='available')
              ),0) FROM stock_products p WHERE p.enabled)::int stock_units,
              (SELECT COUNT(*) FROM users WHERE banned)::int banned_users
            """
            )
        return dict(row)

    async def create_milestone(self, required: int, name: str) -> None:
        await self._p().execute(
            "INSERT INTO milestones (required_referrals,name) VALUES ($1,$2) "
            "ON CONFLICT (required_referrals) DO UPDATE SET name=EXCLUDED.name, enabled=TRUE",
            required,
            name,
        )

    async def list_milestones(self) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            "SELECT m.*, COUNT(r.id)::int AS available_count FROM milestones m "
            "LEFT JOIN rewards r ON r.milestone_id=m.id AND r.status='available' "
            "GROUP BY m.id ORDER BY m.required_referrals"
        )
        return [dict(row) for row in rows]

    async def toggle_milestone(self, milestone_id: int) -> None:
        await self._p().execute(
            "UPDATE milestones SET enabled=NOT enabled WHERE id=$1", milestone_id
        )

    async def delete_milestone(self, milestone_id: int) -> None:
        await self._p().execute("DELETE FROM milestones WHERE id=$1", milestone_id)

    async def add_reward(
        self,
        milestone_required: int,
        name: str,
        kind: str,
        text_content: str | None,
        file_id: str | None,
    ) -> int:
        milestone = await self._p().fetchrow(
            "SELECT id FROM milestones WHERE required_referrals=$1", milestone_required
        )
        if not milestone:
            await self.create_milestone(milestone_required, f"{milestone_required} referrals")
            milestone = await self._p().fetchrow(
                "SELECT id FROM milestones WHERE required_referrals=$1", milestone_required
            )
        return await self._p().fetchval(
            "INSERT INTO rewards (milestone_id,name,kind,text_content,file_id) "
            "VALUES ($1,$2,$3,$4,$5) RETURNING id",
            milestone["id"],
            name,
            kind,
            text_content,
            file_id,
        )

    async def bulk_add_rewards(
        self, milestone_required: int, items: list[tuple[str, str, str | None, str | None]]
    ) -> int:
        count = 0
        for name, kind, body, file_id in items:
            await self.add_reward(milestone_required, name, kind, body, file_id)
            count += 1
        return count

    async def inventory(self) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            "SELECT status, COUNT(*)::int AS count FROM rewards GROUP BY status ORDER BY status"
        )
        return [dict(row) for row in rows]

    async def claim_rewards(self, user_id: int) -> list[dict[str, Any]]:
        user = await self._p().fetchrow("SELECT referral_count FROM users WHERE telegram_id=$1", user_id)
        if not user:
            return []
        async with self._p().acquire() as conn:
            async with conn.transaction():
                milestones = await conn.fetch(
                    "SELECT * FROM milestones WHERE enabled AND required_referrals <= $1 "
                    "ORDER BY required_referrals",
                    user["referral_count"],
                )
                claimed: list[dict[str, Any]] = []
                for milestone in milestones:
                    exists = await conn.fetchval(
                        "SELECT 1 FROM reward_assignments WHERE user_id=$1 AND milestone_id=$2",
                        user_id,
                        milestone["id"],
                    )
                    if exists:
                        continue
                    reward = await conn.fetchrow(
                        "SELECT * FROM rewards WHERE milestone_id=$1 AND status='available' "
                        "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",
                        milestone["id"],
                    )
                    if not reward:
                        continue
                    await conn.execute(
                        "UPDATE rewards SET status='assigned' WHERE id=$1", reward["id"]
                    )
                    await conn.execute(
                        "INSERT INTO reward_assignments (reward_id,user_id,milestone_id,status) "
                        "VALUES ($1,$2,$3,'assigned')",
                        reward["id"],
                        user_id,
                        milestone["id"],
                    )
                    claimed.append(dict(reward))
                return claimed

    async def mark_reward(self, reward_id: int, user_id: int, delivered: bool, error: str = "") -> None:
        status = "delivered" if delivered else "failed"
        async with self._p().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE reward_assignments SET status=$1, delivered_at=CASE WHEN $2 THEN NOW() END, "
                    "error=$3, attempt_count=attempt_count+1 WHERE reward_id=$4 AND user_id=$5",
                    status,
                    delivered,
                    error[:1000],
                    reward_id,
                    user_id,
                )
                await conn.execute("UPDATE rewards SET status=$1 WHERE id=$2", status, reward_id)

    async def retry_failed_reward(self, reward_id: int) -> bool:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT user_id FROM reward_assignments WHERE reward_id=$1 AND status='failed' FOR UPDATE",
                    reward_id,
                )
                if not row:
                    return False
                await conn.execute(
                    "UPDATE reward_assignments SET status='assigned', error=NULL WHERE reward_id=$1",
                    reward_id,
                )
                await conn.execute(
                    "UPDATE rewards SET status='assigned' WHERE id=$1", reward_id
                )
                return True

    async def user_reward_history(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            "SELECT ra.*, r.name, r.kind, r.text_content FROM reward_assignments ra "
            "JOIN rewards r ON r.id=ra.reward_id WHERE ra.user_id=$1 ORDER BY ra.assigned_at DESC LIMIT 30",
            user_id,
        )
        return [dict(row) for row in rows]

    async def list_stock_products(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled"
        rows = await self._p().fetch(
            f"""
            SELECT p.*,
              COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='available'
              ),0) AS available_codes,
              COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='claimed'
              ),0) AS used_codes,
              COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='failed'
              ),0) AS failed_codes,
              p.stock + COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='available'
              ),0) AS available_stock
            FROM stock_products p
            {where}
            ORDER BY enabled DESC, created_at DESC, id DESC
            """
        )
        return [dict(row) for row in rows]

    async def get_stock_product(self, product_id: int) -> dict[str, Any] | None:
        row = await self._p().fetchrow(
            """
            SELECT p.*,
              p.stock + COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='available'
              ),0) AS available_stock,
              COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='claimed'
              ),0) AS used_codes,
              COALESCE((
                SELECT COUNT(*)::int FROM stock_items si
                WHERE si.product_id=p.id AND si.status='failed'
              ),0) AS failed_codes
            FROM stock_products p WHERE p.id=$1
            """,
            product_id,
        )
        return dict(row) if row else None

    async def add_stock_product(
        self,
        name: str,
        points_required: int,
    ) -> int:
        return await self._p().fetchval(
            "INSERT INTO stock_products "
            "(name,points_required) VALUES ($1,$2) RETURNING id",
            name[:120],
            points_required,
        )

    async def add_stock_item(
        self,
        product_id: int,
        kind: str,
        text_content: str | None,
        file_id: str | None,
    ) -> int:
        return await self._p().fetchval(
            "INSERT INTO stock_items (product_id,kind,text_content,file_id) "
            "VALUES ($1,$2,$3,$4) RETURNING id",
            product_id,
            kind,
            text_content,
            file_id,
        )

    async def update_stock_how_to_use(self, product_id: int, how_to_use: str) -> bool:
        updated = await self._p().execute(
            "UPDATE stock_products SET how_to_use=$1 WHERE id=$2",
            how_to_use[:4000],
            product_id,
        )
        return updated.endswith("1")

    async def restock_product(self, product_id: int, amount: int) -> bool:
        updated = await self._p().execute(
            "UPDATE stock_products SET stock=stock+$1 WHERE id=$2",
            amount,
            product_id,
        )
        return updated.endswith("1")

    async def toggle_stock_product(self, product_id: int) -> None:
        await self._p().execute(
            "UPDATE stock_products SET enabled=NOT enabled WHERE id=$1", product_id
        )

    async def claim_stock_product(
        self, user_id: int, product_id: int
    ) -> tuple[str, dict[str, Any] | None]:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    "SELECT points,is_verified,banned FROM users WHERE telegram_id=$1 FOR UPDATE",
                    user_id,
                )
                if not user:
                    return "user_not_found", None
                if user["banned"]:
                    return "banned", None
                if not user["is_verified"]:
                    return "not_verified", None
                product = await conn.fetchrow(
                    "SELECT * FROM stock_products WHERE id=$1 FOR UPDATE", product_id
                )
                if not product or not product["enabled"]:
                    return "unavailable", None
                item = await conn.fetchrow(
                    "SELECT * FROM stock_items WHERE product_id=$1 AND status='available' "
                    "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",
                    product_id,
                )
                legacy_stock = product["stock"] > 0 and (
                    product["text_content"] or product["file_id"]
                )
                if not item and not legacy_stock:
                    return "out_of_stock", dict(product)
                if user["points"] < product["points_required"]:
                    return "insufficient_points", dict(product)
                await conn.execute(
                    "UPDATE users SET points=points-$1 WHERE telegram_id=$2",
                    product["points_required"],
                    user_id,
                )
                if item:
                    await conn.execute(
                        "UPDATE stock_items SET status='claimed' WHERE id=$1", item["id"]
                    )
                    claim = await conn.fetchrow(
                        "INSERT INTO stock_claims "
                        "(product_id,item_id,user_id,status,points_spent) "
                        "VALUES ($1,$2,$3,'reserved',$4) "
                        "RETURNING id,product_id,item_id,user_id,status,points_spent,claimed_at",
                        product_id,
                        item["id"],
                        user_id,
                        product["points_required"],
                    )
                    reward = dict(item)
                else:
                    await conn.execute(
                        "UPDATE stock_products SET stock=stock-1 WHERE id=$1", product_id
                    )
                    claim = await conn.fetchrow(
                        "INSERT INTO stock_claims "
                        "(product_id,user_id,status,points_spent) VALUES ($1,$2,'reserved',$3) "
                        "RETURNING id,product_id,item_id,user_id,status,points_spent,claimed_at",
                        product_id,
                        user_id,
                        product["points_required"],
                    )
                    reward = dict(product)
                result = dict(product)
                result.update(reward)
                result.update(dict(claim))
                result["remaining_points"] = user["points"] - product["points_required"]
                return "claimed", result

    async def mark_stock_claim(
        self, claim_id: int, user_id: int, delivered: bool, error: str = ""
    ) -> None:
        status = "delivered" if delivered else "failed"
        await self._p().execute(
            "UPDATE stock_claims SET status=$1, delivered_at=CASE WHEN $2 THEN NOW() END, "
            "error=$3, attempt_count=attempt_count+1 "
            "WHERE id=$4 AND user_id=$5",
            status,
            delivered,
            error[:1000],
            claim_id,
            user_id,
        )
        await self._p().execute(
            "UPDATE stock_items SET status=$1 WHERE id=("
            "SELECT item_id FROM stock_claims WHERE id=$2 AND user_id=$3) "
            "AND status='claimed'",
            status,
            claim_id,
            user_id,
        )

    async def user_claim_history(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            """
            SELECT source, item_id, name, status, claimed_at, points_spent
            FROM (
              SELECT 'milestone'::text AS source, ra.reward_id AS item_id, r.name,
                     ra.status, ra.assigned_at AS claimed_at, 0::int AS points_spent
              FROM reward_assignments ra
              JOIN rewards r ON r.id=ra.reward_id
              WHERE ra.user_id=$1
              UNION ALL
              SELECT 'stock'::text AS source, sc.product_id AS item_id, sp.name,
                     sc.status, sc.claimed_at, sc.points_spent
              FROM stock_claims sc
              JOIN stock_products sp ON sp.id=sc.product_id
              WHERE sc.user_id=$1
            ) history
            ORDER BY claimed_at DESC
            LIMIT 30
            """,
            user_id,
        )
        return [dict(row) for row in rows]

    async def search_users(self, user_id: int | None = None, limit: int = 12) -> list[dict[str, Any]]:
        query = "SELECT * FROM users "
        args: list[Any] = []
        if user_id is not None:
            query += "WHERE telegram_id=$1 "
            args.append(user_id)
        query += "ORDER BY joined_at DESC LIMIT $" + str(len(args) + 1)
        args.append(limit)
        rows = await self._p().fetch(query, *args)
        return [dict(row) for row in rows]

    async def adjust_user(self, user_id: int, field: str, delta: int) -> None:
        if field not in {"referral_count", "points"}:
            raise ValueError("Invalid adjustment field")
        await self._p().execute(
            f"UPDATE users SET {field}=GREATEST(0,{field}+$1) WHERE telegram_id=$2",
            delta,
            user_id,
        )

    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self._p().execute("UPDATE users SET banned=$1 WHERE telegram_id=$2", banned, user_id)

    async def reset_progress(self, user_id: int) -> None:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE users SET referral_count=0, points=0, is_verified=FALSE WHERE telegram_id=$1",
                    user_id,
                )
                user_column = self._referral_user_column()
                state_column = self._referral_state_column()
                await conn.execute(
                    f"UPDATE referrals SET {state_column}='invalid' "
                    f"WHERE referrer_id=$1 OR {user_column}=$1",
                    user_id,
                )

    async def list_admins(self) -> list[dict[str, Any]]:
        return [dict(row) for row in await self._p().fetch("SELECT * FROM admins ORDER BY role,telegram_id")]

    async def add_admin(self, user_id: int, role: str = "admin") -> None:
        await self._p().execute(
            "INSERT INTO admins (telegram_id,role) VALUES ($1,$2) "
            "ON CONFLICT (telegram_id) DO UPDATE SET role=EXCLUDED.role",
            user_id,
            role,
        )

    async def remove_admin(self, user_id: int) -> None:
        await self._p().execute("DELETE FROM admins WHERE telegram_id=$1 AND role <> 'owner'", user_id)

    async def set_admin_permissions(self, user_id: int, permissions: dict[str, bool]) -> None:
        await self._p().execute(
            "UPDATE admins SET permissions=$1::jsonb WHERE telegram_id=$2 AND role <> 'owner'",
            json.dumps(permissions),
            user_id,
        )

    async def audit(
        self,
        admin_id: int,
        action: str,
        target_type: str = "",
        target_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._p().execute(
            "INSERT INTO audit_logs (admin_id,action,target_type,target_id,details) "
            "VALUES ($1,$2,$3,$4,$5::jsonb)",
            admin_id,
            action,
            target_type,
            target_id,
            json.dumps(details or {}),
        )

    async def logs(self, limit: int = 12, offset: int = 0) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT $1 OFFSET $2", limit, offset
        )
        return [dict(row) for row in rows]

    async def create_broadcast(self, sender_id: int, kind: str, payload: dict[str, Any]) -> int:
        return await self._p().fetchval(
            "INSERT INTO broadcasts (sender_id,kind,payload) VALUES ($1,$2,$3::jsonb) RETURNING id",
            sender_id,
            kind,
            json.dumps(payload),
        )

    async def next_broadcast(self) -> dict[str, Any] | None:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM broadcasts WHERE status='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1"
                )
                if not row:
                    return None
                await conn.execute(
                    "UPDATE broadcasts SET status='processing' WHERE id=$1", row["id"]
                )
                return dict(row)

    async def update_broadcast(self, job_id: int, total: int, sent: int, failed: int, done: bool) -> None:
        await self._p().execute(
            "UPDATE broadcasts SET total=$2,sent=$3,failed=$4,status=$5,"
            "finished_at=CASE WHEN $6 THEN NOW() ELSE finished_at END WHERE id=$1",
            job_id,
            total,
            sent,
            failed,
            "completed" if done else "processing",
            done,
        )

    async def all_verified_users(self) -> list[int]:
        rows = await self._p().fetch("SELECT telegram_id FROM users WHERE is_verified AND NOT banned")
        return [row["telegram_id"] for row in rows]
