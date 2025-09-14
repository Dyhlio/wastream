from typing import List, Dict, Optional
from wastream.services.tmdb import tmdb_service
from wastream.services.alldebrid import alldebrid_service
from wastream.services.kitsu import kitsu_service
from wastream.scrapers.movie import movie_scraper
from wastream.scrapers.series import series_scraper
from wastream.scrapers.anime import anime_scraper
from wastream.utils.database import SearchLock, is_dead_link, mark_dead_link, database
from wastream.utils.cache import get_cache, set_cache
from wastream.utils.validators import extract_media_info
from wastream.utils.helpers import encode_config_to_base64, quote_url_param
from wastream.utils.logger import logger
from wastream.core.config import CONTENT_CACHE_TTL, DEAD_LINK_TTL, ADDON_NAME

# Main streaming service
class StreamService:
    
    async def get_streams(self, content_type: str, content_id: str, 
                         config: Dict, base_url: str) -> List[Dict]:
        media_info = extract_media_info(content_id, content_type)
        
        
        if media_info.get("kitsu_id"):
            return await self._handle_kitsu_request(media_info, config, base_url)
        
        metadata = await self._get_metadata(
            media_info["imdb_id"], 
            config.get("tmdb", "")
        )
        
        if not metadata:
            logger.log("STREAM", f"ERROR: Failed to fetch TMDB metadata for {media_info['imdb_id']}")
            logger.log("STREAM", "ERROR: Check: 1) Valid IMDB ID 2) Valid TMDB Access Token 3) Network connectivity")
            return []
        
        results = await self._search_content(
            metadata["title"],
            metadata.get("year"),
            content_type,
            media_info.get("season"),
            media_info.get("episode"),
            metadata.get("enhanced")
        )
        
        if not results:
            logger.log("STREAM", f"ERROR: No content found for '{metadata['title']}' ({metadata.get('year', 'N/A')})")
            logger.log("STREAM", "ERROR: Possible causes: 1) Content not available on Wawacity 2) Search term mismatch 3) Site accessibility issues")
            return []
        
        streams = await self._format_streams(
            results,
            config,
            base_url,
            media_info.get("season"),
            media_info.get("episode"),
            metadata.get("year")
        )
        
        excluded_words = config.get("excluded_words", [])
        if excluded_words:
            filtered_streams = self._filter_excluded_words(streams, excluded_words)
            excluded_count = len(streams) - len(filtered_streams)
            if excluded_count > 0:
                logger.log("STREAM", f"Excluded {excluded_count} streams by filter")
            return filtered_streams
        
        return streams
    
    async def _get_metadata(self, imdb_id: str, tmdb_key: str) -> Optional[Dict]:
        if not tmdb_key or not tmdb_key.strip():
            logger.log("STREAM", "ERROR: No TMDB Access Token provided in config")
            return None
            
        try:
            enhanced_metadata = await tmdb_service.get_enhanced_metadata(imdb_id, tmdb_key)
            if enhanced_metadata:
                return {
                    "title": enhanced_metadata["titles"][0] if enhanced_metadata["titles"] else "",
                    "year": enhanced_metadata["year"],
                    "type": enhanced_metadata["type"],
                    "enhanced": enhanced_metadata
                }
            
            return await tmdb_service.get_metadata(imdb_id, tmdb_key)
            
        except Exception as e:
            logger.log("STREAM", f"ERROR: TMDB metadata error: {e}")
            return None
    
    async def _search_content(self, title: str, year: Optional[str], 
                             content_type: str, season: Optional[str], 
                             episode: Optional[str], metadata: Optional[Dict] = None) -> List[Dict]:
        if metadata and metadata.get("content_type") == "mangas":
            return await self._search_anime(title, year, season, episode, metadata)
        elif content_type == "series":
            return await self._search_series(title, year, season, episode, metadata)
        else:
            return await self._search_movie(title, year, metadata)
    
    async def _search_with_cache(self, content_type: str, scraper, title: str, 
                                year: Optional[str], metadata: Optional[Dict] = None,
                                season: Optional[str] = None, episode: Optional[str] = None) -> List[Dict]:
        cache_types = {"films": "film", "series": "serie", "mangas": "anime"}
        cache_type = cache_types.get(content_type, content_type)
        
        async with SearchLock(cache_type, title, year):
            cached_results = await get_cache(database, cache_type, title, year)
            if cached_results is not None:
                return self._filter_episode_results(cached_results, season, episode, content_type)
            
            results = await scraper.search(title, year, metadata)
            
            if results:
                await set_cache(
                    database, cache_type, title, year, 
                    results, CONTENT_CACHE_TTL
                )
            
            return self._filter_episode_results(results, season, episode, content_type)
    
    def _filter_episode_results(self, results: List[Dict], season: Optional[str], 
                               episode: Optional[str], content_type: str) -> List[Dict]:
        if not results or not season or not episode:
            return results
        
        if content_type == "mangas":
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
        
        logger.log("STREAM", f"Filtered S{season}E{episode}: {len(filtered)} results")
        return filtered
    
    async def _search_movie(self, title: str, year: Optional[str], metadata: Optional[Dict] = None) -> List[Dict]:
        return await self._search_with_cache("films", movie_scraper, title, year, metadata)
    
    async def _search_anime(self, title: str, year: Optional[str], 
                           season: Optional[str], episode: Optional[str], metadata: Optional[Dict] = None) -> List[Dict]:
        return await self._search_with_cache("mangas", anime_scraper, title, year, metadata, season, episode)
    
    async def _search_series(self, title: str, year: Optional[str], 
                            season: Optional[str], episode: Optional[str], metadata: Optional[Dict] = None) -> List[Dict]:
        return await self._search_with_cache("series", series_scraper, title, year, metadata, season, episode)
    
    async def _format_streams(self, results: List[Dict], config: Dict, 
                             base_url: str, season: Optional[str], 
                             episode: Optional[str], year: Optional[str]) -> List[Dict]:
        streams = []
        dead_links_count = 0
        
        for res in results:
            dl_link = res.get("dl_protect")
            if not dl_link:
                continue
            
            if await is_dead_link(dl_link):
                dead_links_count += 1
                continue
            
            quality = res.get("quality", "N/A")
            language = res.get("language", "N/A")
            hoster = res.get("hoster", "N/A")
            size = res.get("size", "N/A")
            display_name = res.get("display_name", "N/A")
            ep = res.get("episode", "")
            seas = res.get("season", "")
            
            q_link = quote_url_param(dl_link)
            config_b64 = encode_config_to_base64(config)
            q_b64config = quote_url_param(config_b64)
            
            playback_url = f"{base_url}/resolve?link={q_link}&b64config={q_b64config}"
            
            stream_name = f"[AD 🌇] {ADDON_NAME}"
            
            description_parts = []
            if language and language != "N/A":
                description_parts.append(f"🌐 {language}")
            if quality and quality != "N/A":
                description_parts.append(f"🎞️ {quality}")
            if hoster and hoster != "N/A":
                description_parts.append(f"☁️ {hoster}")
            
            size_year_parts = []
            if size and size != "N/A":
                size_year_parts.append(f"📦 {size}")
            if year:
                size_year_parts.append(f"📅 {year}")
            if size_year_parts:
                description_parts.append(" ".join(size_year_parts))
            
            if display_name and display_name != "N/A":
                description_parts.append(f"📁 {display_name}")
            
            streams.append({
                "name": stream_name,
                "description": "\r\n".join(description_parts),
                "url": playback_url
            })
        
        if dead_links_count > 0:
            logger.log("STREAM", f"Skipped {dead_links_count} dead links")
        
        logger.log("STREAM", f"Returning {len(streams)} stream(s)")
        return streams
    
    async def resolve_link(self, dl_protect_link: str, apikey: str) -> Optional[str]:
        result = await alldebrid_service.convert_link(dl_protect_link, apikey)
        
        if result == "LINK_DOWN":
            await mark_dead_link(dl_protect_link, DEAD_LINK_TTL)
        
        return result
    
    def _filter_excluded_words(self, streams: List[Dict], excluded_words: List[str]) -> List[Dict]:
        if not excluded_words:
            return streams
        
        filtered_streams = []
        
        for stream in streams:
            stream_name = stream.get("name", "").lower()
            stream_desc = stream.get("description", "").lower()
            stream_text = f"{stream_name} {stream_desc}"
            
            exclude_stream = False
            for word in excluded_words:
                if word.lower() in stream_text:
                    exclude_stream = True
                    break
            
            if not exclude_stream:
                filtered_streams.append(stream)
        
        return filtered_streams
    
    async def _handle_kitsu_request(self, media_info: Dict, config: Dict, base_url: str) -> List[Dict]:
        kitsu_id = media_info.get("kitsu_id")
        episode = media_info.get("episode")
        
        if not kitsu_id:
            logger.log("STREAM", "ERROR: Empty Kitsu ID in media_info")
            return []
        
        kitsu_metadata = await kitsu_service.get_metadata(kitsu_id)
        if not kitsu_metadata:
            logger.log("STREAM", f"ERROR: Failed to fetch Kitsu metadata for ID {kitsu_id}")
            logger.log("STREAM", "ERROR: Check: 1) Valid Kitsu ID 2) Network connectivity")
            return []
        
        if kitsu_metadata.get("subtype") == "movie":
            search_title = kitsu_metadata["title"]
            search_year = kitsu_metadata.get("year")
            
            enhanced_kitsu_metadata = {
                "titles": kitsu_metadata.get("search_titles", [kitsu_metadata["title"]]),
                "all_titles": kitsu_metadata.get("all_titles", [kitsu_metadata["title"]]),
                "year": search_year,
                "type": "movie",
                "content_type": "films"
            }
            
            results = await self._search_movie(search_title, search_year, enhanced_kitsu_metadata)
            
            if not results:
                logger.log("STREAM", f"ERROR: No content found for Kitsu movie '{kitsu_metadata['title']}' (ID: {kitsu_id})")
                return []
            
            streams = await self._format_streams(
                results,
                config,
                base_url,
                None,
                None,
                kitsu_metadata.get("year")
            )
            
        else:
            actual_season = None
            actual_episode = None
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
                    "content_type": "mangas"
                }
            else:
                enhanced_kitsu_metadata = {
                    "titles": [search_title] + kitsu_metadata.get("aliases", []),
                    "year": search_year,
                    "type": "anime",
                    "content_type": "mangas"
                }
            
            results = await self._search_anime(
                search_title,
                search_year, 
                actual_season,
                actual_episode,
                enhanced_kitsu_metadata
            )
            
            if not results:
                logger.log("STREAM", f"ERROR: No content found for Kitsu anime '{kitsu_metadata['title']}' (ID: {kitsu_id})")
                return []
            
            
            streams = await self._format_streams(
                results,
                config,
                base_url,
                None,
                None,
                kitsu_metadata.get("year")
            )
        
        excluded_words = config.get("excluded_words", [])
        if excluded_words:
            filtered_streams = self._filter_excluded_words(streams, excluded_words)
            excluded_count = len(streams) - len(filtered_streams)
            if excluded_count > 0:
                logger.log("STREAM", f"Excluded {excluded_count} streams by filter")
            return filtered_streams
        
        return streams

stream_service = StreamService()