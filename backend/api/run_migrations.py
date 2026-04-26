#!/usr/bin/env python3
"""
Run Aria database migrations.
Creates all tables needed for the application.
"""
import os
import boto3
import json
from dotenv import load_dotenv

load_dotenv()

CLUSTER_ARN = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN  = os.getenv("AURORA_SECRET_ARN")
DATABASE    = os.getenv("DATABASE_NAME", "aria")
REGION      = os.getenv("DEFAULT_AWS_REGION", "us-east-1")

client = boto3.client("rds-data", region_name=REGION)


def execute(sql: str, description: str = ""):
    """Execute a SQL statement via Data API."""
    try:
        client.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = sql
        )
        if description:
            print(f"  ✅ {description}")
    except Exception as e:
        print(f"  ❌ {description}: {e}")
        raise


def run_migrations():
    print("Running Aria database migrations...")
    print(f"Database: {DATABASE}")
    print(f"Cluster:  {CLUSTER_ARN}")
    print("="*50)

    # ── Enable UUID extension ─────────────────────────────
    execute(
        "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"",
        "UUID extension"
    )

    # ── Users table ───────────────────────────────────────
    execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            clerk_user_id           TEXT UNIQUE NOT NULL,
            display_name            TEXT,
            email                   TEXT,
            created_at              TIMESTAMPTZ DEFAULT NOW(),
            updated_at              TIMESTAMPTZ DEFAULT NOW()
        )
    """, "users table")

    # ── Briefs table ──────────────────────────────────────
    execute("""
        CREATE TABLE IF NOT EXISTS briefs (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
            topics      TEXT[],
            status      TEXT DEFAULT 'pending'
                        CHECK (status IN ('pending','running','complete','failed')),
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """, "briefs table")

    # ── Briefings table ───────────────────────────────────
    execute("""
        CREATE TABLE IF NOT EXISTS briefings (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            brief_id        UUID REFERENCES briefs(id) ON DELETE CASCADE,
            content         TEXT,
            critic_score    FLOAT,
            approved        BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """, "briefings table")

    # ── Jobs table ────────────────────────────────────────
    execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
            brief_id        UUID REFERENCES briefs(id) ON DELETE CASCADE,
            job_type        TEXT NOT NULL,
            status          TEXT DEFAULT 'pending'
                            CHECK (status IN ('pending','running','complete','failed')),
            result          JSONB,
            error           TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            completed_at    TIMESTAMPTZ
        )
    """, "jobs table")

    # ── Indexes ───────────────────────────────────────────
    execute(
        "CREATE INDEX IF NOT EXISTS idx_briefs_user_id ON briefs(user_id)",
        "briefs user_id index"
    )
    execute(
        "CREATE INDEX IF NOT EXISTS idx_briefings_brief_id ON briefings(brief_id)",
        "briefings brief_id index"
    )
    execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)",
        "jobs user_id index"
    )
    execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "jobs status index"
    )

    print("="*50)
    print("✅ All migrations complete!")


if __name__ == "__main__":
    run_migrations()