import asyncio
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

from wastream.config.settings import settings
from wastream.utils.helpers import quote_url_param, normalize_text, build_display_name, normalize_size, format_url
from wastream.utils.http_client import http_client
from wastream.utils.languages import normalize_language
from wastream.utils.logger import scraper_logger
from wastream.utils.quality import quality_sort_key, normalize_quality

# ===========================
# Category Mappings
# ===========================
MOVIE_CATEGORIES = [
    "films bluray 4k", "films hd", "films hdlight", "films sd", "films web-dl",
    "films bluray", "films dvdrip", "films webrip", "films hdrip"
]

SERIES_CATEGORIES = [
    "saisons en cours vf", "saison terminee vf", "saisons en cours vostfr",
    "saison terminee vostfr", "series tv", "séries tv", "saisons en cours vf hd",
    "saison terminee vf hd"
]

ANIME_CATEGORIES = [
    "mangas vf", "mangas vost", "mangas vostfr", "série animée vf",
    "série animée vost", "série animée vostfr", "animes vf", "animes vostfr"
]

# ===========================
# Quality to ignore (bad quality)
# ===========================
IGNORED_QUALITIES = ["cam", "ts", "r5", "dvdscr", "hdcam", "hdts", "telesync", "telecine"]


# ===========================
# Base Free-Telecharger Scraper Class
# ===========================
class BaseFreeTelecharger:

    def _is_ignored_quality(self, quality: str) -> bool:
        if not quality:
            return False
        quality_lower = quality.lower()
        return any(ignored in quality_lower for ignored in IGNORED_QUALITIES)

    def _get_content_type_from_category(self, category: str) -> Optional[str]:
        if not category:
            return None

        category_lower = category.lower().strip()

        for cat in MOVIE_CATEGORIES:
            if cat in category_lower:
                return "movie"

        for cat in SERIES_CATEGORIES:
            if cat in category_lower:
                return "series"

        for cat in ANIME_CATEGORIES:
            if cat in category_lower:
                return "anime"

        return None

    def _extract_quality_from_text(self, text: str) -> str:
        if not text:
            return "Unknown"

        text_upper = text.upper()

        if "2160" in text_upper or "4K" in text_upper or "UHD" in text_upper:
            resolution = "2160p"
        elif "1080" in text_upper:
            resolution = "1080p"
        elif "720" in text_upper:
            resolution = "720p"
        elif "480" in text_upper:
            resolution = "480p"
        else:
            resolution = ""

        if "REMUX" in text_upper:
            release_type = "REMUX"
        elif "BLURAY" in text_upper or "BLU-RAY" in text_upper or "BDRIP" in text_upper:
            release_type = "BLURAY"
        elif "WEB-DL" in text_upper or "WEBDL" in text_upper:
            release_type = "WEB-DL"
        elif "HDLIGHT" in text_upper or "LIGHT" in text_upper:
            release_type = "HDLIGHT"
        elif "WEBRIP" in text_upper:
            release_type = "WEBRIP"
        elif "HDRIP" in text_upper:
            release_type = "HDRIP"
        elif "HDTV" in text_upper:
            release_type = "HDTV"
        elif "DVDRIP" in text_upper:
            release_type = "DVDRIP"
        else:
            release_type = ""

        if resolution and release_type:
            return f"{release_type} {resolution}"
        elif resolution:
            return resolution
        elif release_type:
            return release_type
        else:
            return "Unknown"

    def _extract_language_from_text(self, text: str) -> str:
        if not text:
            return "Unknown"

        text_upper = text.upper()

        if "MULTI" in text_upper:
            langs = []
            if "VFF" in text_upper or "TRUEFRENCH" in text_upper:
                normalized = normalize_language("vff")
                if normalized not in langs:
                    langs.append(normalized)
            if "VFQ" in text_upper:
                normalized = normalize_language("vfq")
                if normalized not in langs:
                    langs.append(normalized)
            if "VF" in text_upper and "VFF" not in text_upper and "VFQ" not in text_upper:
                normalized = normalize_language("vf")
                if normalized not in langs:
                    langs.append(normalized)
            if "VOSTFR" in text_upper:
                normalized = normalize_language("vostfr")
                if normalized not in langs:
                    langs.append(normalized)
            if "VO" in text_upper or "EN" in text_upper:
                normalized = normalize_language("vo")
                if normalized not in langs:
                    langs.append(normalized)
            if langs:
                return f"Multi ({', '.join(langs)})"
            return "Multi"

        if "VFF" in text_upper or "TRUEFRENCH" in text_upper:
            return normalize_language("vff")
        if "VFQ" in text_upper:
            return normalize_language("vfq")
        if "VF" in text_upper and "VOSTFR" not in text_upper:
            return normalize_language("vf")
        if "VOSTFR" in text_upper:
            return normalize_language("vostfr")
        if "VO" in text_upper:
            return normalize_language("vo")

        return "Unknown"

    def _extract_season_from_title(self, title: str) -> Optional[str]:
        if not title:
            return None

        match = re.search(r"saison\s*(\d+)", title, re.IGNORECASE)
        if match:
            return match.group(1)

        match = re.search(r"s(\d+)", title, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    def _extract_season_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None

        match = re.search(r"saison-?(\d+)", url, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    def _clean_title(self, title: str) -> str:
        if not title:
            return ""

        cleaned = re.sub(r"\s*-\s*saison\s*\d+.*$", "", title, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*\[.*?\].*$", "", cleaned)
        cleaned = re.sub(r"\s*\(.*?\)\s*$", "", cleaned)

        return cleaned.strip()

    def _is_intermediate_link(self, link: str) -> bool:
        if not link:
            return False
        parsed = urlparse(link)
        hostname = parsed.hostname or ""
        if hostname.startswith("liens."):
            return True
        return False

    async def _resolve_intermediate_link(self, link: str) -> List[Tuple[str, str]]:
        results = []
        try:
            scraper_logger.debug(f"Resolving intermediate link: {link}")
            response = await http_client.get(link)
            if response.status_code != 200:
                scraper_logger.debug(f"Failed to resolve link: {response.status_code}")
                return results

            parser = HTMLParser(response.text)

            table = parser.css_first("table.gridtable")
            if table:
                rows = table.css("tr")
                for row in rows:
                    cells = row.css("td")
                    if len(cells) >= 3:
                        hoster_cell = cells[1]
                        link_cell = cells[2]

                        hoster_text = hoster_cell.text(strip=True)
                        hoster_match = re.search(r"\[([^\]]+)\]", hoster_text)
                        hoster = hoster_match.group(1) if hoster_match else "Unknown"

                        link_node = link_cell.css_first("a")
                        if link_node:
                            real_link = link_node.attributes.get("href", "")
                            if real_link:
                                results.append((real_link, hoster))

            scraper_logger.debug(f"Resolved {len(results)} links from intermediate page")

        except Exception as e:
            scraper_logger.error(f"Intermediate link resolution error: {type(e).__name__}")

        return results

    async def search_content_by_titles(self, title: str, year: Optional[str] = None,
                                       metadata: Optional[Dict] = None,
                                       content_type: str = "movie") -> Optional[Dict]:
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

        scraper_logger.debug(f"[FreeTelecharger] No {content_type} found for any title variants of '{title}'")
        return None

    async def try_search_with_title(self, search_title: str, year: Optional[str],
                                    metadata: Optional[Dict], content_type: str) -> Optional[Dict]:
        if not settings.FREE_TELECHARGER_URL:
            scraper_logger.error("settings.FREE_TELECHARGER_URL not configured")
            return None

        encoded_title = quote_url_param(str(search_title))
        search_url = f"{settings.FREE_TELECHARGER_URL}/1/recherche1/1.html?rech_fiche={encoded_title}&rech_cat="

        if year:
            search_url += f"&rech_annee={year}"

        scraper_logger.debug(f"Trying search: {search_url}")

        try:
            response = await http_client.get(search_url)
            if response.status_code != 200:
                scraper_logger.debug(f"Search failed: {response.status_code}")
                return None

            parser = HTMLParser(response.text)
            search_results = parser.css("div.container")

            if not search_results:
                scraper_logger.debug(f"No results for '{search_title}'")
                return None

            scraper_logger.debug(f"Found {len(search_results)} results for '{search_title}'")

            if metadata and metadata.get("titles"):
                tmdb_titles = [normalize_text(t) for t in metadata.get("all_titles", metadata["titles"])]
            else:
                tmdb_titles = [normalize_text(search_title)]

            tmdb_year = metadata.get("year") if metadata else year
            verified_result = self.verify_content_results(search_results, tmdb_titles, tmdb_year, content_type)

            if verified_result:
                return verified_result

            for page_num in range(2, settings.FREE_TELECHARGER_MAX_SEARCH_PAGES + 1):
                page_result = await self.try_page_verification(search_title, year, tmdb_titles, tmdb_year, page_num, content_type)
                if page_result:
                    return page_result

            return None

        except Exception as e:
            scraper_logger.error(f"Title '{search_title}' search error: {type(e).__name__}")
            return None

    async def try_page_verification(self, search_title: str, year: Optional[str],
                                    tmdb_titles: List[str], tmdb_year: Optional[str],
                                    page_num: int, content_type: str) -> Optional[Dict]:
        if not settings.FREE_TELECHARGER_URL:
            return None

        try:
            encoded_title = quote_url_param(str(search_title))
            search_url = f"{settings.FREE_TELECHARGER_URL}/{page_num}/recherche1/?rech_fiche={encoded_title}"

            if year:
                search_url += f"&rech_annee={year}"

            scraper_logger.debug(f"Trying page {page_num}: {search_url}")

            response = await http_client.get(search_url)
            if response.status_code != 200:
                return None

            parser = HTMLParser(response.text)
            search_results = parser.css("div.container")

            if not search_results:
                scraper_logger.debug(f"No results on page {page_num}")
                return None

            scraper_logger.debug(f"Found {len(search_results)} results on page {page_num}")

            return self.verify_content_results(search_results, tmdb_titles, tmdb_year, content_type)

        except Exception as e:
            scraper_logger.error(f"Page {page_num} search error: {type(e).__name__}")
            return None

    def verify_content_results(self, search_results, tmdb_titles: List[str],
                               year: Optional[str], content_type: str) -> Optional[Dict]:
        for container in search_results:
            try:
                title_node = container.css_first("div.titre1 a")
                if not title_node:
                    title_node = container.css_first("div.titre1")

                if not title_node:
                    continue

                raw_title = title_node.text(strip=True)
                link = title_node.attributes.get("href", "") if hasattr(title_node, 'attributes') else ""

                if not raw_title:
                    continue

                category_nodes = container.css("div.link_cat b")
                category = ""
                if len(category_nodes) >= 2:
                    category = category_nodes[1].text(strip=True)
                elif len(category_nodes) == 1:
                    category = category_nodes[0].text(strip=True)

                detected_type = self._get_content_type_from_category(category)

                if detected_type and detected_type != content_type:
                    continue

                cleaned_title = self._clean_title(raw_title)
                normalized_title = normalize_text(cleaned_title)

                title_match = any(tmdb_title == normalized_title for tmdb_title in tmdb_titles)

                if not title_match:
                    continue

                freetelecharger_year = None
                container_text = container.text()
                year_match = re.search(r"Année\s*:\s*(\d{4})", container_text)
                if year_match:
                    freetelecharger_year = year_match.group(1)

                if not freetelecharger_year:
                    scraper_logger.debug("FreeTelecharger year missing, skipping")
                    continue

                if not year:
                    scraper_logger.debug("TMDB year missing, skipping")
                    continue

                if year != freetelecharger_year:
                    scraper_logger.debug(f"Year mismatch: TMDB {year} vs FreeTelecharger {freetelecharger_year}")
                    continue

                scraper_logger.debug(f"Found match: {cleaned_title} (link: {link})")
                return {
                    "link": link,
                    "title": raw_title,
                    "category": category,
                    "year": freetelecharger_year
                }

            except Exception as e:
                scraper_logger.error(f"Content data extraction error: {type(e).__name__}")
                continue

        return None

    async def _extract_movie_content(self, search_result: Dict, title: str,
                                     year: Optional[str] = None) -> List[Dict]:
        if not settings.FREE_TELECHARGER_URL:
            return []

        quality_pages = []
        page_link = search_result["link"]

        quality_pages.append({"page_path": page_link})

        movie_url = format_url(page_link, settings.FREE_TELECHARGER_URL)

        try:
            response = await http_client.get(movie_url)
            if response.status_code == 200:
                parser = HTMLParser(response.text)
                quality_nodes = parser.css('div.block1 a[href*=".html"]')

                for node in quality_nodes:
                    page_path = node.attributes.get("href", "")
                    if not page_path:
                        continue

                    page_path_lower = page_path.lower()
                    if not any(cat in page_path_lower for cat in ["films-", "series-", "mangas-", "saison"]):
                        continue

                    if {"page_path": page_path} not in quality_pages:
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

        scraper_logger.debug(f"[FreeTelecharger] Formatted {len(all_results)} valid links")
        all_results.sort(key=quality_sort_key)
        return all_results

    async def _extract_movie_links_for_quality(self, quality_page: Dict, title: str,
                                               year: Optional[str] = None) -> List[Dict]:
        if not settings.FREE_TELECHARGER_URL:
            return []

        page_results = []
        page_path = quality_page["page_path"]

        full_url = format_url(page_path, settings.FREE_TELECHARGER_URL)

        try:
            response = await http_client.get(full_url)
            if response.status_code != 200:
                return page_results

            parser = HTMLParser(response.text)
            page_text = parser.text()

            quality_match = re.search(r"Qualité\s*:\s*([^\n]+)", page_text)
            quality = normalize_quality(self._extract_quality_from_text(quality_match.group(1) if quality_match else ""))

            if self._is_ignored_quality(quality):
                scraper_logger.debug(f"Ignoring bad quality: {quality}")
                return page_results

            language_match = re.search(r"Langue\s*:\s*([^\n]+)", page_text)
            language = self._extract_language_from_text(language_match.group(1) if language_match else "")

            size_match = re.search(r"Taille\s*:\s*([^\n]+)", page_text)
            size = normalize_size(size_match.group(1).strip() if size_match else "Unknown")

            link_container = parser.css_first("div#link")
            if link_container:
                main_blocks = link_container.css("div#main")

                for block in main_blocks:
                    hoster_p = block.css_first("p")
                    hoster = hoster_p.text(strip=True) if hoster_p else "Unknown"

                    link_input = block.css_first('input[name="lien"]')
                    if not link_input:
                        continue

                    download_link = link_input.attributes.get("value", "")
                    if not download_link:
                        continue

                    display_name = build_display_name(
                        title=title,
                        year=year,
                        language=language,
                        quality=quality
                    )

                    if self._is_intermediate_link(download_link):
                        resolved_links = await self._resolve_intermediate_link(download_link)
                        for real_link, real_hoster in resolved_links:
                            result = {
                                "link": real_link,
                                "quality": quality,
                                "language": language,
                                "source": "Free-Telecharger",
                                "hoster": real_hoster.title() if real_hoster else "Unknown",
                                "size": size,
                                "display_name": display_name,
                                "model_type": "link"
                            }
                            page_results.append(result)
                    else:
                        result = {
                            "link": download_link,
                            "quality": quality,
                            "language": language,
                            "source": "Free-Telecharger",
                            "hoster": hoster.title(),
                            "size": size,
                            "display_name": display_name,
                            "model_type": "link"
                        }
                        page_results.append(result)

        except Exception as e:
            scraper_logger.error(f"Failed to extract movie links from {page_path}: {type(e).__name__}")

        return page_results

    async def _extract_series_content(self, search_result: Dict, title: str,
                                      year: Optional[str] = None) -> List[Dict]:
        if not settings.FREE_TELECHARGER_URL:
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

                current_url = format_url(current_link, settings.FREE_TELECHARGER_URL)

                response = await http_client.get(current_url)
                if response.status_code == 200:
                    parser = HTMLParser(response.text)

                    other_seasons = parser.css('div.block1 a[href*=".html"]')
                    for season_node in other_seasons:
                        season_link = season_node.attributes.get("href", "")
                        link_text = season_node.text(strip=True).lower() if season_node.text(strip=True) else ""

                        if season_link and season_link not in visited_pages:
                            season_link_lower = season_link.lower()
                            if any(cat in season_link_lower for cat in ["series-", "mangas-", "saison"]):
                                if "saison" in season_link_lower or "saison" in link_text:
                                    pages_to_process.append(season_link)

                    other_qualities = parser.css('div.block1 a[href*=".html"]')
                    for quality_node in other_qualities:
                        quality_link = quality_node.attributes.get("href", "")
                        if quality_link and quality_link not in visited_pages:
                            quality_link_lower = quality_link.lower()
                            if any(cat in quality_link_lower for cat in ["series-", "mangas-"]):
                                pages_to_process.append(quality_link)

            all_pages = [{"page_path": page} for page in visited_pages]

            page_tasks = [self._extract_episodes_from_page(page, title, year) for page in all_pages]
            page_results = await asyncio.gather(*page_tasks, return_exceptions=True)

            for result in page_results:
                if isinstance(result, list):
                    all_results.extend(result)

        except Exception as e:
            scraper_logger.error(f"Series content extraction error: {type(e).__name__}")

        scraper_logger.debug(f"[FreeTelecharger] Formatted {len(all_results)} valid links")
        all_results.sort(key=lambda x: (
            int(x.get("season", "0")),
            int(x.get("episode", "0")),
            quality_sort_key(x)
        ))

        return all_results

    async def _extract_episodes_from_page(self, page: Dict, title: str,
                                          year: Optional[str] = None) -> List[Dict]:
        if not settings.FREE_TELECHARGER_URL:
            return []

        page_results = []
        page_path = page["page_path"]

        full_url = format_url(page_path, settings.FREE_TELECHARGER_URL)

        try:
            response = await http_client.get(full_url)
            if response.status_code != 200:
                return page_results

            parser = HTMLParser(response.text)
            page_text = parser.text()

            quality_match = re.search(r"Qualité\s*:\s*([^\n]+)", page_text)
            quality = normalize_quality(self._extract_quality_from_text(quality_match.group(1) if quality_match else ""))

            if self._is_ignored_quality(quality):
                scraper_logger.debug(f"Ignoring bad quality: {quality}")
                return page_results

            language_match = re.search(r"Langue\s*:\s*([^\n]+)", page_text)
            language = self._extract_language_from_text(language_match.group(1) if language_match else "")

            size_match = re.search(r"Taille\s*:\s*([^\n]+)", page_text)
            size = normalize_size(size_match.group(1).strip() if size_match else "Unknown")

            page_title = ""
            title_node = parser.css_first("div.titre1")
            if title_node:
                page_title = title_node.text(strip=True)

            season = self._extract_season_from_title(page_title)
            if not season:
                season = self._extract_season_from_url(page_path)
            if not season:
                season = "1"

            link_container = parser.css_first("div#link")
            if link_container:
                main_blocks = link_container.css("div#main")

                for block in main_blocks:
                    episode_p = block.css_first("p")
                    if not episode_p:
                        continue

                    episode_text = episode_p.text(strip=True)
                    episode_match = re.search(r"[EeÉé]pisode\s*(\d+)", episode_text)

                    if episode_match:
                        episode = episode_match.group(1)
                        remaining_text = re.sub(r"[EeÉé]pisode\s*\d+", "", episode_text).strip()
                        hoster = remaining_text if remaining_text else "Unknown"
                    else:
                        continue

                    form = block.css_first("form")
                    if not form:
                        continue

                    link_input = form.css_first('input[name="lien"]')
                    if not link_input:
                        continue

                    download_link = link_input.attributes.get("value", "")
                    if not download_link:
                        continue

                    display_name = build_display_name(
                        title=title,
                        year=year,
                        language=language,
                        quality=quality,
                        season=season,
                        episode=episode
                    )

                    if self._is_intermediate_link(download_link):
                        resolved_links = await self._resolve_intermediate_link(download_link)
                        for real_link, real_hoster in resolved_links:
                            result = {
                                "link": real_link,
                                "season": season,
                                "episode": episode,
                                "quality": quality,
                                "language": language,
                                "source": "Free-Telecharger",
                                "hoster": real_hoster.title() if real_hoster else "Unknown",
                                "size": size,
                                "display_name": display_name,
                                "model_type": "link"
                            }
                            page_results.append(result)
                    else:
                        result = {
                            "link": download_link,
                            "season": season,
                            "episode": episode,
                            "quality": quality,
                            "language": language,
                            "source": "Free-Telecharger",
                            "hoster": hoster.title() if hoster else "Unknown",
                            "size": size,
                            "display_name": display_name,
                            "model_type": "link"
                        }
                        page_results.append(result)

        except Exception as e:
            scraper_logger.error(f"Failed to extract episodes from {page_path}: {type(e).__name__}")

        return page_results

    async def search_content(self, title: str, year: Optional[str] = None,
                             metadata: Optional[Dict] = None,
                             content_type: str = "movie") -> List[Dict]:
        try:
            search_result = await self.search_content_by_titles(title, year, metadata, content_type)
            if not search_result:
                scraper_logger.debug(f"{content_type.title()} not found")
                return []

            if content_type == "movie":
                results = await self._extract_movie_content(search_result, title, year)
            else:
                results = await self._extract_series_content(search_result, title, year)

            scraper_logger.debug(f"[FreeTelecharger] {content_type.title()} links found: {len(results)}")
            return results

        except Exception as e:
            scraper_logger.error(f"[FreeTelecharger] {content_type.title()} search error: {type(e).__name__}")
            return []
