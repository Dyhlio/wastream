import asyncio
import re
import time
from typing import List, Dict, Optional

from fastapi.responses import FileResponse, RedirectResponse

from wastream.config.settings import settings
from wastream.debrid.alldebrid import alldebrid_service
from wastream.debrid.torbox import torbox_service
from wastream.debrid.premiumize import premiumize_service
from wastream.debrid.onefichier import onefichier_service
from wastream.scrapers.darki_api.anime import anime_scraper as darki_api_anime_scraper
from wastream.scrapers.darki_api.base import BaseDarkiAPI
from wastream.scrapers.darki_api.movie import movie_scraper as darki_api_movie_scraper
from wastream.scrapers.darki_api.series import series_scraper as darki_api_series_scraper
from wastream.scrapers.wawacity.anime import anime_scraper
from wastream.scrapers.wawacity.movie import movie_scraper
from wastream.scrapers.wawacity.series import series_scraper
from wastream.scrapers.free_telecharger.anime import anime_scraper as free_telecharger_anime_scraper
from wastream.scrapers.free_telecharger.movie import movie_scraper as free_telecharger_movie_scraper
from wastream.scrapers.free_telecharger.series import series_scraper as free_telecharger_series_scraper
from wastream.services.kitsu import kitsu_service
from wastream.services.tmdb import tmdb_service
from wastream.utils.cache import get_cache, set_cache
from wastream.utils.database import SearchLock, is_dead_link, mark_dead_link, database
from wastream.utils.filters import apply_all_filters, filter_excluded_keywords, filter_archive_files
from wastream.utils.helpers import (
    encode_config_to_base64, quote_url_param,
    deduplicate_and_sort_results, get_debrid_api_key, get_debrid_services
)
from wastream.utils.languages import MULTI_LANGUAGE_PREFIX, MULTI_PREFIX_LENGTH
from wastream.utils.logger import stream_logger, scraper_logger, metadata_logger
from wastream.utils.quality import quality_sort_key
from wastream.utils.validators import extract_media_info


# ===========================
# Stream Service Class
# ===========================
class StreamService:

    def _get_debrid_service(self, service_name: str):
        if service_name == "torbox":
            return torbox_service
        elif service_name == "premiumize":
            return premiumize_service
        elif service_name == "1fichier":
            return onefichier_service
        else:
            return alldebrid_service

    def _get_default_sources_for_service(self, service_name: str) -> List[str]:
        if service_name == "torbox":
            return settings.TORBOX_SUPPORTED_SOURCES
        elif service_name == "premiumize":
            return settings.PREMIUMIZE_SUPPORTED_SOURCES
        elif service_name == "1fichier":
            return settings.ONEFICHIER_SUPPORTED_SOURCES
        else:
            return settings.ALLDEBRID_SUPPORTED_SOURCES

    def _get_sources_for_service(self, service_name: str, service_entry: Dict = None) -> List[str]:
        if service_entry and "sources" in service_entry and service_entry["sources"]:
            return service_entry["sources"]
        return self._get_default_sources_for_service(service_name)

    def _get_default_hosts_for_service(self, service_name: str) -> List[str]:
        if service_name == "torbox":
            return settings.TORBOX_SUPPORTED_HOSTS
        elif service_name == "premiumize":
            return settings.PREMIUMIZE_SUPPORTED_HOSTS
        elif service_name == "1fichier":
            return settings.ONEFICHIER_SUPPORTED_HOSTS
        else:
            return settings.ALLDEBRID_SUPPORTED_HOSTS

    def _get_hosts_for_service(self, service_name: str, service_entry: Dict = None) -> List[str]:
        if service_entry and "hosts" in service_entry and service_entry["hosts"]:
            return service_entry["hosts"]
        return self._get_default_hosts_for_service(service_name)

    def _get_supported_sources(self, config: Dict) -> List[str]:
        debrid_services = get_debrid_services(config)
        if not debrid_services:
            return settings.ALLDEBRID_SUPPORTED_SOURCES

        all_sources = set()
        for service_entry in debrid_services:
            service_name = service_entry.get("service", "alldebrid")
            all_sources.update(self._get_sources_for_service(service_name, service_entry))

        return list(all_sources)

    async def _check_cache_and_enrich(
        self,
        results: List[Dict],
        debrid_services: List[Dict],
        config: Dict,
        timeout_remaining: float,
        season: Optional[str] = None,
        episode: Optional[str] = None
    ) -> List[Dict]:
        if not debrid_services:
            return []

        source_mapping = {
            "wawacity": "Wawacity",
            "free-telecharger": "Free-Telecharger",
            "darki-api": "Darki-API"
        }

        async def check_single(service_entry):
            service_name = service_entry.get("service", "alldebrid")
            api_key = service_entry.get("api_key", "")
            debrid_service = self._get_debrid_service(service_name)

            supported_sources = self._get_sources_for_service(service_name, service_entry)
            allowed_sources = [source_mapping.get(s, s) for s in supported_sources]

            filtered_results = [
                r.copy() for r in results
                if r.get("source") in allowed_sources
            ]

            if not filtered_results:
                return []

            user_hosts = self._get_hosts_for_service(service_name, service_entry)

            enriched = await debrid_service.check_cache_and_enrich(
                filtered_results, api_key, config, timeout_remaining, season, episode, user_hosts
            )

            for r in enriched:
                r["debrid_service"] = service_name

            return enriched

        tasks = [check_single(entry) for entry in debrid_services]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged_results = []
        for idx, result in enumerate(all_results):
            if isinstance(result, list):
                merged_results.extend(result)
            elif isinstance(result, Exception):
                service_name = debrid_services[idx].get("service", "unknown")
                stream_logger.error(f"Cache check failed for {service_name}: {result}")

        merged_results.sort(key=quality_sort_key)

        return merged_results

    async def _format_streams(
        self,
        results: List[Dict],
        config: Dict,
        base_url: str,
        season: Optional[str],
        episode: Optional[str],
        year: Optional[str]
    ) -> List[Dict]:
        streams = []
        dead_links_count = 0

        debrid_services = get_debrid_services(config)
        service_order = {entry.get("service"): idx for idx, entry in enumerate(debrid_services)}

        for result in results:
            link = result.get("link")
            if not link:
                continue

            if await is_dead_link(link):
                dead_links_count += 1
                continue

            quality = result.get("quality", "Unknown")
            language = result.get("language", "Unknown")
            hoster = result.get("hoster", "Unknown")
            size = result.get("size", "Unknown")
            display_name = result.get("display_name", "Unknown")
            episode_num = result.get("episode") if result.get("episode") is not None else episode
            season_num = result.get("season") if result.get("season") is not None else season

            service_name = result.get("debrid_service", "alldebrid")
            if service_name == "torbox":
                service_abbr = "TB"
            elif service_name == "premiumize":
                service_abbr = "PM"
            elif service_name == "1fichier":
                service_abbr = "1F"
            else:
                service_abbr = "AD"

            debrid_filename = result.get("debrid_filename")
            if debrid_filename and debrid_filename.strip():
                if not (debrid_filename.startswith("Unknown") and debrid_filename.endswith("Link")):
                    display_name = debrid_filename

            user_languages = config.get("languages", [])
            if user_languages and language.startswith(MULTI_LANGUAGE_PREFIX.title()) and language.endswith(")"):
                multi_langs = language[MULTI_PREFIX_LENGTH:-1]
                multi_langs_list = [lang.strip() for lang in multi_langs.split(",")]

                filtered_langs = [lang for lang in multi_langs_list if lang in user_languages]

                if filtered_langs:
                    filtered_multi = f"Multi ({', '.join(filtered_langs)})"
                    language = filtered_multi

                    if "Multi (" in display_name and ")" in display_name:
                        pattern = r"Multi \([^)]+\)"
                        display_name = re.sub(pattern, filtered_multi, display_name)

            cache_status = result.get("cache_status", "uncached")
            cache_emoji = "⚡" if cache_status == "cached" else "⏳"

            if cache_status == "cached" and result.get("cached_link"):
                playback_url = result.get("cached_link")
            else:
                quoted_link = quote_url_param(link)
                config_b64 = encode_config_to_base64(config)
                quoted_config_b64 = quote_url_param(config_b64)
                playback_url = f"{base_url}/resolve?link={quoted_link}&b64config={quoted_config_b64}&service={service_name}"

                if season_num:
                    playback_url += f"&season={season_num}"
                if episode_num:
                    playback_url += f"&episode={episode_num}"

            stream_name = f"[{service_abbr} {cache_emoji}] {settings.ADDON_NAME}"

            description_parts = []
            if language and language != "Unknown":
                description_parts.append(f"🌍 {language}")
            if quality and quality != "Unknown":
                description_parts.append(f"🎞️ {quality}")

            size_year_parts = []
            if size and size != "Unknown":
                size_year_parts.append(f"📦 {size}")
            if year:
                size_year_parts.append(f"📅 {year}")
            if size_year_parts:
                description_parts.append(" ".join(size_year_parts))

            source_line = ""
            source = result.get("source", "Wawacity")
            if source == "Darki-API":
                source_line += "🌐 Darki-API"
            elif source == "Free-Telecharger":
                source_line += "🌐 Free-Telecharger"
            else:
                source_line += "🌐 Wawacity"

            if hoster and hoster != "Unknown":
                source_line += f" ☁️ {hoster}"

            if source_line:
                description_parts.append(source_line)

            if display_name and display_name != "Unknown":
                description_parts.append(f"📁 {display_name}")

            streams.append({
                "name": stream_name,
                "description": "\r\n".join(description_parts),
                "behaviorHints": {
                    "filename": display_name
                },
                "url": playback_url,
                "_cache_priority": 0 if cache_status == "cached" else 1,
                "_quality_key": quality_sort_key(result),
                "_service_order": service_order.get(service_name, 999)
            })

        streams.sort(key=lambda s: (s["_cache_priority"], s["_quality_key"], s["_service_order"]))

        for s in streams:
            del s["_cache_priority"]
            del s["_quality_key"]
            del s["_service_order"]

        stream_logger.debug(f"Skipped {dead_links_count} dead links")
        stream_logger.debug(f"Returning {len(streams)} stream(s)")
        return streams

    async def get_streams(self, content_type: str, content_id: str,
                          config: Dict, base_url: str) -> List[Dict]:
        start_time = time.time()

        media_info = extract_media_info(content_id, content_type)

        if media_info.get("kitsu_id"):
            return await self._handle_kitsu_request(media_info, config, base_url, start_time)

        metadata = await self._get_metadata(
            media_info["imdb_id"],
            config.get("tmdb_api_token", "")
        )

        if not metadata:
            stream_logger.error(f"TMDB metadata failed for {media_info['imdb_id']}")
            return []

        results = await self._search_content(
            metadata["title"],
            metadata.get("year"),
            content_type,
            media_info.get("season"),
            media_info.get("episode"),
            metadata.get("enhanced"),
            config
        )

        if not results:
            stream_logger.debug(f"No content: '{metadata['title']}' ({metadata.get('year', 'Unknown')})")
            return []

        results = deduplicate_and_sort_results(results, quality_sort_key)

        results = apply_all_filters(results, config)

        elapsed = time.time() - start_time
        timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT)
        remaining_time = max(0, timeout - elapsed)

        debrid_services = get_debrid_services(config)
        enriched_results = await self._check_cache_and_enrich(
            results, debrid_services, config, remaining_time,
            media_info.get("season"), media_info.get("episode")
        )

        streams = await self._format_streams(
            enriched_results,
            config,
            base_url,
            media_info.get("season"),
            media_info.get("episode"),
            metadata.get("year")
        )

        streams = filter_archive_files(streams)

        excluded_keywords = config.get("excluded_keywords", [])
        if excluded_keywords:
            filtered_streams = filter_excluded_keywords(streams, excluded_keywords)
            excluded_count = len(streams) - len(filtered_streams)
            if excluded_count > 0:
                stream_logger.debug(f"Excluded {excluded_count} streams")
            return filtered_streams

        return streams

    async def _get_metadata(self, imdb_id: str, tmdb_api_token: str) -> Optional[Dict]:
        if not tmdb_api_token or not tmdb_api_token.strip():
            stream_logger.error("No TMDB token")
            return None

        try:
            enhanced_metadata = await tmdb_service.get_enhanced_metadata(imdb_id, tmdb_api_token)
            if enhanced_metadata:
                return {
                    "title": enhanced_metadata["titles"][0] if enhanced_metadata["titles"] else "",
                    "year": enhanced_metadata["year"],
                    "type": enhanced_metadata["type"],
                    "enhanced": enhanced_metadata
                }

            return await tmdb_service.get_metadata(imdb_id, tmdb_api_token)

        except Exception as e:
            stream_logger.error(f"Metadata fetch error: {type(e).__name__}")
            return None

    async def _search_content(self, title: str, year: Optional[str],
                              content_type: str, season: Optional[str],
                              episode: Optional[str], metadata: Optional[Dict] = None, config: Dict = None) -> List[Dict]:
        if metadata and metadata.get("content_type") == "anime":
            return await self._search_anime(title, year, season, episode, metadata, config)
        elif content_type == "series":
            return await self._search_series(title, year, season, episode, metadata, config)
        else:
            return await self._search_movie(title, year, metadata, config)

    async def _background_refresh_wawacity(self, cache_type: str, scraper, title: str,
                                           year: Optional[str], metadata: Optional[Dict] = None) -> None:
        try:
            stream_logger.debug(f"Background refresh: {cache_type} {title} ({year})")
            results = await scraper.search(title, year, metadata)
            if results:
                await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)
                stream_logger.debug(f"Background refresh done: {len(results)} results")
        except Exception as e:
            stream_logger.error(f"Background refresh failed: {type(e).__name__}")

    async def _search_wawacity_with_cache(self, content_type: str, scraper, title: str,
                                          year: Optional[str], metadata: Optional[Dict] = None,
                                          season: Optional[str] = None, episode: Optional[str] = None) -> List[Dict]:
        cache_types = {"movies": "wawacity_movie", "series": "wawacity_series", "anime": "wawacity_anime"}
        cache_type = cache_types.get(content_type, f"wawacity_{content_type}")

        lock_type = {"movies": "wawacity_movie", "series": "wawacity_series", "anime": "wawacity_anime"}[content_type]

        if settings.CONTENT_CACHE_MODE == "live":
            cached_results = await get_cache(database, cache_type, title, year)

            if cached_results is not None:
                asyncio.create_task(self._background_refresh_wawacity(cache_type, scraper, title, year, metadata))
                return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

            async with SearchLock(lock_type, title, year):
                cached_results = await get_cache(database, cache_type, title, year)
                if cached_results is not None:
                    return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

                results = await scraper.search(title, year, metadata)

                if results:
                    await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)

                return self._filter_episode_results(results, season, episode, content_type, metadata)

        async with SearchLock(lock_type, title, year):
            cached_results = await get_cache(database, cache_type, title, year)
            if cached_results is not None:
                stream_logger.debug(f"Using cached results for {content_type}")
                return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

            results = await scraper.search(title, year, metadata)

            if results:
                await set_cache(
                    database, cache_type, title, year,
                    results, settings.CONTENT_CACHE_TTL
                )

            return self._filter_episode_results(results, season, episode, content_type, metadata)

    async def _background_refresh_free_telecharger(self, cache_type: str, scraper, title: str,
                                                   year: Optional[str], metadata: Optional[Dict] = None) -> None:
        try:
            stream_logger.debug(f"Background refresh: {cache_type} {title} ({year})")
            results = await scraper.search(title, year, metadata)
            if results:
                await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)
                stream_logger.debug(f"Background refresh done: {len(results)} results")
        except Exception as e:
            stream_logger.error(f"Background refresh failed: {type(e).__name__}")

    async def _search_free_telecharger_with_cache(self, content_type: str, scraper, title: str,
                                                  year: Optional[str], metadata: Optional[Dict] = None,
                                                  season: Optional[str] = None, episode: Optional[str] = None) -> List[Dict]:
        cache_types = {"movies": "free_telecharger_movie", "series": "free_telecharger_series", "anime": "free_telecharger_anime"}
        cache_type = cache_types.get(content_type, f"free_telecharger_{content_type}")

        lock_type = {"movies": "free_telecharger_movie", "series": "free_telecharger_series", "anime": "free_telecharger_anime"}[content_type]

        if settings.CONTENT_CACHE_MODE == "live":
            cached_results = await get_cache(database, cache_type, title, year)

            if cached_results is not None:
                asyncio.create_task(self._background_refresh_free_telecharger(cache_type, scraper, title, year, metadata))
                return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

            async with SearchLock(lock_type, title, year):
                cached_results = await get_cache(database, cache_type, title, year)
                if cached_results is not None:
                    return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

                results = await scraper.search(title, year, metadata)

                if results:
                    await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)

                return self._filter_episode_results(results, season, episode, content_type, metadata)

        async with SearchLock(lock_type, title, year):
            cached_results = await get_cache(database, cache_type, title, year)
            if cached_results is not None:
                stream_logger.debug(f"Using cached results for {content_type}")
                return self._filter_episode_results(cached_results, season, episode, content_type, metadata)

            results = await scraper.search(title, year, metadata)

            if results:
                await set_cache(
                    database, cache_type, title, year,
                    results, settings.CONTENT_CACHE_TTL
                )

            return self._filter_episode_results(results, season, episode, content_type, metadata)

    async def _background_refresh_darki_api(self, cache_type: str, scraper, title: str,
                                            year: Optional[str], metadata: Optional[Dict] = None,
                                            config: Optional[Dict] = None) -> None:
        try:
            stream_logger.debug(f"Background refresh: {cache_type} {title} ({year})")
            results = await scraper.search(title, year, metadata, config)
            if results:
                await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)
                stream_logger.debug(f"Background refresh done: {len(results)} results")
        except Exception as e:
            stream_logger.error(f"Background refresh failed: {type(e).__name__}")

    async def _search_darki_api_with_cache(self, content_type: str, scraper, title: str,
                                           year: Optional[str], metadata: Optional[Dict] = None, config: Optional[Dict] = None) -> List[Dict]:
        cache_types = {"movies": "darki_api_movie"}
        cache_type = cache_types.get(content_type, f"darki_api_{content_type}")

        lock_type = f"darki_api_{content_type}"

        if settings.CONTENT_CACHE_MODE == "live":
            cached_results = await get_cache(database, cache_type, title, year)

            if cached_results is not None:
                asyncio.create_task(self._background_refresh_darki_api(cache_type, scraper, title, year, metadata, config))
                return cached_results

            async with SearchLock(lock_type, title, year):
                cached_results = await get_cache(database, cache_type, title, year)
                if cached_results is not None:
                    return cached_results

                results = await scraper.search(title, year, metadata, config)

                if results:
                    await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)

                return results

        async with SearchLock(lock_type, title, year):
            cached_results = await get_cache(database, cache_type, title, year)
            if cached_results is not None:
                stream_logger.debug(f"Using cached results for {content_type}")
                return cached_results

            results = await scraper.search(title, year, metadata, config)

            if results:
                await set_cache(
                    database, cache_type, title, year,
                    results, settings.CONTENT_CACHE_TTL
                )

            return results

    async def _background_refresh_darki_api_episode(self, cache_type: str, scraper, title: str,
                                                    year: Optional[str], metadata: Optional[Dict] = None,
                                                    season: Optional[str] = None, episode: Optional[str] = None,
                                                    config: Optional[Dict] = None) -> None:
        try:
            stream_logger.debug(f"Background refresh: {cache_type} {title} ({year}) S{season}E{episode}")
            results = await scraper.search(title, year, metadata, season, episode, config)
            if results:
                await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)
                stream_logger.debug(f"Background refresh done: {len(results)} results")
        except Exception as e:
            stream_logger.error(f"Background refresh failed: {type(e).__name__}")

    async def _search_darki_api_with_episode_cache(self, content_type: str, scraper, title: str,
                                                   year: Optional[str], metadata: Optional[Dict] = None,
                                                   season: Optional[str] = None, episode: Optional[str] = None, config: Optional[Dict] = None) -> List[Dict]:
        if not season or not episode:
            try:
                return await scraper.search(title, year, metadata, season, episode, config)
            except Exception as e:
                scraper_logger.error(f"Darki-API search failed: {type(e).__name__}")
                return []

        base_types = {"series": "series", "anime": "anime"}
        base_type = base_types.get(content_type, content_type)
        cache_type = f"darki_api_{base_type}_s{season}e{episode}"

        lock_type = f"darki_api_{base_type}"

        if settings.CONTENT_CACHE_MODE == "live":
            cached_results = await get_cache(database, cache_type, title, year)

            if cached_results is not None:
                asyncio.create_task(self._background_refresh_darki_api_episode(cache_type, scraper, title, year, metadata, season, episode, config))
                return cached_results

            async with SearchLock(lock_type, title, year):
                cached_results = await get_cache(database, cache_type, title, year)
                if cached_results is not None:
                    return cached_results

                results = await scraper.search(title, year, metadata, season, episode, config)

                if results:
                    await set_cache(database, cache_type, title, year, results, settings.CONTENT_CACHE_TTL)

                return results

        async with SearchLock(lock_type, title, year):
            cached_results = await get_cache(database, cache_type, title, year)
            if cached_results is not None:
                stream_logger.debug(f"Using cached results for {content_type} S{season}E{episode}")
                return cached_results

            results = await scraper.search(title, year, metadata, season, episode, config)

            if results:
                await set_cache(
                    database, cache_type, title, year,
                    results, settings.CONTENT_CACHE_TTL
                )

            return results

    async def _search_darki_api_with_kitsu_direct_mapping(
        self,
        title: str,
        year: Optional[str],
        metadata: Dict,
        absolute_episode: int,
        config: Optional[Dict] = None
    ) -> List[Dict]:
        try:
            darki_api_kitsu_metadata = {
                "titles": metadata.get("titles", [title]),
                "year": year
            }

            metadata_logger.debug("Kitsu→Darki: searching anime")

            darki_api_scraper = BaseDarkiAPI()
            search_titles = darki_api_kitsu_metadata.get("titles", [title])
            darki_api_result = await darki_api_scraper.search_by_titles(search_titles, darki_api_kitsu_metadata)

            if not darki_api_result:
                metadata_logger.debug("Kitsu→Darki: anime not found")
                return []

            title_id = darki_api_result.get("id")

            if not title_id:
                metadata_logger.error("Kitsu→Darki: no title ID")
                return []

            metadata_logger.debug(f"Kitsu→Darki: mapping episode {absolute_episode}")

            tmdb_api_token = config.get("tmdb_api_token") if config else None

            darki_mapping = await darki_api_scraper.map_kitsu_absolute_to_darki_season(
                title_id, absolute_episode, tmdb_api_token
            )

            if not darki_mapping:
                metadata_logger.error("Kitsu→Darki: mapping failed")
                return []

            darki_season, darki_episode = darki_mapping

            metadata_logger.debug(f"Kitsu→Darki: S{darki_season}E{darki_episode}")

            return await self._search_darki_api_with_episode_cache(
                "anime", darki_api_anime_scraper, title, year,
                darki_api_kitsu_metadata, darki_season, darki_episode, config
            )

        except Exception as e:
            metadata_logger.error(f"Kitsu→Darki error: {type(e).__name__}")
            return []

    def _season_episode_to_absolute(self, season: int, episode: int, seasons_data: List[Dict]) -> Optional[int]:
        if not seasons_data:
            return None

        absolute = 0
        for s in seasons_data:
            s_num = s.get("number", 0)
            ep_count = s.get("episode_count", 0)

            if s_num < season:
                absolute += ep_count
            elif s_num == season:
                return absolute + episode

        return None

    def _filter_episode_results(self, results: List[Dict], season: Optional[str],
                                episode: Optional[str], content_type: str,
                                metadata: Optional[Dict] = None) -> List[Dict]:
        if not results or not season or not episode:
            return results

        seasons_data = None
        if metadata:
            seasons_data = metadata.get("seasons")

        if seasons_data:
            try:
                target_absolute = self._season_episode_to_absolute(
                    int(season), int(episode), seasons_data
                )

                if target_absolute:
                    filtered = []
                    for r in results:
                        r_season = r.get("season")
                        r_episode = r.get("episode")

                        if r_season and r_episode:
                            r_absolute = self._season_episode_to_absolute(
                                int(r_season), int(r_episode), seasons_data
                            )
                            if r_absolute == target_absolute:
                                filtered.append(r)

                    stream_logger.debug(f"Absolute filtered S{season}E{episode} (abs:{target_absolute}): {len(filtered)} results")
                    return filtered

            except (ValueError, TypeError):
                pass

        if content_type == "anime":
            season_str = str(season) if season is not None else None
            episode_str = str(episode) if episode is not None else None
            filtered = [
                r for r in results
                if r.get("season") == season_str and r.get("episode") == episode_str
            ]
        else:
            filtered = [
                r for r in results
                if r.get("season") == season and r.get("episode") == episode
            ]

        stream_logger.debug(f"Filtered S{season}E{episode}: {len(filtered)} results")
        return filtered

    async def _search_content_common(self, content_type: str, content_name: str,
                                     wawacity_scraper, darki_scraper, free_telecharger_scraper,
                                     title: str, year: Optional[str],
                                     metadata: Optional[Dict] = None,
                                     season: Optional[str] = None, episode: Optional[str] = None,
                                     config: Dict = None, use_episode_cache: bool = False) -> List[Dict]:
        supported_sources = self._get_supported_sources(config) if config else settings.ALLDEBRID_SUPPORTED_SOURCES

        tasks = []
        if "wawacity" in supported_sources:
            if use_episode_cache:
                tasks.append(self._search_wawacity_with_cache(content_type, wawacity_scraper, title, year, metadata, season, episode))
            else:
                tasks.append(self._search_wawacity_with_cache(content_type, wawacity_scraper, title, year, metadata))

        if "free-telecharger" in supported_sources:
            if use_episode_cache:
                tasks.append(self._search_free_telecharger_with_cache(content_type, free_telecharger_scraper, title, year, metadata, season, episode))
            else:
                tasks.append(self._search_free_telecharger_with_cache(content_type, free_telecharger_scraper, title, year, metadata))

        if "darki-api" in supported_sources:
            if use_episode_cache:
                tasks.append(self._search_darki_api_with_episode_cache(content_type, darki_scraper, title, year, metadata, season, episode, config))
            else:
                tasks.append(self._search_darki_api_with_cache(content_type, darki_scraper, title, year, metadata, config))

        if not tasks:
            stream_logger.debug(f"No supported sources configured for {content_name}")
            return []

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for result in results_list:
            if isinstance(result, list):
                all_results.extend(result)
            elif isinstance(result, Exception):
                stream_logger.error(f"{content_name.title()} search failed: {result}")

        return all_results

    async def _search_movie(self, title: str, year: Optional[str], metadata: Optional[Dict] = None, config: Dict = None) -> List[Dict]:
        return await self._search_content_common("movies", "movie", movie_scraper, darki_api_movie_scraper,
                                                 free_telecharger_movie_scraper, title, year, metadata, None, None, config, use_episode_cache=False)

    async def _search_anime(self, title: str, year: Optional[str],
                            season: Optional[str], episode: Optional[str], metadata: Optional[Dict] = None, config: Dict = None) -> List[Dict]:
        return await self._search_content_common("anime", "anime", anime_scraper, darki_api_anime_scraper,
                                                 free_telecharger_anime_scraper, title, year, metadata, season, episode, config, use_episode_cache=True)

    async def _search_series(self, title: str, year: Optional[str],
                             season: Optional[str], episode: Optional[str], metadata: Optional[Dict] = None, config: Dict = None) -> List[Dict]:
        return await self._search_content_common("series", "series", series_scraper, darki_api_series_scraper,
                                                 free_telecharger_series_scraper, title, year, metadata, season, episode, config, use_episode_cache=True)

    async def resolve_link(self, link: str, config: Dict, season: Optional[str] = None, episode: Optional[str] = None, service: Optional[str] = None) -> Optional[str]:
        if service:
            debrid_service = self._get_debrid_service(service)
            debrid_api_key = get_debrid_api_key(config, service)
        else:
            debrid_services = get_debrid_services(config)
            if debrid_services:
                first_service = debrid_services[0]
                service = first_service.get("service", "alldebrid")
                debrid_service = self._get_debrid_service(service)
                debrid_api_key = first_service.get("api_key", "")
            else:
                debrid_service = alldebrid_service
                debrid_api_key = ""

        result = await debrid_service.convert_link(link, debrid_api_key, season, episode)

        if result == "LINK_DOWN":
            await mark_dead_link(link, settings.DEAD_LINK_TTL)

        return result

    async def resolve_link_with_response(self, link: str, config: Dict, season: Optional[str] = None, episode: Optional[str] = None, service: Optional[str] = None):
        direct_link = await self.resolve_link(link, config, season, episode, service)

        if direct_link and direct_link not in ["LINK_DOWN", "RETRY_ERROR", "FATAL_ERROR", "LINK_UNCACHED"]:
            return RedirectResponse(url=direct_link, status_code=302)
        elif direct_link == "LINK_DOWN":
            return FileResponse("wastream/public/link_down.mp4")
        elif direct_link == "LINK_UNCACHED":
            return FileResponse("wastream/public/uncached.mp4")
        elif direct_link == "RETRY_ERROR":
            return FileResponse("wastream/public/retry_error.mp4")
        else:
            return FileResponse("wastream/public/fatal_error.mp4")

    async def _handle_kitsu_request(self, media_info: Dict, config: Dict, base_url: str, start_time: float) -> List[Dict]:
        kitsu_id = media_info.get("kitsu_id")
        episode = media_info.get("episode")

        if not kitsu_id:
            stream_logger.error("Empty Kitsu ID")
            return []

        kitsu_metadata = await kitsu_service.get_metadata(kitsu_id)
        if not kitsu_metadata:
            stream_logger.error(f"Kitsu metadata failed: {kitsu_id}")
            return []

        if kitsu_metadata.get("subtype") == "movie":
            search_title = kitsu_metadata["title"]
            search_year = kitsu_metadata.get("year")

            enhanced_kitsu_metadata = {
                "titles": kitsu_metadata.get("search_titles", [kitsu_metadata["title"]]),
                "all_titles": kitsu_metadata.get("all_titles", [kitsu_metadata["title"]]),
                "year": search_year,
                "type": "movie",
                "content_type": "movies"
            }

            results = await self._search_movie(search_title, search_year, enhanced_kitsu_metadata, config)

            if not results:
                stream_logger.debug(f"No content: Kitsu {kitsu_metadata['title']}")
                return []

            results = deduplicate_and_sort_results(results, quality_sort_key)

            results = apply_all_filters(results, config)

            elapsed = time.time() - start_time
            timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT)
            remaining_time = max(0, timeout - elapsed)

            debrid_services = get_debrid_services(config)
            enriched_results = await self._check_cache_and_enrich(
                results, debrid_services, config, remaining_time, None, None
            )

            streams = await self._format_streams(
                enriched_results,
                config,
                base_url,
                None,
                None,
                kitsu_metadata.get("year")
            )

            streams = filter_archive_files(streams)

        else:
            actual_season = None
            actual_episode = None
            base_metadata = None
            search_title = kitsu_metadata["title"]
            search_year = kitsu_metadata.get("year")

            if episode:
                actual_season, actual_episode, season_mapping, base_title, base_year, base_metadata = await kitsu_service.get_season_chain_and_mapping(
                    kitsu_id,
                    int(episode)
                )
                if base_title:
                    search_title = base_title
                if base_year:
                    search_year = base_year

            if base_metadata:
                enhanced_kitsu_metadata = {
                    "titles": base_metadata.get("search_titles", [base_metadata["title"]]),
                    "all_titles": base_metadata.get("all_titles", [base_metadata["title"]]),
                    "year": search_year,
                    "type": "anime",
                    "content_type": "anime"
                }
            else:
                enhanced_kitsu_metadata = {
                    "titles": [search_title] + kitsu_metadata.get("aliases", []),
                    "year": search_year,
                    "type": "anime",
                    "content_type": "anime"
                }

            supported_sources = self._get_supported_sources(config) if config else settings.ALLDEBRID_SUPPORTED_SOURCES

            tasks = []
            if "wawacity" in supported_sources:
                tasks.append(self._search_wawacity_with_cache(
                    "anime", anime_scraper, search_title, search_year,
                    enhanced_kitsu_metadata, str(actual_season), str(actual_episode)
                ))

            if "free-telecharger" in supported_sources:
                tasks.append(self._search_free_telecharger_with_cache(
                    "anime", free_telecharger_anime_scraper, search_title, search_year,
                    enhanced_kitsu_metadata, str(actual_season), str(actual_episode)
                ))

            if "darki-api" in supported_sources:
                absolute_ep = season_mapping.get("absolute_episode", actual_episode) if season_mapping else actual_episode

                tasks.append(self._search_darki_api_with_kitsu_direct_mapping(
                    search_title, search_year, enhanced_kitsu_metadata,
                    absolute_ep, config
                ))

            if not tasks:
                stream_logger.error("No supported sources")
                return []

            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            results = []
            for result in results_list:
                if isinstance(result, list):
                    results.extend(result)
                elif isinstance(result, Exception):
                    stream_logger.error(f"Kitsu search failed: {result}")

            if not results:
                stream_logger.debug(f"No content: Kitsu {kitsu_metadata['title']}")
                return []

            results = deduplicate_and_sort_results(results, quality_sort_key)

            results = apply_all_filters(results, config)

            elapsed = time.time() - start_time
            timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT)
            remaining_time = max(0, timeout - elapsed)

            debrid_services = get_debrid_services(config)
            enriched_results = await self._check_cache_and_enrich(
                results, debrid_services, config, remaining_time,
                str(actual_season) if actual_season else None,
                str(actual_episode) if actual_episode else None
            )

            streams = await self._format_streams(
                enriched_results,
                config,
                base_url,
                None,
                None,
                search_year
            )

            streams = filter_archive_files(streams)

        excluded_keywords = config.get("excluded_keywords", [])
        if excluded_keywords:
            filtered_streams = filter_excluded_keywords(streams, excluded_keywords)
            excluded_count = len(streams) - len(filtered_streams)
            if excluded_count > 0:
                stream_logger.debug(f"Excluded {excluded_count} streams")
            return filtered_streams

        return streams


# ===========================
# Singleton Instance
# ===========================
stream_service = StreamService()
