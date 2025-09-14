import json
import time
from typing import Optional, List, Dict, Any
from wastream.core.config import DATABASE_TYPE
from wastream.utils.helpers import create_cache_key
from wastream.utils.logger import logger

# Get cached content if not expired
async def get_cache(database, cache_type: str, title: str, year: Optional[str] = None) -> Optional[List[Dict]]:
    cache_key = create_cache_key(cache_type, title, year)
    
    current_time = time.time()
    result = await database.fetch_one(
        "SELECT content FROM content_cache WHERE cache_key = :cache_key AND expires_at > :current_time",
        {"cache_key": cache_key, "current_time": current_time}
    )
    
    if not result:
        logger.log("CACHE", f"Miss for {cache_type}: {title} ({year})")
        return None
    
    try:
        cached_data = json.loads(result["content"])
        logger.log("CACHE", f"Hit for {cache_type}: {title} ({year}) - {len(cached_data)} results")
        return cached_data
    except json.JSONDecodeError as e:
        logger.log("CACHE", f"ERROR: Corrupted cache for {cache_key}: {e}")
        return None

# Store content in cache with expiration
async def set_cache(database, cache_type: str, title: str, year: Optional[str] = None, 
                   results: Optional[List] = None, ttl: int = 3600):
    cache_key = create_cache_key(cache_type, title, year)
    
    current_time = time.time()
    expires_at = current_time + ttl
    content = json.dumps(results or [])
    
    if DATABASE_TYPE == "sqlite":
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
    
    logger.log("CACHE", f"Saved {cache_type}: {title} ({year}) - {len(results or [])} results for {ttl}s")