import json
import time
from typing import Optional, List, Dict, Any

from wastream.core.config import settings
from wastream.utils.helpers import create_cache_key
from wastream.utils.logger import cache_logger

# ===========================
# Cache Retrieval
# ===========================
async def get_cache(database, cache_type: str, title: str, year: Optional[str] = None) -> Optional[List[Dict]]:
    cache_key = create_cache_key(cache_type, title, year)

    try:
        current_time = time.time()
        result = await database.fetch_one(
            "SELECT content FROM content_cache WHERE cache_key = :cache_key AND expires_at > :current_time",
            {"cache_key": cache_key, "current_time": current_time}
        )

        if not result:
            cache_logger.debug(f"Miss: {cache_type} {title} ({year})")
            return None

        cached_data = json.loads(result["content"])
        cache_logger.debug(f"Hit: {cache_type} {title} ({year}) - {len(cached_data)} results")
        return cached_data
    except json.JSONDecodeError as e:
        cache_logger.error(f"Corrupted cache: {type(e).__name__}")
        return None
    except Exception as e:
        cache_logger.error(f"Cache read failed: {type(e).__name__}")
        return None

# ===========================
# Cache Storage
# ===========================
async def set_cache(database, cache_type: str, title: str, year: Optional[str] = None,
                   results: Optional[List] = None, ttl: int = 3600):
    cache_key = create_cache_key(cache_type, title, year)

    try:
        current_time = time.time()
        expires_at = current_time + ttl
        content = json.dumps(results or [])

        if settings.DATABASE_TYPE == "sqlite":
            query = """INSERT OR REPLACE INTO content_cache (cache_key, content, expires_at)
                       VALUES (:cache_key, :content, :expires_at)"""
        else:
            query = """INSERT INTO content_cache (cache_key, content, expires_at)
                       VALUES (:cache_key, :content, :expires_at)
                       ON CONFLICT (cache_key) DO UPDATE
                       SET content = :content, expires_at = :expires_at"""

        await database.execute(query, {
            "cache_key": cache_key,
            "content": content,
            "expires_at": expires_at
        })

        cache_logger.debug(f"Saved: {cache_type} {title} ({year}) - {len(results or [])} results ({ttl}s)")
    except Exception as e:
        cache_logger.error(f"Cache save failed: {type(e).__name__}")