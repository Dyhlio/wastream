import os
import time
import asyncio
from typing import Optional
from databases import Database
from wastream.core.config import (
    DATABASE_VERSION, DATABASE_PATH, DATABASE_TYPE, 
    get_database_url, CLEANUP_INTERVAL, SCRAPE_LOCK_TTL,
    SCRAPE_WAIT_TIMEOUT
)
from wastream.utils.helpers import create_cache_key
from wastream.utils.logger import logger

database = Database(get_database_url())

# Initialize and configure database
async def setup_database():
    try:
        logger.log("DATABASE", f"Setup {DATABASE_TYPE} database")
        if DATABASE_TYPE == "sqlite":
            os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
            if not os.path.exists(DATABASE_PATH):
                open(DATABASE_PATH, "a").close()

        await database.connect()
        logger.log("DATABASE", "Connected successfully")

        await database.execute("CREATE TABLE IF NOT EXISTS db_version (id INTEGER PRIMARY KEY CHECK (id = 1), version TEXT)")
        current_version = await database.fetch_val("SELECT version FROM db_version WHERE id = 1")

        if current_version != DATABASE_VERSION:
            if DATABASE_TYPE == "sqlite":
                await database.execute("DROP TABLE IF EXISTS dead_links")
                await database.execute("DROP TABLE IF EXISTS scrape_lock")
                await database.execute("DROP TABLE IF EXISTS content_cache")
                await database.execute("INSERT OR REPLACE INTO db_version VALUES (1, :version)", {"version": DATABASE_VERSION})
            else:
                await database.execute("DROP TABLE IF EXISTS dead_links CASCADE")
                await database.execute("DROP TABLE IF EXISTS scrape_lock CASCADE")
                await database.execute("DROP TABLE IF EXISTS content_cache CASCADE")
                await database.execute(
                    "INSERT INTO db_version VALUES (1, :version) ON CONFLICT (id) DO UPDATE SET version = :version",
                    {"version": DATABASE_VERSION}
                )

        await database.execute("CREATE TABLE IF NOT EXISTS dead_links (url TEXT PRIMARY KEY, expires_at INTEGER)")
        await database.execute("CREATE TABLE IF NOT EXISTS scrape_lock (lock_key TEXT PRIMARY KEY, instance_id TEXT, expires_at INTEGER)")
        await database.execute("CREATE TABLE IF NOT EXISTS content_cache (cache_key TEXT PRIMARY KEY, content TEXT NOT NULL, expires_at INTEGER)")
        
        await database.execute("CREATE INDEX IF NOT EXISTS idx_dead_links_expires ON dead_links(expires_at)")
        await database.execute("CREATE INDEX IF NOT EXISTS idx_scrape_lock_expires ON scrape_lock(expires_at)")
        await database.execute("CREATE INDEX IF NOT EXISTS idx_content_cache_expires ON content_cache(expires_at)")

        if DATABASE_TYPE == "sqlite":
            await database.execute("PRAGMA busy_timeout=30000")
            await database.execute("PRAGMA journal_mode=WAL")
            await database.execute("PRAGMA synchronous=NORMAL")
            await database.execute("PRAGMA temp_store=MEMORY")
            await database.execute("PRAGMA cache_size=-2000")

        logger.log("DATABASE", "Setup completed")

    except Exception as e:
        logger.log("DATABASE", f"ERROR: Database setup failed: {e}")

# Clean expired data periodically
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
                logger.log("CLEANUP", f"Removed: {deleted_locks} locks, {deleted_links} dead links, {deleted_cache} cache entries")
                
        except Exception as e:
            logger.log("DATABASE", f"ERROR: Cleanup error: {e}")
        
        await asyncio.sleep(CLEANUP_INTERVAL)

# Check if URL is marked as dead
async def is_dead_link(url: str) -> bool:
    current_time = time.time()
    result = await database.fetch_one(
        "SELECT 1 FROM dead_links WHERE url = :url AND expires_at > :current_time",
        {"url": url, "current_time": current_time}
    )
    return result is not None

# Mark URL as dead with TTL
async def mark_dead_link(url: str, ttl: int):
    current_time = time.time()
    expires_at = current_time + ttl
    
    if DATABASE_TYPE == "sqlite":
        query = "INSERT OR REPLACE INTO dead_links (url, expires_at) VALUES (:url, :expires_at)"
    else:
        query = """INSERT INTO dead_links (url, expires_at) VALUES (:url, :expires_at) 
                   ON CONFLICT (url) DO UPDATE SET expires_at = :expires_at"""
    
    await database.execute(query, {"url": url, "expires_at": expires_at})
    logger.log("DEAD_LINK", f"Marked as dead for {ttl}s: {url[:50]}...")

# Acquire exclusive lock for scraping
async def acquire_lock(lock_key: str, instance_id: str, duration: int = SCRAPE_LOCK_TTL) -> bool:
    start_time = time.time()
    attempt = 0
    
    while (time.time() - start_time) < SCRAPE_WAIT_TIMEOUT:
        attempt += 1
        try:
            current_time = int(time.time())
            expires_at = current_time + duration
            
            await database.execute(
                "DELETE FROM scrape_lock WHERE expires_at < :current_time",
                {"current_time": current_time}
            )
            
            if DATABASE_TYPE == "sqlite":
                query = "INSERT OR IGNORE INTO scrape_lock (lock_key, instance_id, expires_at) VALUES (:lock_key, :instance_id, :expires_at)"
            else:
                query = """INSERT INTO scrape_lock (lock_key, instance_id, expires_at) 
                           VALUES (:lock_key, :instance_id, :expires_at) ON CONFLICT (lock_key) DO NOTHING"""
            
            result = await database.execute(query, {
                "lock_key": lock_key,
                "instance_id": instance_id,
                "expires_at": expires_at
            })
            
            existing_lock = await database.fetch_one(
                "SELECT instance_id FROM scrape_lock WHERE lock_key = :lock_key",
                {"lock_key": lock_key}
            )
            
            if existing_lock and existing_lock["instance_id"] == instance_id:
                elapsed_time = round((time.time() - start_time) * 1000)
                logger.log("LOCK", f"Acquired lock for {lock_key} by {instance_id[:8]} after {elapsed_time}ms (attempt {attempt})")
                return True
            
            if (time.time() - start_time) >= SCRAPE_WAIT_TIMEOUT:
                break
                
            logger.log("LOCK", f"Lock busy for {lock_key}, retrying in 0.5s (attempt {attempt})")
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.log("DATABASE", f"ERROR: Lock attempt {attempt} failed for {lock_key}: {e}")
            if (time.time() - start_time) < SCRAPE_WAIT_TIMEOUT - 0.5:
                await asyncio.sleep(0.5)
    
    elapsed_time = round((time.time() - start_time) * 1000)
    logger.log("LOCK", f"Failed to acquire lock for {lock_key} after {elapsed_time}ms timeout ({attempt} attempts)")
    return False

# Release acquired lock
async def release_lock(lock_key: str, instance_id: str):
    try:
        await database.execute(
            "DELETE FROM scrape_lock WHERE lock_key = :lock_key AND instance_id = :instance_id",
            {"lock_key": lock_key, "instance_id": instance_id}
        )
    except Exception as e:
        logger.log("DATABASE", f"ERROR: Failed to release lock: {e}")

# Context manager for search locking
class SearchLock:
    
    def __init__(self, content_type: str, title: str, year: Optional[str] = None):
        lock_key = create_cache_key(content_type, title, year)
        self.lock_key = lock_key
        self.instance_id = f"wastream_{int(time.time())}"
        self.duration = SCRAPE_LOCK_TTL
        self.acquired = False
    
    async def __aenter__(self):
        start_time = time.time()
        timeout = SCRAPE_WAIT_TIMEOUT
        
        while time.time() - start_time < timeout:
            self.acquired = await acquire_lock(self.lock_key, self.instance_id, self.duration)
            if self.acquired:
                logger.log("LOCK", f"Acquired: {self.lock_key}")
                return self
            await asyncio.sleep(1)
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            await release_lock(self.lock_key, self.instance_id)
            logger.log("LOCK", f"Released: {self.lock_key}")

# Close database connection
async def teardown_database():
    try:
        await database.disconnect()
        logger.log("DATABASE", "Disconnected")
    except Exception as e:
        logger.log("DATABASE", f"ERROR: Failed to disconnect: {e}")