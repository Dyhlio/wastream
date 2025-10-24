import asyncio
from typing import List, Dict, Optional, Any

from wastream.core.config import settings
from wastream.utils.helpers import normalize_text, normalize_size, build_display_name
from wastream.utils.http_client import http_client
from wastream.utils.languages import combine_languages
from wastream.utils.logger import scraper_logger
from wastream.utils.quality import quality_sort_key, normalize_quality

# ===========================
# Base Darki API Client Class
# ===========================
class BaseDarkiAPI:

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if settings.DARKI_API_KEY:
            headers["X-API-Key"] = settings.DARKI_API_KEY
        return headers

    async def search_by_titles(self, titles: List[str], metadata: Optional[Dict] = None) -> Optional[Dict]:
        if not settings.DARKI_API_URL:
            scraper_logger.error("settings.DARKI_API_URL not configured")
            return None

        if not metadata:
            scraper_logger.error("Metadata required for matching")
            return None

        has_imdb_id = metadata.get("imdb_id")

        if has_imdb_id:
            return await self._search_by_imdb_id(titles, metadata)
        else:
            return await self._search_by_name_and_year(titles, metadata)

    async def _search_by_imdb_id(self, titles: List[str], metadata: Dict) -> Optional[Dict]:
        target_imdb_id = metadata["imdb_id"]
        headers = self._get_headers()

        for search_title in titles:
            try:
                scraper_logger.debug(f"Searching with title: '{search_title}'")

                search_url = f"{settings.DARKI_API_URL}/search"
                params = {"q": search_title}

                response = await http_client.get(search_url, params=params, headers=headers)

                if response.status_code != 200:
                    scraper_logger.debug(f"Search failed: {response.status_code}")
                    continue

                data = response.json()
                results = data.get("results", [])

                if not results:
                    scraper_logger.debug(f"No results for '{search_title}'")
                    continue

                scraper_logger.debug(f"Found {len(results)} results for '{search_title}'")

                for result in results:
                    result_imdb_id = result.get("imdb_id")
                    result_name = result.get("name", "Unknown")

                    if result_imdb_id and result_imdb_id == target_imdb_id:
                        scraper_logger.debug(f"Found match by IMDB ID: {result.get('name')} (ID: {result.get('id')})")
                        return result

                scraper_logger.debug(f"No IMDB match in {len(results)} results for '{search_title}'")

            except Exception as e:
                scraper_logger.error(f"Title '{search_title}' search error: {type(e).__name__}")
                continue

        scraper_logger.debug("No match found for any title variant")
        return None

    async def _search_by_name_and_year(self, titles: List[str], metadata: Dict) -> Optional[Dict]:
        target_year = metadata.get("year")

        if metadata.get("all_titles"):
            normalized_targets = [normalize_text(t) for t in metadata["all_titles"]]
        else:
            normalized_targets = [normalize_text(t) for t in titles]
        headers = self._get_headers()

        for search_title in titles:
            try:
                scraper_logger.debug(f"Searching Kitsu anime: '{search_title}'")

                search_url = f"{settings.DARKI_API_URL}/search"
                params = {
                    "q": search_title,
                    "content_type": "animes"
                }

                response = await http_client.get(search_url, params=params, headers=headers)

                if response.status_code != 200:
                    scraper_logger.debug(f"Search failed: {response.status_code}")
                    continue

                data = response.json()
                results = data.get("results", [])

                if not results:
                    scraper_logger.debug(f"No results for '{search_title}'")
                    continue

                scraper_logger.debug(f"Found {len(results)} anime results for '{search_title}'")

                for result in results:
                    result_name = result.get("name", "")
                    result_name_normalized = normalize_text(result_name)

                    if result_name_normalized in normalized_targets:
                        scraper_logger.debug(f"Kitsu match by name: {result_name} [ID: {result.get('id')}]")
                        return result

                scraper_logger.debug(f"No name match for '{search_title}'")

            except Exception as e:
                scraper_logger.error(f"Kitsu '{search_title}' search error: {type(e).__name__}")
                continue

        scraper_logger.debug("No Kitsu match found for any title variant")
        return None

    async def get_all_links(self, title_id: int, season: Optional[str] = None, episode: Optional[str] = None) -> List[Dict]:
        if not settings.DARKI_API_URL:
            scraper_logger.error("settings.DARKI_API_URL not configured")
            return []

        all_links = []
        page = 1
        headers = self._get_headers()

        while True:
            try:
                links_url = f"{settings.DARKI_API_URL}/titles/{title_id}/links"
                params = {"page": page}

                if season:
                    params["season"] = season
                if episode:
                    params["episode"] = episode

                scraper_logger.debug(f"Fetching links page {page} for title {title_id}")

                response = await http_client.get(links_url, params=params, headers=headers)

                if response.status_code != 200:
                    scraper_logger.debug(f"Links request failed: {response.status_code} on page {page}")
                    break

                data = response.json()
                pagination = data.get("pagination", {})
                links = pagination.get("data", [])

                if not links:
                    scraper_logger.debug(f"No more links on page {page}")
                    break

                all_links.extend(links)
                scraper_logger.debug(f"Found {len(links)} links on page {page}")

                next_page = pagination.get("next_page")
                if not next_page:
                    break

                page += 1

                if page > settings.DARKI_API_MAX_LINK_PAGES:
                    scraper_logger.debug(f"Reached page limit ({settings.DARKI_API_MAX_LINK_PAGES})")
                    break

            except Exception as e:
                scraper_logger.error(f"Links page {page} fetch error: {type(e).__name__}")
                break

        scraper_logger.debug(f"Total links fetched: {len(all_links)}")
        return all_links

    async def verify_and_get_link(self, link_id: int) -> Optional[str]:
        if not settings.DARKI_API_URL:
            scraper_logger.error("settings.DARKI_API_URL not configured")
            return None

        try:
            verify_url = f"{settings.DARKI_API_URL}/links/{link_id}"
            headers = self._get_headers()

            response = await http_client.get(verify_url, headers=headers)

            if response.status_code != 200:
                scraper_logger.debug(f"Link verification failed: {response.status_code} for ID {link_id}")
                return None

            data = response.json()
            status = data.get("status")

            if status != "KO":
                scraper_logger.debug(f"Link {link_id} is not valid (status: {status})")
                return None

            link_data = data.get("lien", {})
            download_url = link_data.get("lien") if isinstance(link_data, dict) else None

            if not download_url:
                scraper_logger.debug(f"No download URL found for link {link_id}")
                return None

            return download_url

        except Exception as e:
            scraper_logger.error(f"Link {link_id} verification error: {type(e).__name__}")
            return None

    async def search_content(self, title: str, year: Optional[str] = None,
                            metadata: Optional[Dict] = None, content_type: str = "movie",
                            season: Optional[str] = None, episode: Optional[str] = None) -> List[Dict]:
        content_names = {"movie": "movie", "series": "series", "anime": "anime"}
        content_name = content_names.get(content_type, "content")

        if season and episode:
            scraper_logger.debug(f"[Darki-API] Searching {content_name}: '{title}' S{season}E{episode}")
        else:
            scraper_logger.debug(f"[Darki-API] Searching {content_name}: '{title}' ({year})")

        try:
            search_titles = []

            if metadata and metadata.get("titles"):
                search_titles.extend(metadata["titles"])

            if title not in search_titles:
                search_titles.append(title)

            content = await self.search_by_titles(search_titles, metadata)

            if not content:
                scraper_logger.debug(f"{content_name.title()} not found")
                return []

            title_id = content.get("id")
            content_title = content.get("name", title)

            if not title_id:
                scraper_logger.error("No title ID found")
                return []

            scraper_logger.debug(f"Found {content_name}: {content_title} (ID: {title_id})")

            if season and episode:
                links = await self.get_all_links(title_id, season=season, episode=episode)

                if not links:
                    scraper_logger.debug(f"No links found for S{season}E{episode}")
                    return []
            else:
                links = await self.get_all_links(title_id)

                if not links:
                    scraper_logger.debug(f"No links found for {content_name}")
                    return []

            is_series = season is not None and episode is not None

            results = await self.format_links(links, content_title, year=year, is_series=is_series)

            scraper_logger.debug(f"[Darki-API] {content_name.title()} links found: {len(results)}")
            return results

        except Exception as e:
            scraper_logger.error(f"[Darki-API] {content_name.title()} search error: {type(e).__name__}")
            return []

    async def format_links(self, links: List[Dict], content_title: str, year: Optional[str] = None, is_series: bool = False, user_prefs: list = None) -> List[Dict]:
        if not links:
            return []

        verification_tasks = [self.verify_and_get_link(link.get("id")) for link in links]
        verified_urls = await asyncio.gather(*verification_tasks, return_exceptions=True)

        formatted_results = []

        for i, link in enumerate(links):
            try:
                download_url = verified_urls[i]

                if isinstance(download_url, Exception) or not download_url:
                    continue

                host_data = link.get("host", {})
                host_name = host_data.get("name", "Unknown")

                qual_data = link.get("qual", {})
                raw_quality = qual_data.get("qual", "Unknown") if isinstance(qual_data, dict) else "Unknown"
                quality = normalize_quality(raw_quality)

                languages_compact = link.get("langues_compact", [])
                audio_langs = [lang.get("name", "") for lang in languages_compact if isinstance(lang, dict)]

                subs_compact = link.get("subs_compact", [])
                subtitle_langs = [sub.get("name", "") for sub in subs_compact if isinstance(sub, dict)]

                language = combine_languages(audio_langs, subtitle_langs, user_prefs)

                size = link.get("taille", 0)
                if size and size > 0:
                    size_gb = size / (1024 ** 3)
                    size_str = f"{size_gb:.2f} GB"
                else:
                    size_str = "Unknown"

                size_str = normalize_size(size_str)

                season = None
                episode = None
                if is_series:
                    season = str(link.get("saison", "1"))
                    episode = str(link.get("episode", "1"))

                display_name = build_display_name(
                    title=content_title,
                    year=year,
                    language=language,
                    quality=quality,
                    season=season,
                    episode=episode
                )

                result = {
                    "link": download_url,
                    "quality": quality,
                    "language": language,
                    "source": "Darki-API",
                    "hoster": host_name.title(),
                    "size": size_str,
                    "display_name": display_name
                }

                if is_series:
                    result["season"] = season
                    result["episode"] = episode

                formatted_results.append(result)

            except Exception as e:
                scraper_logger.error(f"Link format error: {type(e).__name__}")
                continue

        formatted_results.sort(key=quality_sort_key)

        scraper_logger.debug(f"[Darki-API] Formatted {len(formatted_results)} valid links")
        return formatted_results

    async def get_title_details(self, title_id: int) -> Optional[Dict]:
        if not settings.DARKI_API_URL:
            scraper_logger.error("settings.DARKI_API_URL not configured")
            return None

        try:
            url = f"{settings.DARKI_API_URL}/titles/{title_id}"
            headers = self._get_headers()

            scraper_logger.debug(f"Fetching title details for ID {title_id}")

            response = await http_client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                scraper_logger.debug(f"Title details retrieved for ID {title_id}")
                return data
            else:
                scraper_logger.debug(f"Title details fetch failed: {response.status_code}")
                return None

        except Exception as e:
            scraper_logger.error(f"Title details error: {type(e).__name__}")
            return None

    async def map_kitsu_absolute_to_darki_season(self, title_id: int, absolute_episode: int) -> Optional[tuple]:
        details = await self.get_title_details(title_id)

        if not details:
            scraper_logger.debug("No title details for mapping")
            return None

        title_data = details.get("title", {})
        seasons_data = details.get("seasons", {})
        seasons = seasons_data.get("data", [])

        if not seasons:
            scraper_logger.debug("No seasons data found")
            return None

        regular_seasons = [s for s in seasons if s.get("number", 0) > 0]

        regular_seasons.sort(key=lambda s: s.get("number", 0))

        episode_counter = 0

        for season in regular_seasons:
            season_number = season.get("number")
            episode_count = season.get("episodes_count", 0)

            if episode_counter + episode_count >= absolute_episode:
                episode_in_season = absolute_episode - episode_counter

                scraper_logger.debug(f"Kitsu episode {absolute_episode} (absolute) → Darki S{season_number}E{episode_in_season}")
                return (str(season_number), str(episode_in_season))

            episode_counter += episode_count

        scraper_logger.debug(f"Episode {absolute_episode} exceeds total episodes ({episode_counter})")
        return None
