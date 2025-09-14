from typing import Optional, Dict
from wastream.utils.http_client import http_client
from wastream.core.config import TMDB_API_URL
from wastream.utils.logger import logger

# TMDB metadata service
class TMDBService:
    
    BASE_URL = TMDB_API_URL
    
    async def get_enhanced_metadata(self, imdb_id: str, tmdb_key: str) -> Optional[Dict]:
        if not tmdb_key or not tmdb_key.strip():
            logger.log("TMDB", "ERROR: TMDB Access Token is empty")
            return None
        
        logger.log("TMDB", f"Fetching metadata for {imdb_id}")
            
        headers = {
            "Authorization": f"Bearer {tmdb_key}",
            "Content-Type": "application/json",
        }
        
        try:
            find_url = f"{self.BASE_URL}/find/{imdb_id}?external_source=imdb_id"
            response = await http_client.get(find_url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            if data.get("movie_results"):
                movie = data["movie_results"][0]
                movie_id = movie["id"]
                
                details_url = f"{self.BASE_URL}/movie/{movie_id}?append_to_response=translations"
                details_response = await http_client.get(details_url, headers=headers, timeout=10)
                
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
                    
                    
                    year = movie.get("release_date", "").split("-")[0]
                    
                    logger.log("TMDB", f"Movie metadata found for {imdb_id}: {len(titles)} titles")
                    return {
                        "titles": titles,
                        "year": year,
                        "type": "movie",
                        "content_type": "films"
                    }
            
            elif data.get("tv_results"):
                tv_show = data["tv_results"][0]
                tv_id = tv_show["id"]
                
                details_url = f"{self.BASE_URL}/tv/{tv_id}?append_to_response=translations,keywords"
                details_response = await http_client.get(details_url, headers=headers, timeout=10)
                
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
                    
                    
                    year = tv_show.get("first_air_date", "").split("-")[0]
                    
                    content_type = "series"
                    genre_ids = tv_show.get("genre_ids", [])
                    
                    if 16 in genre_ids:
                        keywords = details.get("keywords", {}).get("results", [])
                        keyword_ids = [kw.get("id") for kw in keywords]
                        
                        if 210024 in keyword_ids:
                            content_type = "mangas"
                    
                    logger.log("TMDB", f"Series metadata found for {imdb_id}: {len(titles)} titles ({content_type})")
                    return {
                        "titles": titles,
                        "year": year,
                        "type": "series",
                        "content_type": content_type
                    }
            
            logger.log("TMDB", f"No metadata found for {imdb_id}")
            return None
            
        except Exception as e:
            logger.log("TMDB", f"ERROR: Enhanced metadata fetch failed: {e}")
            return None
    
    async def get_metadata(self, imdb_id: str, tmdb_key: str) -> Optional[Dict]:
        enhanced = await self.get_enhanced_metadata(imdb_id, tmdb_key)
        if enhanced:
            return {
                "title": enhanced["titles"][0] if enhanced["titles"] else "",
                "year": enhanced["year"],
                "type": enhanced["type"]
            }
        return None

tmdb_service = TMDBService()