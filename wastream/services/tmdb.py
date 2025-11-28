from typing import Optional, Dict
from wastream.utils.http_client import http_client
from wastream.config.settings import settings
from wastream.utils.logger import metadata_logger

# ===========================
# TMDB Service Class
# ===========================
class TMDBService:

    BASE_URL = settings.TMDB_API_URL

    async def get_enhanced_metadata(self, imdb_id: str, tmdb_api_token: str) -> Optional[Dict]:
        if not tmdb_api_token or not tmdb_api_token.strip():
            metadata_logger.error("Empty TMDB token")
            return None

        metadata_logger.debug(f"Fetching TMDB: {imdb_id}")

        headers = {
            "Authorization": f"Bearer {tmdb_api_token}",
            "Content-Type": "application/json",
        }

        try:
            find_url = f"{self.BASE_URL}/find/{imdb_id}?external_source=imdb_id"
            response = await http_client.get(find_url, headers=headers, timeout=settings.METADATA_TIMEOUT)

            if response.status_code != 200:
                metadata_logger.error(f"TMDB API {response.status_code}")
                return None

            data = response.json()

            if data.get("movie_results"):
                metadata_logger.debug(f"Found {len(data['movie_results'])} movie results")
                movie = data["movie_results"][0]
                movie_id = movie["id"]

                details_url = f"{self.BASE_URL}/movie/{movie_id}?append_to_response=translations"
                details_response = await http_client.get(details_url, headers=headers, timeout=settings.METADATA_TIMEOUT)

                if details_response.status_code != 200:
                    metadata_logger.error(f"TMDB movie details API {details_response.status_code}")
                    return None

                if details_response.status_code == 200:
                    details = details_response.json()

                    titles = []

                    if details.get("title"):
                        titles.append(details["title"].lower())
                    if details.get("original_title") and details["original_title"].lower() not in titles:
                        titles.append(details["original_title"].lower())

                    if details.get("translations", {}).get("translations"):
                        for trans in details["translations"]["translations"]:
                            if trans.get("iso_639_1") == "fr" and trans.get("data", {}).get("title"):
                                fr_title = trans["data"]["title"].lower()
                                if fr_title not in titles:
                                    titles.append(fr_title)
                                    metadata_logger.debug(f"Added French title: {fr_title}")

                    year = movie.get("release_date", "").split("-")[0]

                    metadata_logger.debug(f"TMDB movie: {len(titles)} titles")
                    return {
                        "imdb_id": imdb_id,
                        "tmdb_id": movie_id,
                        "titles": titles,
                        "year": year,
                        "type": "movie",
                        "content_type": "movies"
                    }

            elif data.get("tv_results"):
                metadata_logger.debug(f"Found {len(data['tv_results'])} series results")
                tv_show = data["tv_results"][0]
                tv_id = tv_show["id"]

                details_url = f"{self.BASE_URL}/tv/{tv_id}?append_to_response=translations,keywords"
                details_response = await http_client.get(details_url, headers=headers, timeout=settings.METADATA_TIMEOUT)

                if details_response.status_code != 200:
                    metadata_logger.error(f"TMDB series details API {details_response.status_code}")
                    return None

                if details_response.status_code == 200:
                    details = details_response.json()

                    titles = []

                    if details.get("name"):
                        titles.append(details["name"].lower())
                    if details.get("original_name") and details["original_name"].lower() not in titles:
                        titles.append(details["original_name"].lower())

                    if details.get("translations", {}).get("translations"):
                        for trans in details["translations"]["translations"]:
                            if trans.get("iso_639_1") == "fr" and trans.get("data", {}).get("name"):
                                fr_name = trans["data"]["name"].lower()
                                if fr_name not in titles:
                                    titles.append(fr_name)
                                    metadata_logger.debug(f"Added French title: {fr_name}")

                    year = tv_show.get("first_air_date", "").split("-")[0]

                    content_type = "series"
                    genre_ids = tv_show.get("genre_ids", [])

                    if 16 in genre_ids:
                        keywords = details.get("keywords", {}).get("results", [])
                        keyword_ids = [kw.get("id") for kw in keywords]

                        if 210024 in keyword_ids:
                            content_type = "anime"

                    metadata_logger.debug(f"TMDB series: {len(titles)} titles ({content_type})")
                    return {
                        "imdb_id": imdb_id,
                        "tmdb_id": tv_id,
                        "titles": titles,
                        "year": year,
                        "type": "series",
                        "content_type": content_type
                    }

            metadata_logger.debug(f"No TMDB metadata: {imdb_id}")
            return None

        except Exception as e:
            metadata_logger.error(f"TMDB metadata fetch error: {type(e).__name__}")
            return None

    async def get_metadata(self, imdb_id: str, tmdb_api_token: str) -> Optional[Dict]:
        enhanced = await self.get_enhanced_metadata(imdb_id, tmdb_api_token)
        if enhanced:
            return {
                "title": enhanced["titles"][0] if enhanced["titles"] else "",
                "year": enhanced["year"],
                "type": enhanced["type"]
            }
        return None

    async def get_seasons_episode_count(self, imdb_id: str, tmdb_api_token: str) -> Optional[Dict]:
        if not tmdb_api_token or not tmdb_api_token.strip():
            metadata_logger.error("Empty TMDB token")
            return None

        metadata_logger.debug(f"Fetching TMDB seasons: {imdb_id}")

        headers = {
            "Authorization": f"Bearer {tmdb_api_token}",
            "Content-Type": "application/json",
        }

        try:
            find_url = f"{self.BASE_URL}/find/{imdb_id}?external_source=imdb_id"
            response = await http_client.get(find_url, headers=headers, timeout=settings.METADATA_TIMEOUT)

            if response.status_code != 200:
                return None

            data = response.json()
            if not data.get("tv_results"):
                return None

            tv_id = data["tv_results"][0]["id"]

            details_url = f"{self.BASE_URL}/tv/{tv_id}"
            details_response = await http_client.get(details_url, headers=headers, timeout=settings.METADATA_TIMEOUT)

            if details_response.status_code != 200:
                return None

            details = details_response.json()
            seasons = details.get("seasons", [])

            seasons_data = []
            for season in seasons:
                season_number = season.get("season_number", 0)
                if season_number > 0:
                    seasons_data.append({
                        "number": season_number,
                        "episode_count": season.get("episode_count", 0)
                    })

            seasons_data.sort(key=lambda s: s["number"])

            metadata_logger.debug(f"TMDB seasons: {len(seasons_data)} for {imdb_id}")

            return {
                "imdb_id": imdb_id,
                "tmdb_id": tv_id,
                "seasons": seasons_data
            }

        except Exception as e:
            metadata_logger.error(f"TMDB seasons fetch error: {type(e).__name__}")
            return None

# ===========================
# Singleton Instance
# ===========================
tmdb_service = TMDBService()
