from typing import List, Dict, Optional
from wastream.scrapers.wawacity.base import BaseWawacity
from wastream.utils.logger import scraper_logger

# ===========================
# Movie Scraper Class
# ===========================
class MovieScraper(BaseWawacity):

    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        scraper_logger.debug(f"[Wawacity] Searching movie: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "films")
        return results

# ===========================
# Singleton Instance
# ===========================
movie_scraper = MovieScraper()