from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from asyncio import sleep
from wastream.utils.logger import debrid_logger, cache_logger

# ===========================
# Constants
# ===========================
HTTP_RETRY_ERRORS = [429, 500, 502, 503, 504]

# ===========================
# Base Debrid Service Class
# ===========================
class BaseDebridService(ABC):

    @abstractmethod
    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float = 0, user_season: Optional[str] = None, user_episode: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    async def convert_link(self, link: str, api_key: str, season: Optional[str] = None, episode: Optional[str] = None) -> Optional[str]:
        pass

    @abstractmethod
    def get_service_name(self) -> str:
        pass

    async def _handle_http_retry_error(
        self,
        response,
        http_error_count: int,
        service_name: str,
        retry_delay: int,
        max_retries: int
    ) -> Tuple[bool, int]:
        if response.status_code not in HTTP_RETRY_ERRORS:
            return (False, http_error_count)

        http_error_count += 1
        if http_error_count >= max_retries:
            debrid_logger.error(f"HTTP {response.status_code} - Max retries")
            return (False, http_error_count)

        debrid_logger.debug(f"HTTP {response.status_code} - Retry {http_error_count}/{max_retries}")
        await sleep(retry_delay)
        return (True, http_error_count)

    def group_identical_links(self, results: List[Dict]) -> Dict[str, List[Dict]]:
        groups = {}

        for result in results:
            group_key = (
                result.get("quality", "Unknown"),
                result.get("language", "Unknown"),
                result.get("size", "Unknown"),
                result.get("display_name", "Unknown"),
                result.get("year", ""),
                result.get("source", "Unknown")
            )

            if group_key not in groups:
                groups[group_key] = []

            groups[group_key].append(result)

        cache_logger.debug(f"Grouped {len(results)} links into {len(groups)} groups")
        return groups
