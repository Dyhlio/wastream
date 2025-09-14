from typing import List, Dict, Optional
from wastream.scrapers.base import BaseScraper
from wastream.utils.logger import logger

# Series scraper implementation
class SeriesScraper(BaseScraper):
    
    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        logger.log("SCRAPER", f"Searching series: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "series")
        logger.log("SCRAPER", f"Series found: {len(results)}")
        return results

series_scraper = SeriesScraper()