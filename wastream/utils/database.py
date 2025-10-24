import asyncio
import os
import time
import uuid
from typing import Optional

from databases import Database

from wastream.core.config import settings
from wastream.utils.helpers import create_cache_key
from wastream.utils.logger import database_logger

# ===========================
# Database Instance
# ===========================
database = Database(settings.get_database_url())

# ===========================
# Database Setup
# ===========================
async def setup_database():
    try:
        database_logger.info(f"Setup {settings.DATABASE_TYPE} database")
        if settings.DATABASE_TYPE == "sqlite":
            os.makedirs(os.path.dirname(settings.DATABASE_PATH), exist_ok=True)
            if not os.path.exists(settings.DATABASE_PATH):
                open(settings.DATABASE_PATH, "a").close()

        await database.connect()
        database_logger.info("Connected")

        await database.execute("CREATE TABLE IF NOT EXISTS db_version (id INTEGER PRIMARY KEY CHECK (id = 1), version TEXT)")
        current_version = await database.fetch_val("SELECT version FROM db_version WHERE id = 1")

        if current_version != settings.DATABASE_VERSION:
            if settings.DATABASE_TYPE == "sqlite":
                await database.execute("DROP TABLE IF EXISTS dead_links")
                await database.execute("DROP TABLE IF EXISTS scrape_lock")
                await database.execute("DROP TABLE IF EXISTS content_cache")
                await database.execute("INSERT OR REPLACE INTO db_version VALUES (1, :version)", {"version": settings.DATABASE_VERSION})
            else:
                await database.execute("DROP TABLE IF EXISTS dead_links CASCADE")
                await database.execute("DROP TABLE IF EXISTS scrape_lock CASCADE")
                await database.execute("DROP TABLE IF EXISTS content_cache CASCADE")
                await database.execute(
                    "INSERT INTO db_version VALUES (1, :version) ON CONFLICT (id) DO UPDATE SET version = :version",
                    {"version": settings.DATABASE_VERSION}
                )

        await database.execute("CREATE TABLE IF NOT EXISTS dead_links (url TEXT PRIMARY KEY, expires_at INTEGER)")
        await database.execute("CREATE TABLE IF NOT EXISTS scrape_lock (lock_key TEXT PRIMARY KEY, instance_id TEXT, expires_at INTEGER)")
        await database.execute("CREATE TABLE IF NOT EXISTS content_cache (cache_key TEXT PRIMARY KEY, content TEXT NOT NULL, expires_at INTEGER)")

        await database.execute("CREATE INDEX IF NOT EXISTS idx_dead_links_expires ON dead_links(expires_at)")
        await database.execute("CREATE INDEX IF NOT EXISTS idx_scrape_lock_expires ON scrape_lock(expires_at)")
        await database.execute("CREATE INDEX IF NOT EXISTS idx_content_cache_expires ON content_cache(expires_at)")

        if settings.DATABASE_TYPE == "sqlite":
            await database.execute("PRAGMA busy_timeout=30000")
            await database.execute("PRAGMA journal_mode=WAL")
            await database.execute("PRAGMA synchronous=NORMAL")
            await database.execute("PRAGMA temp_store=MEMORY")
            await database.execute("PRAGMA cache_size=-2000")

        database_logger.info("Setup completed")

    except Exception as e:
        database_logger.error(f"Setup failed: {type(e).__name__}")
        raise

# ===========================
# Cleanup Expired Data
# ===========================
async def cleanup_expired_data():
    while True:
        try:
            current_time = int(time.time())

            deleted_locks = await database.execute(
                "DELETE FROM scrape_lock WHERE expires_at < :current_time",
                {"current_time": current_time}
            )

            deleted_links = await database.execute(
                "DELETE FROM dead_links WHERE expires_at < :current_time",
                {"current_time": current_time}
            )

            deleted_cache = await database.execute(
                "DELETE FROM content_cache WHERE expires_at < :current_time",
                {"current_time": current_time}
            )

            if deleted_locks or deleted_links or deleted_cache:
                database_logger.debug(f"Cleanup: {deleted_locks} locks, {deleted_links} links, {deleted_cache} cache")

        except Exception as e:
            database_logger.error(f"Cleanup error: {type(e).__name__}")

        await asyncio.sleep(settings.CLEANUP_INTERVAL)

# ===========================
# Dead Link Checking
# ===========================
async def is_dead_link(url: str) -> bool:
    try:
        current_time = int(time.time())
        result = await database.fetch_one(
            "SELECT 1 FROM dead_links WHERE url = :url AND expires_at > :current_time",
            {"url": url, "current_time": current_time}
        )
        return result is not None
    except Exception as e:
        database_logger.error(f"Dead link check failed: {type(e).__name__}")
        return False

# ===========================
# Dead Link Marking
# ===========================
async def mark_dead_link(url: str, ttl: int):
    try:
        current_time = int(time.time())
        expires_at = current_time + ttl

        if settings.DATABASE_TYPE == "sqlite":
            query = "INSERT OR REPLACE INTO dead_links (url, expires_at) VALUES (:url, :expires_at)"
        else:
            query = """INSERT INTO dead_links (url, expires_at) VALUES (:url, :expires_at)
                       ON CONFLICT (url) DO UPDATE SET expires_at = :expires_at"""

        await database.execute(query, {"url": url, "expires_at": expires_at})
    except Exception as e:
        database_logger.error(f"Mark dead link failed: {type(e).__name__}")

# ===========================
# Lock Acquisition
# ===========================
async def acquire_lock(lock_key: str, instance_id: str, duration: int = settings.SCRAPE_LOCK_TTL) -> bool:
    try:
        current_time = int(time.time())
        expires_at = current_time + duration

        await database.execute(
            "DELETE FROM scrape_lock WHERE expires_at < :current_time",
            {"current_time": current_time}
        )

        if settings.DATABASE_TYPE == "sqlite":
            query = "INSERT OR IGNORE INTO scrape_lock (lock_key, instance_id, expires_at) VALUES (:lock_key, :instance_id, :expires_at)"
        else:
            query = """INSERT INTO scrape_lock (lock_key, instance_id, expires_at)
                       VALUES (:lock_key, :instance_id, :expires_at) ON CONFLICT (lock_key) DO NOTHING"""

        await database.execute(query, {
            "lock_key": lock_key,
            "instance_id": instance_id,
            "expires_at": expires_at
        })

        existing_lock = await database.fetch_one(
            "SELECT instance_id FROM scrape_lock WHERE lock_key = :lock_key",
            {"lock_key": lock_key}
        )

        return existing_lock and existing_lock["instance_id"] == instance_id

    except Exception as e:
        database_logger.error(f"Lock attempt failed: {type(e).__name__}")
        return False

# ===========================
# Lock Release
# ===========================
async def release_lock(lock_key: str, instance_id: str):
    try:
        await database.execute(
            "DELETE FROM scrape_lock WHERE lock_key = :lock_key AND instance_id = :instance_id",
            {"lock_key": lock_key, "instance_id": instance_id}
        )
    except Exception as e:
        database_logger.error(f"Failed to release lock: {type(e).__name__}")

# ===========================
# Search Lock Context Manager
# ===========================
class SearchLock:

    def __init__(self, content_type: str, title: str, year: Optional[str] = None,
                 timeout: Optional[int] = None, retry_interval: float = 1.0):
        lock_key = create_cache_key(content_type, title, year)
        self.lock_key = lock_key
        self.instance_id = f"{uuid.uuid4()}_{os.getpid()}"
        self.duration = settings.SCRAPE_LOCK_TTL
        self.timeout = timeout if timeout is not None else settings.SCRAPE_WAIT_TIMEOUT
        self.retry_interval = retry_interval
        self.acquired = False

    async def __aenter__(self):
        start_time = time.time()
        attempt = 0

        while time.time() - start_time < self.timeout:
            attempt += 1
            self.acquired = await acquire_lock(self.lock_key, self.instance_id, self.duration)

            if self.acquired:
                elapsed_ms = int((time.time() - start_time) * 1000)
                database_logger.debug(
                    f"Lock acquired: {self.lock_key[:30]}... "
                    f"({elapsed_ms}ms, attempt {attempt})"
                )
                return self

            database_logger.debug(f"Lock busy: {self.lock_key[:30]}... (retry in {self.retry_interval}s)")
            await asyncio.sleep(self.retry_interval)

        elapsed_ms = int((time.time() - start_time) * 1000)
        database_logger.warning(
            f"Lock timeout: {self.lock_key[:30]}... "
            f"({elapsed_ms}ms, {attempt} attempts)"
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            await release_lock(self.lock_key, self.instance_id)
            database_logger.debug(f"Lock released: {self.lock_key[:30]}...")

# ===========================
# Database Teardown
# ===========================
async def teardown_database():
    try:
        await database.disconnect()
        database_logger.info("Disconnected")
    except Exception as e:
        database_logger.error(f"Failed to disconnect: {type(e).__name__}")
