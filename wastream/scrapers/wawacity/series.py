from typing import List, Dict, Optional
from wastream.scrapers.wawacity.base import BaseWawacity
from wastream.utils.logger import scraper_logger


# ===========================
# Series Scraper Class
# ===========================
class SeriesScraper(BaseWawacity):

    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        scraper_logger.debug(f"[Wawacity] Searching series: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "series")
        return results


# ===========================
# Singleton Instance
# ===========================
series_scraper = SeriesScraper()
