import asyncio
from typing import List, Dict, Optional
from wastream.scrapers.base import BaseScraper
from wastream.core.config import WAWACITY_URL
from wastream.utils.http_client import http_client
from wastream.utils.logger import logger
from selectolax.parser import HTMLParser

# Anime scraper implementation
class AnimeScraper(BaseScraper):
    
    async def search(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> List[Dict]:
        logger.log("SCRAPER", f"Searching anime: '{title}' ({year})")
        try:
            search_result = await self._search_anime(title, year, metadata)
            if not search_result:
                logger.log("SCRAPER", f"Anime found: 0")
                return []
            
            all_episodes = await self._extract_all_episodes(search_result)
            
            all_episodes.sort(key=lambda x: (
                int(x.get("season", "0")),
                int(x.get("episode", "0")),
                self.quality_sort_key(x)
            ))
            
            logger.log("SCRAPER", f"Anime found: {len(all_episodes)}")
            return all_episodes
            
        except Exception as e:
            logger.log("SCRAPER", f"ERROR: Anime search failed for '{title}': {e}")
            return []
    
    async def _search_anime(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None) -> Optional[Dict]:
        return await self.search_content_by_titles(title, year, metadata, "mangas")
    
    async def _extract_all_episodes(self, search_result: Dict) -> List[Dict]:
        all_results = []
        anime_link = search_result["link"]
        
        try:
            visited_pages = set()
            pages_to_process = [anime_link]
            
            
            while pages_to_process:
                current_link = pages_to_process.pop(0)
                
                if current_link in visited_pages:
                    continue
                    
                visited_pages.add(current_link)
                current_url = f"{WAWACITY_URL}/{current_link}"
                
                
                response = await http_client.get(current_url)
                if response.status_code == 200:
                    parser = HTMLParser(response.text)
                    
                    other_seasons = parser.css('ul.wa-post-list-ofLinks a[href^="?p=manga&id="]')
                    for season_node in other_seasons:
                        season_link = season_node.attributes.get("href", "")
                        if season_link and "saison" in season_link.lower() and season_link not in visited_pages:
                            pages_to_process.append(season_link)
                    
                    other_qualities = parser.css('ul.wa-post-list-ofLinks a[href^="?p=manga&id="]:has(button)')
                    for quality_node in other_qualities:
                        quality_link = quality_node.attributes.get("href", "")
                        if quality_link and quality_link not in visited_pages:
                            button_text = quality_node.text(strip=True)
                            pages_to_process.append(quality_link)
            
            all_anime_pages = [{"page_path": page} for page in visited_pages]
            
            page_tasks = []
            for anime_page in all_anime_pages:
                page_tasks.append(
                    self._extract_episodes_from_page(anime_page, extract_season_from_url=True)
                )
            
            page_results = await asyncio.gather(*page_tasks, return_exceptions=True)
            
            for result in page_results:
                if isinstance(result, list):
                    all_results.extend(result)
            
        except Exception as e:
            logger.log("SCRAPER", f"ERROR: Failed to extract all episodes: {e}")
        
        return all_results

anime_scraper = AnimeScraper()