"""
Database integration tests using testcontainers.
Automatically skipped when Docker is not running.
"""
import pytest


def is_docker_running() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


try:
    from testcontainers.postgres import PostgresContainer
    import psycopg2
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False


# ── Note: check runs fresh each pytest session ────────────
pytestmark = pytest.mark.skipif(
    not TESTCONTAINERS_AVAILABLE,
    reason="testcontainers not installed"
)


@pytest.fixture(scope="module")
def postgres():
    """Start PostgreSQL container — skip if Docker not running."""
    if not is_docker_running():
        pytest.skip("Docker not running — start Docker Desktop")
    with PostgresContainer("postgres:15") as pg:
        yield pg


@pytest.fixture(scope="module")
def db(postgres):

    conn = psycopg2.connect(
    host     = postgres.get_container_host_ip(),
    port     = postgres.get_exposed_port(5432),
    dbname   = "test",
    user     = "test",
    password = "test"
)
    cur  = conn.cursor()

    cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            clerk_user_id TEXT UNIQUE NOT NULL,
            display_name  TEXT,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS briefs (
            id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
            topics     TEXT[],
            status     TEXT DEFAULT 'pending'
                       CHECK (status IN ('pending','running','complete','failed')),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS briefings (
            id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            brief_id     UUID REFERENCES briefs(id) ON DELETE CASCADE,
            content      TEXT,
            critic_score FLOAT,
            approved     BOOLEAN DEFAULT FALSE,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
            brief_id     UUID REFERENCES briefs(id) ON DELETE CASCADE,
            job_type     TEXT NOT NULL,
            status       TEXT DEFAULT 'pending',
            result       JSONB,
            error        TEXT,
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at   TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
    """)

    conn.commit()
    yield conn, cur
    conn.close()


class TestDatabaseSchema:
    """Test Aria schema against a real PostgreSQL instance."""

    def test_can_create_user(self, db):
        conn, cur = db
        cur.execute(
            "INSERT INTO users (clerk_user_id, display_name) VALUES (%s, %s) RETURNING id",
            ("test-clerk-id", "Test User")
        )
        conn.commit()
        user_id = cur.fetchone()[0]
        assert user_id is not None

    def test_can_create_brief_with_topics(self, db):
        conn, cur = db
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefs (user_id, topics, status) VALUES (%s, %s, %s) RETURNING id",
            (user_id, ["NVIDIA chips 2025", "Tesla outlook"], "pending")
        )
        conn.commit()
        assert cur.fetchone()[0] is not None

    def test_topics_stored_as_array(self, db):
        conn, cur = db
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = cur.fetchone()[0]

        topics = ["NVIDIA 2025", "Apple Vision Pro", "Tesla shares"]
        cur.execute(
            "INSERT INTO briefs (user_id, topics) VALUES (%s, %s) RETURNING topics",
            (user_id, topics)
        )
        conn.commit()
        assert cur.fetchone()[0] == topics

    def test_brief_status_transitions(self, db):
        conn, cur = db
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefs (user_id, topics, status) VALUES (%s, %s, %s) RETURNING id",
            (user_id, ["Test topic"], "pending")
        )
        conn.commit()
        brief_id = cur.fetchone()[0]

        for status in ["running", "complete"]:
            cur.execute("UPDATE briefs SET status = %s WHERE id = %s", (status, brief_id))
            conn.commit()

        cur.execute("SELECT status FROM briefs WHERE id = %s", (brief_id,))
        assert cur.fetchone()[0] == "complete"

    def test_invalid_status_rejected(self, db):
        conn, cur = db
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = cur.fetchone()[0]

        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO briefs (user_id, topics, status) VALUES (%s, %s, %s)",
                (user_id, ["Test"], "invalid_status")
            )
            conn.commit()
        conn.rollback()

    def test_briefing_saved_with_score(self, db):
        conn, cur = db
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefs (user_id, topics) VALUES (%s, %s) RETURNING id",
            (user_id, ["Test topic"])
        )
        conn.commit()
        brief_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefings (brief_id, content, critic_score, approved) VALUES (%s, %s, %s, %s)",
            (brief_id, "## Executive Summary\nContent...", 8.5, True)
        )
        conn.commit()

        cur.execute(
            "SELECT critic_score, approved FROM briefings WHERE brief_id = %s",
            (brief_id,)
        )
        row = cur.fetchone()
        assert row[0] == 8.5
        assert row[1] is True

    def test_cascade_delete(self, db):
        conn, cur = db
        cur.execute(
            "INSERT INTO users (clerk_user_id) VALUES (%s) RETURNING id",
            ("cascade-test-user",)
        )
        conn.commit()
        user_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefs (user_id, topics) VALUES (%s, %s) RETURNING id",
            (user_id, ["Test"])
        )
        conn.commit()
        brief_id = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO briefings (brief_id, content) VALUES (%s, %s)",
            (brief_id, "Content")
        )
        conn.commit()

        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM briefs WHERE id = %s", (brief_id,))
        assert cur.fetchone()[0] == 0