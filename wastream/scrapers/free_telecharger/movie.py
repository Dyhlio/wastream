from typing import List, Dict, Optional
from wastream.scrapers.free_telecharger.base import BaseFreeTelecharger
from wastream.utils.logger import scraper_logger


# ===========================
# Movie Scraper Class
# ===========================
class MovieScraper(BaseFreeTelecharger):

    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        scraper_logger.debug(f"[FreeTelecharger] Searching movie: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "movie")
        return results


# ===========================
# Singleton Instance
# ===========================
movie_scraper = MovieScraper()
