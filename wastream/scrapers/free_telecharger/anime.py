from typing import List, Dict, Optional
from wastream.scrapers.free_telecharger.base import BaseFreeTelecharger
from wastream.utils.logger import scraper_logger


# ===========================
# Anime Scraper Class
# ===========================
class AnimeScraper(BaseFreeTelecharger):

    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        scraper_logger.debug(f"[FreeTelecharger] Searching anime: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "anime")
        return results


# ===========================
# Singleton Instance
# ===========================
anime_scraper = AnimeScraper()
