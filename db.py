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
  device_verified BOOLEAN NOT NULL DEFAULT FALSE,
  device_verified_at TIMESTAMPTZ,
  banned BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS referrals (
  id BIGSERIAL PRIMARY KEY,
  referrer_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  referred_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('pending','subscribed','disclaimer_accepted','completed','invalid')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  security_status TEXT NOT NULL DEFAULT 'clear' CHECK (security_status IN ('clear','review','suspicious'))
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
CREATE TABLE IF NOT EXISTS security_verification_attempts (
  id BIGSERIAL PRIMARY KEY,
  session_hash TEXT NOT NULL UNIQUE,
  init_data_hash TEXT NOT NULL,
  telegram_user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  install_hash TEXT,
  fingerprint_hash TEXT,
  ip_hash TEXT,
  network_hash TEXT,
  network_label TEXT,
  provider_status TEXT NOT NULL DEFAULT 'unavailable',
  vpn BOOLEAN,
  proxy BOOLEAN,
  tor BOOLEAN,
  hosting BOOLEAN,
  risk_score INTEGER NOT NULL DEFAULT 0 CHECK (risk_score BETWEEN 0 AND 100),
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','medium','high')),
  risk_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','passed','medium','suspicious','expired','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS security_attempts_user_created_idx
  ON security_verification_attempts(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS security_attempts_install_idx
  ON security_verification_attempts(install_hash, telegram_user_id);
CREATE INDEX IF NOT EXISTS security_attempts_fingerprint_idx
  ON security_verification_attempts(fingerprint_hash, telegram_user_id);
CREATE INDEX IF NOT EXISTS security_attempts_ip_idx
  ON security_verification_attempts(ip_hash, telegram_user_id);
CREATE INDEX IF NOT EXISTS security_attempts_network_idx
  ON security_verification_attempts(network_hash, telegram_user_id);
CREATE TABLE IF NOT EXISTS security_rate_limits (
  key TEXT PRIMARY KEY,
  window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  request_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS security_events (
  id BIGSERIAL PRIMARY KEY,
  telegram_user_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS security_events_created_idx
  ON security_events(created_at DESC);
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
        VALUES ('users','telegram_id'), ('referrals','referrer_id'), ('referrals','inviter_user_id'),
               ('referrals','referred_id'), ('referrals','referred_user_id'), ('referrals','invited_user_id'),
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
          VALUES ('users','telegram_id'), ('referrals','referrer_id'), ('referrals','inviter_user_id'),
                 ('referrals','referred_id'), ('referrals','referred_user_id'), ('referrals','invited_user_id'),
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

LEGACY_USERS_MIGRATION = """
DO $body$
DECLARE
  id_column TEXT;
  username_column TEXT;
  first_name_column TEXT;
  points_column TEXT;
  referral_count_column TEXT;
  force_subscribed_column TEXT;
  disclaimer_column TEXT;
  verified_column TEXT;
  banned_column TEXT;
  joined_at_column TEXT;
  username_expression TEXT;
  first_name_expression TEXT;
  points_expression TEXT;
  referral_count_expression TEXT;
  force_subscribed_expression TEXT;
  disclaimer_expression TEXT;
  verified_expression TEXT;
  banned_expression TEXT;
  joined_at_expression TEXT;
BEGIN
  IF to_regclass('public.bot_users') IS NULL THEN
    RETURN;
  END IF;

  SELECT column_name INTO id_column
  FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users'
    AND column_name IN ('telegram_id','user_id','id')
  ORDER BY CASE column_name WHEN 'telegram_id' THEN 1 WHEN 'user_id' THEN 2 ELSE 3 END
  LIMIT 1;
  IF id_column IS NULL THEN
    RETURN;
  END IF;

  SELECT column_name INTO username_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('username','user_name')
  ORDER BY CASE column_name WHEN 'username' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO first_name_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('first_name','name')
  ORDER BY CASE column_name WHEN 'first_name' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO points_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('points','coins','balance')
  ORDER BY CASE column_name WHEN 'points' THEN 1 WHEN 'coins' THEN 2 ELSE 3 END LIMIT 1;
  SELECT column_name INTO referral_count_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('referral_count','referrals_count','invite_count')
  ORDER BY CASE column_name WHEN 'referral_count' THEN 1 WHEN 'referrals_count' THEN 2 ELSE 3 END LIMIT 1;
  SELECT column_name INTO force_subscribed_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('force_subscribed','subscribed')
  ORDER BY CASE column_name WHEN 'force_subscribed' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO disclaimer_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('disclaimer_accepted','accepted_disclaimer')
  ORDER BY CASE column_name WHEN 'disclaimer_accepted' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO verified_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('is_verified','verified')
  ORDER BY CASE column_name WHEN 'is_verified' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO banned_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('banned','is_banned')
  ORDER BY CASE column_name WHEN 'banned' THEN 1 ELSE 2 END LIMIT 1;
  SELECT column_name INTO joined_at_column FROM information_schema.columns
  WHERE table_schema='public' AND table_name='bot_users' AND column_name IN ('joined_at','created_at')
  ORDER BY CASE column_name WHEN 'joined_at' THEN 1 ELSE 2 END LIMIT 1;

  username_expression := CASE WHEN username_column IS NULL THEN quote_literal('') ELSE format('COALESCE(bu.%I::text, %L)', username_column, '') END;
  first_name_expression := CASE WHEN first_name_column IS NULL THEN quote_literal('') ELSE format('COALESCE(bu.%I::text, %L)', first_name_column, '') END;
  points_expression := CASE WHEN points_column IS NULL THEN '0' ELSE format('GREATEST(COALESCE(bu.%I::bigint, 0), 0)::integer', points_column) END;
  referral_count_expression := CASE WHEN referral_count_column IS NULL THEN '0' ELSE format('GREATEST(COALESCE(bu.%I::bigint, 0), 0)::integer', referral_count_column) END;
  force_subscribed_expression := CASE WHEN force_subscribed_column IS NULL THEN 'FALSE' ELSE format('COALESCE(bu.%I::boolean, FALSE)', force_subscribed_column) END;
  disclaimer_expression := CASE WHEN disclaimer_column IS NULL THEN 'FALSE' ELSE format('COALESCE(bu.%I::boolean, FALSE)', disclaimer_column) END;
  verified_expression := CASE WHEN verified_column IS NULL THEN 'FALSE' ELSE format('COALESCE(bu.%I::boolean, FALSE)', verified_column) END;
  banned_expression := CASE WHEN banned_column IS NULL THEN 'FALSE' ELSE format('COALESCE(bu.%I::boolean, FALSE)', banned_column) END;
  joined_at_expression := CASE WHEN joined_at_column IS NULL THEN 'NOW()' ELSE format('COALESCE(bu.%I::timestamptz, NOW())', joined_at_column) END;

  EXECUTE format(
    'INSERT INTO users (telegram_id, username, first_name, joined_at, points, referral_count, force_subscribed, disclaimer_accepted, is_verified, banned)
     SELECT bu.%I::bigint, %s, %s, %s, %s, %s, %s, %s, %s, %s
     FROM bot_users bu
     WHERE bu.%I IS NOT NULL
     ON CONFLICT (telegram_id) DO UPDATE SET
       username = CASE WHEN users.username = %L THEN EXCLUDED.username ELSE users.username END,
       first_name = CASE WHEN users.first_name = %L THEN EXCLUDED.first_name ELSE users.first_name END,
       joined_at = LEAST(users.joined_at, EXCLUDED.joined_at),
       points = GREATEST(users.points, EXCLUDED.points),
       referral_count = GREATEST(users.referral_count, EXCLUDED.referral_count),
       force_subscribed = users.force_subscribed OR EXCLUDED.force_subscribed,
       disclaimer_accepted = users.disclaimer_accepted OR EXCLUDED.disclaimer_accepted,
       is_verified = users.is_verified OR EXCLUDED.is_verified,
       banned = users.banned OR EXCLUDED.banned',
    id_column, username_expression, first_name_expression, joined_at_expression, points_expression, referral_count_expression, force_subscribed_expression, disclaimer_expression, verified_expression, banned_expression, id_column, '', ''
  );
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
    "verification_complete": (
        "╭━━━━━━━━━━━━━━━━━━╮\n"
        "   ✅ VERIFICATION\n"
        "       COMPLETE\n"
        "╰━━━━━━━━━━━━━━━━━━╯\n\n"
        "Your device has been successfully verified.\n\n"
        "🔓 Access Granted\n"
        "🛡️ Security Check Passed\n\n"
        "You can now continue using the bot."
    ),
    "verification_rejected": (
        "╭━━━━━━━━━━━━━━━━━━╮\n"
        "   🚫 VERIFICATION\n"
        "        REJECTED\n"
        "╰━━━━━━━━━━━━━━━━━━╯\n\n"
        "Multiple accounts/devices linked to this verification were detected.\n\n"
        "⚠️ Referral abuse is strictly prohibited.\n"
        "❌ This referral has been invalidated.\n"
        "🔒 Further attempts may be blocked.\n\n"
        "Don't try to bypass the system."
    ),
}


log = logging.getLogger(__name__)


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None
        self.referral_owner_column = "referrer_id"
        self.referral_has_legacy_owner = False
        self.referral_user_column = "current_referred_id"
        self.referral_user_expression = "current_referred_id"
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
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS device_verified BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS device_verified_at TIMESTAMPTZ")
            await conn.execute(LEGACY_USERS_MIGRATION)
            # Some legacy Railway databases kept referred_id/status but omitted
            # the owner column. Add it without deleting or rewriting old rows.
            await conn.execute("ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
            await conn.execute("ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referred_id BIGINT")
            await conn.execute("ALTER TABLE referrals ADD COLUMN IF NOT EXISTS current_referred_id BIGINT")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS referrals_current_referred_id_unique ON referrals(current_referred_id) WHERE current_referred_id IS NOT NULL")
            # Legacy owner and user columns can point at bot_users and be NOT NULL.
            # Keep them for historical reads, but do not force new referrals through them.
            await conn.execute("""
                DO $migration$
                DECLARE
                  legacy_column TEXT;
                BEGIN
                  FOREACH legacy_column IN ARRAY ARRAY['inviter_user_id','invited_user_id','referred_user_id','referred_id'] LOOP
                    IF EXISTS (
                      SELECT 1 FROM information_schema.columns c
                      WHERE c.table_schema='public' AND c.table_name='referrals'
                        AND c.column_name=legacy_column
                    ) THEN
                      EXECUTE format('ALTER TABLE referrals ALTER COLUMN %I DROP NOT NULL', legacy_column);
                    END IF;
                  END LOOP;
                END
                $migration$;
            """)
            # The old inviter column can point at the old bot_users table and be NOT NULL.
            # Keep it for historical reads, but do not force new referrals through it.
            await conn.execute("""
                DO $migration$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='referrals'
                      AND column_name='inviter_user_id'
                  ) THEN
                    ALTER TABLE referrals ALTER COLUMN inviter_user_id DROP NOT NULL;
                  END IF;
                END
                $migration$;
            """)
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
            await conn.execute(
                "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS security_status TEXT NOT NULL DEFAULT 'clear'"
            )
            referral_columns = await conn.fetchrow(
                """
                SELECT
                  CASE
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='referrer_id' AND NOT attisdropped
                    ) THEN 'referrer_id'
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='inviter_user_id' AND NOT attisdropped
                    ) THEN 'inviter_user_id'
                    ELSE NULL
                  END AS owner_column,
                  EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid=to_regclass('referrals')
                      AND attname='inviter_user_id' AND NOT attisdropped
                  ) AS has_legacy_owner,
                  CASE
                    WHEN EXISTS (
                      SELECT 1 FROM pg_attribute
                      WHERE attrelid=to_regclass('referrals')
                        AND attname='invited_user_id' AND NOT attisdropped
                    ) THEN 'invited_user_id'
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
                  EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid=to_regclass('referrals')
                      AND attname='invited_user_id' AND NOT attisdropped
                  ) AS has_invited_user_id,
                  EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid=to_regclass('referrals')
                      AND attname='referred_user_id' AND NOT attisdropped
                  ) AS has_referred_user_id,
                  EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid=to_regclass('referrals')
                      AND attname='referred_id' AND NOT attisdropped
                  ) AS has_referred_id,
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
            if referral_columns["owner_column"] not in {"referrer_id", "inviter_user_id"}:
                raise RuntimeError("The referrals table has no referrer_id/inviter_user_id column")
            if referral_columns["user_column"] not in {"referred_id", "referred_user_id", "invited_user_id"}:
                raise RuntimeError("The referrals table has no referred_id/referred_user_id/invited_user_id column")
            if referral_columns["state_column"] not in {"state", "status"}:
                raise RuntimeError("The referrals table has no state/status column")
            self.referral_owner_column = referral_columns["owner_column"]
            self.referral_has_legacy_owner = bool(referral_columns["has_legacy_owner"])
            self.referral_user_column = "current_referred_id"
            user_columns = ["current_referred_id"]
            if referral_columns["has_invited_user_id"]:
                user_columns.append("invited_user_id")
            if referral_columns["has_referred_user_id"]:
                user_columns.append("referred_user_id")
            if referral_columns["has_referred_id"]:
                user_columns.append("referred_id")
            self.referral_user_expression = "COALESCE(" + ", ".join(user_columns) + ")"
            self.referral_state_column = referral_columns["state_column"]
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER NOT NULL DEFAULT 0")
            owner_expression = self._referral_owner_expression()
            state_column = self._referral_state_column()
            await conn.execute(
                f"""
                UPDATE users AS u
                SET referral_count = (
                    SELECT COUNT(*)::int
                    FROM referrals AS r
                    WHERE {owner_expression} = u.telegram_id
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

    def _referral_owner_column(self) -> str:
        if self.referral_owner_column not in {"referrer_id", "inviter_user_id"}:
            raise RuntimeError("Unsupported referrals owner column")
        return self.referral_owner_column

    def _referral_owner_expression(self) -> str:
        owner_column = self._referral_owner_column()
        if owner_column == "referrer_id" and self.referral_has_legacy_owner:
            return "COALESCE(referrer_id, inviter_user_id)"
        return owner_column

    def _referral_user_expression(self) -> str:
        if not self.referral_user_expression:
            raise RuntimeError("Unsupported referrals user expression")
        return self.referral_user_expression

    def _referral_user_column(self) -> str:
        if self.referral_user_column != "current_referred_id":
            raise RuntimeError("Unsupported referrals write column")
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
        owner_column = self._referral_owner_column()
        user_expression = self._referral_user_expression()
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
                    if referrer_id and referrer_id != telegram_id:
                        referrer_exists = await conn.fetchval(
                            "SELECT 1 FROM users WHERE telegram_id=$1", referrer_id
                        )
                        if referrer_exists:
                            user_column = self._referral_user_column()
                            state_column = self._referral_state_column()
                            prior_referral = await conn.fetchval(
                                f"SELECT 1 FROM referrals WHERE {user_expression}=$1",
                                telegram_id,
                            )
                            if not prior_referral:
                                referral_state = "completed" if existing["is_verified"] else "pending"
                                referral = await conn.fetchrow(
                                    f"INSERT INTO referrals ({owner_column}, {user_column}, {state_column}) "
                                    f"VALUES ($1,$2,$3) ON CONFLICT DO NOTHING "
                                    f"RETURNING {owner_column}",
                                    referrer_id,
                                    telegram_id,
                                    referral_state,
                                )
                                if referral:
                                    created_referrer_id = referral[owner_column]
                                    if referral_state == "completed":
                                        await conn.execute(
                                            "UPDATE users SET referral_count=referral_count+1, points=points+1 "
                                            "WHERE telegram_id=$1",
                                            created_referrer_id,
                                        )
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
                            f"INSERT INTO referrals ({owner_column}, {user_column}, {state_column}) "
                            f"VALUES ($1,$2,'pending') ON CONFLICT DO NOTHING "
                            f"RETURNING {owner_column}",
                            referrer_id,
                            telegram_id,
                        )
                        if referral:
                            created_referrer_id = referral[owner_column]
                return (
                    dict(await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)),
                    created_referrer_id,
                )
    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = await self._p().fetchrow("SELECT * FROM users WHERE telegram_id=$1", user_id)
        return dict(row) if row else None

    async def referral_stats(self, referrer_id: int) -> dict[str, int]:
        owner_expression = self._referral_owner_expression()
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
                    WHERE {owner_expression}=$1
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
        raw_permissions = row["permissions"] or {}
        if isinstance(raw_permissions, str):
            try:
                permissions = json.loads(raw_permissions)
            except (TypeError, ValueError):
                permissions = {}
        elif isinstance(raw_permissions, dict):
            permissions = raw_permissions
        else:
            permissions = {}
        return bool(permissions.get(permission)) if isinstance(permissions, dict) else False

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

    async def invalidate_verification(self, user_id: int) -> None:
        await self._p().execute(
            "UPDATE users SET force_subscribed=FALSE, is_verified=FALSE WHERE telegram_id=$1",
            user_id,
        )


    async def consume_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Atomically consume one request from a database-backed rolling window."""
        if limit <= 0:
            return False
        now = datetime.now().astimezone()
        async with self._p().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT window_started_at, request_count FROM security_rate_limits WHERE key=$1 FOR UPDATE",
                    key,
                )
                if not row:
                    await conn.execute(
                        "INSERT INTO security_rate_limits (key, window_started_at, request_count) VALUES ($1,NOW(),1)",
                        key,
                    )
                    return True
                started = row["window_started_at"]
                if started.tzinfo is None:
                    started = started.replace(tzinfo=now.tzinfo)
                if (now - started).total_seconds() >= window_seconds:
                    await conn.execute(
                        "UPDATE security_rate_limits SET window_started_at=NOW(), request_count=1 WHERE key=$1",
                        key,
                    )
                    return True
                if int(row["request_count"]) >= limit:
                    return False
                await conn.execute(
                    "UPDATE security_rate_limits SET request_count=request_count+1 WHERE key=$1",
                    key,
                )
                return True

    async def verification_risk_context(
        self,
        user_id: int,
        install_hash: str | None,
        fingerprint_hash: str | None,
        ip_hash: str | None,
        network_hash: str | None,
    ) -> dict[str, Any]:
        """Return correlation counts; raw IP and fingerprint values never enter this query."""
        row = await self._p().fetchrow(
            """
            SELECT
              (SELECT COUNT(DISTINCT telegram_user_id)::int FROM security_verification_attempts
               WHERE install_hash=$1 AND telegram_user_id<>$5) AS same_device_accounts,
              (SELECT COUNT(DISTINCT telegram_user_id)::int FROM security_verification_attempts
               WHERE fingerprint_hash=$2 AND telegram_user_id<>$5) AS same_fingerprint_accounts,
              (SELECT COUNT(DISTINCT telegram_user_id)::int FROM security_verification_attempts
               WHERE ip_hash=$3 AND telegram_user_id<>$5) AS same_ip_accounts,
              (SELECT COUNT(DISTINCT telegram_user_id)::int FROM security_verification_attempts
               WHERE network_hash=$4 AND telegram_user_id<>$5) AS same_network_accounts,
              (SELECT COUNT(*)::int FROM security_verification_attempts
               WHERE telegram_user_id=$5 AND created_at >= NOW()-INTERVAL '1 hour') AS recent_user_attempts
            """,
            install_hash,
            fingerprint_hash,
            ip_hash,
            network_hash,
            user_id,
        )
        owner_expression = self._referral_owner_expression()
        user_expression = self._referral_user_expression()
        referrer_id = await self._p().fetchval(
            f"SELECT {owner_expression} FROM referrals WHERE {user_expression}=$1 LIMIT 1",
            user_id,
        )
        referral_cycle = False
        if referrer_id:
            referral_cycle = bool(await self._p().fetchval(
                f"""
                WITH RECURSIVE referral_chain(node, depth) AS (
                  SELECT $1::bigint, 0
                  UNION ALL
                  SELECT {user_expression}, referral_chain.depth + 1
                  FROM referrals JOIN referral_chain
                    ON {owner_expression}=referral_chain.node
                  WHERE referral_chain.depth < 20
                )
                SELECT EXISTS (SELECT 1 FROM referral_chain WHERE node=$2::bigint)
                """,
                user_id,
                referrer_id,
            ))
        context = dict(row)
        context["referrer_id"] = int(referrer_id) if referrer_id else None
        context["referral_cycle"] = referral_cycle
        return context

    async def create_verification_attempt(
        self,
        session_hash: str,
        init_data_hash: str,
        user_id: int,
        install_hash: str | None,
        fingerprint_hash: str | None,
        ip_hash: str | None,
        network_hash: str | None,
        network_label: str | None,
        provider_status: str,
        provider_flags: dict[str, bool],
        risk_score: int,
        risk_level: str,
        risk_reasons: list[str],
        expires_seconds: int,
    ) -> None:
        await self._p().execute(
            """
            INSERT INTO security_verification_attempts
              (session_hash,init_data_hash,telegram_user_id,install_hash,fingerprint_hash,ip_hash,
               network_hash,network_label,provider_status,vpn,proxy,tor,hosting,risk_score,risk_level,
               risk_reasons,expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,
                    NOW()+($17 * INTERVAL '1 second'))
            """,
            session_hash,
            init_data_hash,
            user_id,
            install_hash,
            fingerprint_hash,
            ip_hash,
            network_hash,
            (str(network_label)[:100] if network_label else None),
            provider_status[:40],
            bool(provider_flags.get("vpn")),
            bool(provider_flags.get("proxy")),
            bool(provider_flags.get("tor")),
            bool(provider_flags.get("hosting")),
            max(0, min(100, int(risk_score))),
            risk_level if risk_level in {"low", "medium", "high"} else "high",
            json.dumps(risk_reasons[:12]),
            max(60, int(expires_seconds)),
        )

    async def finish_verification(
        self,
        session_hash: str,
        user_id: int,
        init_data_hash: str,
        install_hash: str,
        fingerprint_hash: str,
    ) -> dict[str, Any]:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                attempt = await conn.fetchrow(
                    "SELECT * FROM security_verification_attempts WHERE session_hash=$1 "
                     "AND telegram_user_id=$2 AND init_data_hash=$3 "
                     "AND install_hash=$4 AND fingerprint_hash=$5 FOR UPDATE",
                    session_hash,
                    user_id,
                    init_data_hash,
                    install_hash,
                    fingerprint_hash,
                )
                if not attempt:
                    return {"status": "invalid"}
                if attempt["status"] != "pending":
                    return {"status": attempt["status"]}
                if attempt["expires_at"] <= datetime.now().astimezone():
                    await conn.execute(
                        "UPDATE security_verification_attempts SET status='expired', completed_at=NOW() WHERE session_hash=$1",
                        session_hash,
                    )
                    return {"status": "expired"}
                level = attempt["risk_level"]
                final_status = "passed" if level == "low" else "medium" if level == "medium" else "suspicious"
                await conn.execute(
                    "UPDATE security_verification_attempts SET status=$2, completed_at=NOW() WHERE session_hash=$1",
                    session_hash,
                    final_status,
                )
                if final_status == "passed":
                    await conn.execute(
                        "UPDATE users SET device_verified=TRUE, device_verified_at=NOW() WHERE telegram_id=$1",
                        user_id,
                    )
                user_expression = self._referral_user_expression()
                if final_status == "suspicious":
                    await conn.execute(
                        f"UPDATE referrals SET security_status='suspicious' WHERE {user_expression}=$1",
                        user_id,
                    )
                elif final_status == "medium":
                    await conn.execute(
                        f"UPDATE referrals SET security_status='review' WHERE {user_expression}=$1 AND security_status<>'suspicious'",
                        user_id,
                    )
                else:
                    await conn.execute(
                        f"UPDATE referrals SET security_status='clear' WHERE {user_expression}=$1 AND security_status='review'",
                        user_id,
                    )
                await conn.execute(
                    "INSERT INTO security_events (telegram_user_id,event_type,details) VALUES ($1,$2,$3::jsonb)",
                    user_id,
                    "device_verification_" + final_status,
                    json.dumps({"attempt_id": attempt["id"], "risk_score": attempt["risk_score"]}),
                )
                return {"status": final_status}

    async def device_verification_passed(self, user_id: int) -> bool:
        return bool(await self._p().fetchval(
            "SELECT device_verified FROM users WHERE telegram_id=$1", user_id
        ))

    async def device_verification_status(self, user_id: int) -> str:
        if await self.device_verification_passed(user_id):
            return "passed"
        status = await self._p().fetchval(
            "SELECT status FROM security_verification_attempts WHERE telegram_user_id=$1 "
            "ORDER BY created_at DESC LIMIT 1",
            user_id,
        )
        return str(status or "not_started")

    async def suspicious_verifications(self, limit: int = 20) -> list[dict[str, Any]]:
        owner_expression = self._referral_owner_expression()
        user_expression = self._referral_user_expression()
        for column in ("referrer_id", "inviter_user_id"):
            owner_expression = owner_expression.replace(column, "r." + column)
        for column in ("current_referred_id", "invited_user_id", "referred_user_id", "referred_id"):
            user_expression = user_expression.replace(column, "r." + column)
        rows = await self._p().fetch(
            f"""
            SELECT va.id, va.telegram_user_id, va.risk_level, va.risk_score, va.risk_reasons,
                   va.status, va.provider_status, va.vpn, va.proxy, va.tor, va.hosting,
                   va.network_label, va.created_at, r.security_status,
                   {owner_expression} AS referrer_id,
                   (SELECT COUNT(DISTINCT x.telegram_user_id)::int FROM security_verification_attempts x
                    WHERE x.install_hash=va.install_hash AND x.telegram_user_id<>va.telegram_user_id) AS linked_device_count,
                   (SELECT COUNT(DISTINCT x.telegram_user_id)::int FROM security_verification_attempts x
                    WHERE x.fingerprint_hash=va.fingerprint_hash AND x.telegram_user_id<>va.telegram_user_id) AS linked_account_count,
                   (SELECT COUNT(DISTINCT x.telegram_user_id)::int FROM security_verification_attempts x
                    WHERE x.ip_hash=va.ip_hash AND x.telegram_user_id<>va.telegram_user_id) AS linked_ip_count,
                   (SELECT COUNT(DISTINCT x.telegram_user_id)::int FROM security_verification_attempts x
                    WHERE x.network_hash=va.network_hash AND x.telegram_user_id<>va.telegram_user_id) AS linked_network_count
            FROM security_verification_attempts va
            LEFT JOIN referrals r ON {user_expression}=va.telegram_user_id
            WHERE va.risk_level IN ('medium','high')
            ORDER BY va.created_at DESC
            LIMIT $1
            """,
            max(1, min(100, limit)),
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
            user_expression = self._referral_user_expression()
            state_column = self._referral_state_column()
            await conn.execute(
                f"UPDATE referrals SET {state_column}='subscribed' "
                f"WHERE {user_expression}=$1 AND {state_column}='pending'",
                user_id,
            )

    async def accept_disclaimer(self, user_id: int) -> None:
        async with self._p().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE users SET disclaimer_accepted=TRUE WHERE telegram_id=$1", user_id
                )
                user_expression = self._referral_user_expression()
                state_column = self._referral_state_column()
                await conn.execute(
                    f"UPDATE referrals SET {state_column}='disclaimer_accepted' "
                    f"WHERE {user_expression}=$1 AND {state_column} IN ('pending','subscribed')",
                    user_id,
                )

    async def complete_gate(self, user_id: int) -> int | None:
        owner_expression = self._referral_owner_expression()
        user_expression = self._referral_user_expression()
        state_column = self._referral_state_column()
        async with self._p().acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    "SELECT device_verified FROM users WHERE telegram_id=$1 FOR UPDATE", user_id
                )
                if not user or not user["device_verified"]:
                    return None
                # Keep verification and referral accounting in one transaction.
                # If either update fails, neither state is committed.
                row = await conn.fetchrow(
                    f"UPDATE referrals SET {state_column}='completed', completed_at=NOW() "
                    f"WHERE {user_expression}=$1 AND {state_column} IN "
                    "('pending','subscribed','disclaimer_accepted') "
                    "AND COALESCE(security_status,'clear') <> 'suspicious' "
                    f"RETURNING {owner_expression} AS referrer_id",
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

    async def user_delivery_history(self, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        rows = await self._p().fetch(
            """
            SELECT category, claim_id, user_id, name, kind, code, status,
                   claimed_at, delivered_at, points_spent, error
            FROM (
              SELECT 'Milestone'::text AS category, ra.reward_id::bigint AS claim_id,
                     ra.user_id, r.name, r.kind,
                     CASE
                       WHEN r.text_content IS NOT NULL AND r.text_content <> '' THEN r.text_content
                       WHEN r.file_id IS NOT NULL THEN '[' || COALESCE(r.kind, 'file') || ' attachment]'
                       ELSE '—'
                     END AS code,
                     ra.status, ra.assigned_at AS claimed_at, ra.delivered_at,
                     0::int AS points_spent, ra.error
              FROM reward_assignments ra
              JOIN rewards r ON r.id=ra.reward_id
              WHERE ra.user_id=$1
              UNION ALL
              SELECT 'Stock'::text AS category, sc.id::bigint AS claim_id,
                     sc.user_id, sp.name, COALESCE(si.kind, 'text') AS kind,
                     CASE
                       WHEN si.text_content IS NOT NULL AND si.text_content <> '' THEN si.text_content
                       WHEN si.file_id IS NOT NULL THEN '[' || COALESCE(si.kind, 'file') || ' attachment]'
                       ELSE '—'
                     END AS code,
                     sc.status, sc.claimed_at, sc.delivered_at,
                     sc.points_spent, sc.error
              FROM stock_claims sc
              JOIN stock_products sp ON sp.id=sc.product_id
              LEFT JOIN stock_items si ON si.id=sc.item_id
              WHERE sc.user_id=$1
            ) deliveries
            ORDER BY claimed_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
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

    async def update_stock_points(
        self, product_id: int, value: int, relative: bool = False
    ) -> dict[str, Any] | None:
        expression = "GREATEST(0, points_required + $1)" if relative else "$1"
        row = await self._p().fetchrow(
            f"UPDATE stock_products SET points_required={expression} "
            "WHERE id=$2 RETURNING id,name,points_required",
            value,
            product_id,
        )
        return dict(row) if row else None

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
        async with self._p().acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE stock_claims SET status=$1, delivered_at=CASE WHEN $2 THEN NOW() END, "
                    "error=$3, attempt_count=attempt_count+1 "
                    "WHERE id=$4 AND user_id=$5",
                    status,
                    delivered,
                    error[:1000],
                    claim_id,
                    user_id,
                )
                # stock_items has no delivered status; a delivered code remains claimed.
                if not delivered:
                    await conn.execute(
                        "UPDATE stock_items SET status='failed' WHERE id=("
                        "SELECT item_id FROM stock_claims WHERE id=$1 AND user_id=$2) "
                        "AND status='claimed'",
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

    async def adjust_user(self, user_id: int, field: str, delta: int) -> int | None:
        if field not in {"referral_count", "points"}:
            raise ValueError("Invalid adjustment field")
        return await self._p().fetchval(
            f"UPDATE users SET {field}=GREATEST(0,{field}+$1) WHERE telegram_id=$2 RETURNING {field}",
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
                owner_expression = self._referral_owner_expression()
                user_expression = self._referral_user_expression()
                state_column = self._referral_state_column()
                await conn.execute(
                    f"UPDATE referrals SET {state_column}='invalid' "
                    f"WHERE {owner_expression}=$1 OR {user_expression}=$1",
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
