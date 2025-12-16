from typing import List, Dict, Optional
from wastream.scrapers.darki_api.base import BaseDarkiAPI


# ===========================
# Series Scraper Class
# ===========================
class SeriesScraper(BaseDarkiAPI):

    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None, season: Optional[str] = None, episode: Optional[str] = None, config: Optional[Dict] = None) -> List[Dict]:
        results = await self.search_content(title, year, metadata, content_type="series", season=season, episode=episode, config=config)
        return results


# ===========================
# Singleton Instance
# ===========================
series_scraper = SeriesScraper()
