from typing import List, Dict, Optional
from wastream.scrapers.base import BaseScraper
from wastream.utils.logger import logger

# Movie scraper implementation
class MovieScraper(BaseScraper):
    
    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        logger.log("SCRAPER", f"Searching films: '{title}' ({year})")
        results = await self.search_content(title, year, metadata, "films")
        logger.log("SCRAPER", f"Films found: {len(results)}")
        return results

movie_scraper = MovieScraper()