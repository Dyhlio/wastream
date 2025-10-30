import asyncio
import re
from typing import List, Dict, Optional, Any

from selectolax.parser import HTMLParser, Node

from wastream.core.config import settings
from wastream.utils.helpers import (
    quote_url_param, normalize_text, extract_and_decode_filename,
    parse_movie_info, parse_series_info, format_url, normalize_size, build_display_name
)
from wastream.utils.http_client import http_client
from wastream.utils.logger import scraper_logger
from wastream.utils.quality import quality_sort_key

# ===========================
# Constants
# ===========================
WAWACITY_SEARCH_MAX_LENGTH = 31

# ===========================
# Base Wawacity Scraper Class
# ===========================
class BaseWawacity:

    @staticmethod
    def extract_link_from_node(node: Node) -> Optional[str]:
        link = None
        attributes = node.attributes
        
        if "href" in attributes:
            link = attributes["href"]
        else:
            for value in attributes.values():
                if re.search(r"^(/|https?:)\w", value):
                    link = value
                    break
        return link

    @staticmethod
    def filter_nodes(nodes: List[Node], pattern: str) -> List[Node]:
        filtered = []
        for node in nodes:
            if isinstance(node, Node) and re.search(pattern, node.text()):
                filtered.append(node)
        return filtered

    async def search_content_by_titles(self, title: str, year: Optional[str] = None, metadata: Optional[Dict] = None, content_type: str = "films") -> Optional[Dict]:
        if metadata and metadata.get("titles"):
            titles_to_try = metadata["titles"]
        else:
            titles_to_try = [title]
        
        for search_title in titles_to_try:
            result = await self.try_search_with_title(search_title, year, metadata, content_type)
            if result:
                return result
        
        if year:
            scraper_logger.debug(f"No results found with year {year}, retrying without year...")
            for search_title in titles_to_try:
                result = await self.try_search_with_title(search_title, None, metadata, content_type)
                if result:
                    return result
        
        content_name_mapping = {"movies": "movie", "films": "movie", "series": "series", "anime": "anime", "mangas": "anime"}
        content_name = content_name_mapping.get(content_type, "content")
        scraper_logger.debug(f"[Wawacity] No {content_name} found for any title variants of '{title}'")
        return None
    
    async def try_search_with_title(self, search_title: str, year: Optional[str], metadata: Optional[Dict], default_content_type: str) -> Optional[Dict]:
        if not settings.WAWACITY_URL:
            scraper_logger.error("settings.WAWACITY_URL not configured")
            return None

        content_type = metadata.get("content_type", default_content_type) if metadata else default_content_type

        wawacity_content_type_mapping = {"movies": "films", "series": "series", "anime": "mangas"}
        wawacity_content_type = wawacity_content_type_mapping.get(content_type, content_type)

        encoded_title = quote_url_param(str(search_title)[:WAWACITY_SEARCH_MAX_LENGTH])
        search_url = f"{settings.WAWACITY_URL}/?p={wawacity_content_type}&search={encoded_title}"
        if year:
            search_url += f"&year={str(year)}"
        
        scraper_logger.debug(f"Trying search: {search_url}")
        
        try:
            response = await http_client.get(search_url)
            if response.status_code != 200:
                scraper_logger.debug(f"Search failed: {response.status_code}")
                return None

            parser = HTMLParser(response.text)
            if wawacity_content_type == "films":
                css_selector = 'a[href^="?p=film&id="]'
            elif wawacity_content_type == "series":
                css_selector = 'a[href^="?p=serie&id="]'
            else:
                css_selector = 'a[href^="?p=manga&id="]'
            search_nodes = parser.css(css_selector)

            if not search_nodes:
                scraper_logger.debug(f"No results for '{search_title}'")
                return None

            scraper_logger.debug(f"Found {len(search_nodes)} results for '{search_title}'")
            
            if metadata and metadata.get("titles"):
                verified_result = await self.verify_content_results(search_nodes, metadata, search_title, year, content_type)
            else:
                simple_metadata = {
                    "titles": [normalize_text(search_title)]
                }
                verified_result = await self.verify_content_results(search_nodes, simple_metadata, search_title, year, content_type)

            if verified_result:
                return verified_result
            else:
                scraper_logger.debug("No verified result found")
                return None
            
        except Exception as e:
            scraper_logger.error(f"Title '{search_title}' search error: {type(e).__name__}")
            return None
    
    async def verify_content_results(self, search_nodes, metadata: Dict, search_title: str = "", year: Optional[str] = None, content_type: str = "films") -> Optional[Dict]:
        try:
            if metadata.get("all_titles"):
                tmdb_titles = [normalize_text(t) for t in metadata["all_titles"]]
            else:
                tmdb_titles = [normalize_text(t) for t in metadata["titles"]]
            
            content_data = self.extract_content_from_search_page(search_nodes, content_type)

            for content in content_data:
                content_title = content.get("title", "Unknown")

                result = self.progressive_verification_from_search(content, tmdb_titles)

                if result:
                    tmdb_title = metadata.get("titles", [search_title])[0].title() if metadata.get("titles") else search_title.title()
                    content_name_mapping = {"movies": "movie", "films": "movie", "series": "series", "anime": "anime", "mangas": "anime"}
                    content_name = content_name_mapping.get(content_type, "content")
                    scraper_logger.debug(f"Found match: {content_title} (link: {content['link']})")
                    scraper_logger.debug(f"[Wawacity] Found {content_name}: '{tmdb_title}'")
                    return {
                        "link": content["link"],
                        "text": content["title"]
                    }

            scraper_logger.debug(f"No match in {len(content_data)} results for '{search_title}'")

            for page_num in range(2, settings.WAWACITY_MAX_SEARCH_PAGES + 1):
                scraper_logger.debug(f"No match found on page {page_num - 1}, trying page {page_num}...")
                page_result = await self.try_page_verification(search_title, year, tmdb_titles, page_num, content_type, metadata)
                if page_result:
                    return page_result

            return None
            
        except Exception as e:
            scraper_logger.error(f"Content verification error: {type(e).__name__}")
            return None
    
    async def try_page_verification(self, search_title: str, year: Optional[str], tmdb_titles: list, page_num: int, content_type: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        if not settings.WAWACITY_URL:
            return None

        try:
            wawacity_content_type_mapping = {"movies": "films", "series": "series", "anime": "mangas"}
            wawacity_content_type = wawacity_content_type_mapping.get(content_type, content_type)

            encoded_title = quote_url_param(str(search_title)[:WAWACITY_SEARCH_MAX_LENGTH])
            search_url = f"{settings.WAWACITY_URL}/?p={wawacity_content_type}&search={encoded_title}&page={page_num}"
            if year:
                search_url += f"&year={str(year)}"
            
            scraper_logger.debug(f"Trying page {page_num}: {search_url}")
            
            response = await http_client.get(search_url)
            if response.status_code != 200:
                return None

            parser = HTMLParser(response.text)
            if wawacity_content_type == "films":
                css_selector = 'a[href^="?p=film&id="]'
            elif wawacity_content_type == "series":
                css_selector = 'a[href^="?p=serie&id="]'
            else:
                css_selector = 'a[href^="?p=manga&id="]'
            search_nodes = parser.css(css_selector)
            
            if not search_nodes:
                scraper_logger.debug(f"No results on page {page_num}")
                return None

            scraper_logger.debug(f"Found {len(search_nodes)} results on page {page_num}")

            content_data = self.extract_content_from_search_page(search_nodes, content_type)

            for content in content_data:
                content_title = content.get("title", "Unknown")

                result = self.progressive_verification_from_search(content, tmdb_titles)

                if result:
                    tmdb_title = metadata.get("titles", [search_title])[0].title() if metadata and metadata.get("titles") else search_title.title()
                    content_name_mapping = {"movies": "movie", "films": "movie", "series": "series", "anime": "anime", "mangas": "anime"}
                    content_name = content_name_mapping.get(content_type, "content")
                    scraper_logger.debug(f"Found match on page {page_num}: {content_title}")
                    scraper_logger.debug(f"[Wawacity] Found {content_name} on page {page_num}: '{tmdb_title}'")
                    return {
                        "link": content["link"],
                        "text": content["title"]
                    }
            
            return None
            
        except Exception as e:
            scraper_logger.error(f"Page {page_num} search error: {type(e).__name__}")
            return None
    
    def extract_content_from_search_page(self, search_nodes, content_type: str) -> List[Dict]:
        content_list = []
        processed_links = set()
        
        for node in search_nodes:
            try:
                link = node.attributes.get("href", "")
                if not link or link in processed_links:
                    continue
                
                processed_links.add(link)
                
                parent_block = node.parent
                while parent_block and "wa-post-detail-item" not in parent_block.attributes.get("class", ""):
                    parent_block = parent_block.parent
                
                if not parent_block:
                    title = node.text(strip=True)
                    if not title:
                        continue
                    content_list.append({
                        "link": link,
                        "title": title
                    })
                    continue

                full_text = node.text(strip=True)
                title = full_text.split("[")[0].strip() if "[" in full_text else full_text

                if not title:
                    continue
                
                content_list.append({
                    "link": link,
                    "title": title
                })
                
            except Exception as e:
                scraper_logger.error(f"Content data extraction error: {type(e).__name__}")
                continue
        
        
        return content_list
    
    def progressive_verification_from_search(self, content_data: Dict, tmdb_titles: list) -> Optional[str]:

        normalized_title = normalize_text(content_data["title"])

        if "saison" in normalized_title.lower():
            clean_title = re.sub(r"(\s*-\s*)?saison.*$", "", normalized_title, flags=re.IGNORECASE).strip()
            title_match = any(tmdb_title == clean_title for tmdb_title in tmdb_titles)
        else:
            title_match = any(tmdb_title == normalized_title for tmdb_title in tmdb_titles)

        return "TITLE_MATCH" if title_match else None
    
    async def search_content(self, title: str, year: Optional[str] = None,
                           metadata: Optional[Dict] = None, content_type: str = "films") -> List[Dict]:
        content_names = {"films": "movie", "movies": "movie", "series": "series", "mangas": "anime", "anime": "anime"}
        content_name = content_names.get(content_type, "content")

        try:
            search_result = await self.search_content_by_titles(title, year, metadata, content_type)
            if not search_result:
                scraper_logger.debug(f"{content_name.title()} not found")
                return []

            if content_names.get(content_type) == "movie":
                results = await self._extract_movie_content(search_result, title, year)
            else:
                results = await self._extract_series_content(search_result, title, year)

            scraper_logger.debug(f"[Wawacity] {content_name.title()} links found: {len(results)}")
            return results

        except Exception as e:
            scraper_logger.error(f"[Wawacity] {content_name.title()} search error: {type(e).__name__}")
            return []

    async def _extract_movie_content(self, search_result: Dict, title: str, year: Optional[str] = None) -> List[Dict]:
        if not settings.WAWACITY_URL:
            return []

        quality_pages = []
        page_link = search_result["link"]

        quality_pages.append({"page_path": page_link})

        movie_url = f"{settings.WAWACITY_URL}/{page_link}"
        
        try:
            response = await http_client.get(movie_url)
            if response.status_code == 200:
                parser = HTMLParser(response.text)
                quality_nodes = parser.css('a[href^="?p=film&id="]:has(button)')
                
                for node in quality_nodes:
                    page_path = node.attributes.get("href", "")
                    if page_path and {"page_path": page_path} not in quality_pages:
                        quality_pages.append({"page_path": page_path})
        except Exception as e:
            scraper_logger.error(f"Quality pages extraction error: {type(e).__name__}")
        
        tasks = [self._extract_movie_links_for_quality(quality, title, year) for quality in quality_pages]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_results = []
        for result in results_lists:
            if isinstance(result, list):
                all_results.extend(result)
            elif not isinstance(result, Exception):
                scraper_logger.error(f"Unexpected result type: {type(result)}")

        scraper_logger.debug(f"[Wawacity] Formatted {len(all_results)} valid links")
        all_results.sort(key=quality_sort_key)
        return all_results

    async def _extract_series_content(self, search_result: Dict, title: str, year: Optional[str] = None) -> List[Dict]:
        if not settings.WAWACITY_URL:
            return []

        all_results = []
        content_link = search_result["link"]

        try:
            visited_pages = set()
            pages_to_process = [content_link]
            
            while pages_to_process:
                current_link = pages_to_process.pop(0)
                
                if current_link in visited_pages:
                    continue
                    
                visited_pages.add(current_link)
                current_url = f"{settings.WAWACITY_URL}/{current_link}"
                
                response = await http_client.get(current_url)
                if response.status_code == 200:
                    parser = HTMLParser(response.text)
                    
                    other_seasons = parser.css('ul.wa-post-list-ofLinks a[href^="?p=serie&id="], ul.wa-post-list-ofLinks a[href^="?p=manga&id="]')
                    for season_node in other_seasons:
                        season_link = season_node.attributes.get("href", "")
                        if season_link and "saison" in season_link.lower() and season_link not in visited_pages:
                            pages_to_process.append(season_link)
                    
                    other_qualities = parser.css('ul.wa-post-list-ofLinks a[href^="?p=serie&id="]:has(button), ul.wa-post-list-ofLinks a[href^="?p=manga&id="]:has(button)')
                    for quality_node in other_qualities:
                        quality_link = quality_node.attributes.get("href", "")
                        if quality_link and quality_link not in visited_pages:
                            pages_to_process.append(quality_link)
            
            all_pages = [{"page_path": page} for page in visited_pages]
            
            page_tasks = [self._extract_episodes_from_page(page, title, year) for page in all_pages]
            page_results = await asyncio.gather(*page_tasks, return_exceptions=True)
            
            for result in page_results:
                if isinstance(result, list):
                    all_results.extend(result)

        except Exception as e:
            scraper_logger.error(f"Series content extraction error: {type(e).__name__}")

        scraper_logger.debug(f"[Wawacity] Formatted {len(all_results)} valid links")
        all_results.sort(key=lambda x: (
            int(x.get("season", "0")),
            int(x.get("episode", "0")),
            quality_sort_key(x)
        ))

        return all_results

    async def _extract_links_from_page(self, page_info: Dict, content_type: str, title: str, year: Optional[str] = None, extract_season_from_url: bool = False) -> List[Dict]:
        if not settings.WAWACITY_URL:
            return []

        page_results = []
        page_path = page_info["page_path"]
        full_url = f"{settings.WAWACITY_URL}/{page_path}"
        
        try:
            response = await http_client.get(full_url)
            if response.status_code == 200:
                parser = HTMLParser(response.text)
                
                link_rows = parser.css('#DDLLinks tr.link-row:nth-child(n+2)')
                filtered_rows = self.filter_nodes(link_rows, r"Lien .*")
                
                for row in filtered_rows:
                    hoster_cell = row.css_first('td[width="120px"].text-center')
                    hoster_name = hoster_cell.text().strip() if hoster_cell else ""

                    size_td = row.css_first('td[width="80px"].text-center')
                    raw_size = size_td.text().strip() if size_td else "Unknown"
                    file_size = normalize_size(raw_size)
                    
                    link_node = row.css_first('a[href*="dl-protect."].link')
                    if not link_node:
                        continue
                    
                    link_url = self.extract_link_from_node(link_node)
                    if not link_url:
                        continue

                    link_text = link_node.text().strip() if link_node else ""

                    link_url = format_url(link_url, settings.WAWACITY_URL)
                    try:
                        decoded_filename = extract_and_decode_filename(link_url)
                        if decoded_filename:
                            if extract_season_from_url:
                                season_from_url = "1"

                                url_season_match = re.search(r"saison(\d+)", page_path, re.IGNORECASE)
                                if url_season_match:
                                    season_from_url = url_season_match.group(1)

                                original_filename = decoded_filename
                                if "Saison" not in decoded_filename and "Épisode" in decoded_filename:
                                    decoded_filename = decoded_filename.replace(" - Épisode", f" - Saison {season_from_url} Épisode")
                                else:
                                    pass
                            
                            if content_type == "movie":
                                content_info = parse_movie_info(decoded_filename)
                                original_filename = link_text.split(":")[-1].strip() if ":" in link_text else decoded_filename
                                result = {
                                    "link": link_url,
                                    "quality": content_info.get("quality", "Unknown"),
                                    "language": content_info.get("language", "Unknown"),
                                    "source": "Wawacity",
                                    "hoster": hoster_name.title(),
                                    "size": file_size,
                                    "display_name": original_filename,
                                    "model_type": "link"
                                }
                            else:
                                content_info = parse_series_info(decoded_filename)

                                display_name = build_display_name(
                                    title=title,
                                    year=year,
                                    language=content_info.get("language", "Unknown"),
                                    quality=content_info.get("quality", "Unknown"),
                                    season=content_info.get("season", "1"),
                                    episode=content_info.get("episode", "1")
                                )

                                result = {
                                    "link": link_url,
                                    "season": content_info.get("season", "1"),
                                    "episode": content_info.get("episode", "1"),
                                    "quality": content_info.get("quality", "Unknown"),
                                    "language": content_info.get("language", "Unknown"),
                                    "source": "Wawacity",
                                    "hoster": hoster_name.title(),
                                    "size": file_size,
                                    "display_name": display_name,
                                    "model_type": "link"
                                }

                            page_results.append(result)

                    except Exception as e:
                        error_type = "movie" if content_type == "movie" else "episode"
                        scraper_logger.error(f"Error processing {error_type} link {link_url}: {type(e).__name__}")
                        
        except Exception as e:
            error_type = "movie links" if content_type == "movie" else "episodes"
            scraper_logger.error(f"Failed to extract {error_type} from {page_path}: {type(e).__name__}")
        
        return page_results
    
    async def _extract_movie_links_for_quality(self, quality_page: Dict, title: str, year: Optional[str] = None) -> List[Dict]:
        return await self._extract_links_from_page(quality_page, "movie", title, year)

    async def _extract_episodes_from_page(self, page: Dict, title: str, year: Optional[str] = None, extract_season_from_url: bool = False) -> List[Dict]:
        return await self._extract_links_from_page(page, "series", title, year, extract_season_from_url)