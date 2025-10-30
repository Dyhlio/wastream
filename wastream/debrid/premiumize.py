import asyncio
import time
from asyncio import sleep
from typing import Optional, List, Dict

from wastream.core.config import settings
from wastream.debrid.base import BaseDebridService, HTTP_RETRY_ERRORS
from wastream.utils.http_client import http_client
from wastream.utils.logger import debrid_logger, cache_logger
from wastream.utils.quality import quality_sort_key

# ===========================
# Premiumize Error Constants
# ===========================
RETRY_MESSAGES = [
    "Fair use limit reached!",
    "maximum of 25 active downloads"
]

LINK_DOWN_MESSAGES = [
    "not found",
    "not available",
    "offline"
]

# ===========================
# Premiumize Service Class
# ===========================
class PremiumizeService(BaseDebridService):
    def get_service_name(self) -> str:
        return "Premiumize"

    def _handle_api_error(
        self,
        message: str,
        attempt: int
    ) -> str:
        message_lower = message.lower()

        if any(kw in message_lower for kw in LINK_DOWN_MESSAGES):
            debrid_logger.debug(f"LINK_DOWN: {message}")
            return "LINK_DOWN"

        if any(kw in message for kw in RETRY_MESSAGES):
            debrid_logger.error(f"RETRY: {message}")
            if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                return "RETRY_ERROR"
            return "RETRY"

        debrid_logger.error(f"Fatal: {message}")
        return "FATAL_ERROR"

    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float, user_season: Optional[str] = None, user_episode: Optional[str] = None) -> List[Dict]:
        start_time = time.time()

        if not api_key or not results:
            for result in results:
                result["cache_status"] = "uncached"
            return results

        initial_count = len(results)
        filtered_results = []
        for result in results:
            if result.get("source") != "Darki-API":
                continue
            if result.get("model_type") == "nzb":
                continue
            hoster = result.get("hoster", "").lower()
            if any(supported_host in hoster for supported_host in settings.PREMIUMIZE_SUPPORTED_HOSTS):
                filtered_results.append(result)

        if len(filtered_results) < initial_count:
            debrid_logger.debug(f"Filtered: {initial_count} → {len(filtered_results)} links (Premiumize: Darki-API only, DDL only)")

        if not filtered_results:
            debrid_logger.debug("No supported hosts")
            return []

        results = filtered_results

        for result in results:
            result["cache_status"] = "cached"

        groups = self.group_identical_links(results)

        cached_results = []
        for group_key, group_links in groups.items():
            cached_results.append(group_links[0])

        cached_results.sort(key=quality_sort_key)

        elapsed = time.time() - start_time
        cache_logger.debug(f"Done in {elapsed:.1f}s: {len(cached_results)} results (all marked cached)")

        return cached_results

    async def convert_link(self, link: str, api_key: str, season: Optional[str] = None, episode: Optional[str] = None) -> Optional[str]:
        if not api_key:
            debrid_logger.error("Empty API key")
            return "FATAL_ERROR"

        debrid_logger.debug(f"Converting: {link}")

        http_error_count = 0

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:
                response = await http_client.get(
                    f"{settings.PREMIUMIZE_API_URL}/transfer/directdl",
                    params={"apikey": api_key, "src": link},
                    timeout=settings.HTTP_TIMEOUT
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response, http_error_count, "PREMIUMIZE",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif response.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"Max HTTP retries ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
                    return "RETRY_ERROR"

                http_error_count = 0

                if response.status_code == 401:
                    debrid_logger.error("Invalid API key (401)")
                    return "FATAL_ERROR"

                if response.status_code == 402:
                    debrid_logger.error("Account not premium (402)")
                    return "FATAL_ERROR"

                if response.status_code == 404:
                    debrid_logger.error("Endpoint not found (404)")
                    return "FATAL_ERROR"

                if response.status_code != 200:
                    debrid_logger.error(f"HTTP {response.status_code}")
                    if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                        return "FATAL_ERROR"
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                data = response.json()

                if data.get("status") != "success":
                    message = data.get("message", "Unknown error")

                    api_error_result = self._handle_api_error(message, attempt)
                    if api_error_result == "LINK_DOWN":
                        return "LINK_DOWN"
                    elif api_error_result == "FATAL_ERROR":
                        return "FATAL_ERROR"
                    elif api_error_result == "RETRY_ERROR":
                        return "RETRY_ERROR"
                    elif api_error_result == "RETRY":
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue

                direct_link = data.get("content", [{}])[0].get("link") if data.get("content") else data.get("location")

                if direct_link:
                    debrid_logger.debug("Converted")
                    return direct_link
                else:
                    debrid_logger.error("No direct link in response")
                    if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                        return "FATAL_ERROR"
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

            except Exception as e:
                debrid_logger.error(f"Attempt {attempt + 1} failed: {type(e).__name__}")
                if attempt < settings.DEBRID_MAX_RETRIES - 1:
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

        debrid_logger.error(f"Failed after {settings.DEBRID_MAX_RETRIES} attempts")
        return "FATAL_ERROR"

# ===========================
# Singleton Instance
# ===========================
premiumize_service = PremiumizeService()
