import time
from asyncio import sleep
from typing import Optional, List, Dict

from wastream.config.settings import settings
from wastream.debrid.base import BaseDebridService, HTTP_RETRY_ERRORS
from wastream.utils.http_client import http_client
from wastream.utils.logger import debrid_logger, cache_logger
from wastream.utils.quality import quality_sort_key


# ===========================
# 1fichier Service Class
# ===========================
class OneFichierService(BaseDebridService):
    def get_service_name(self) -> str:
        return "1fichier"

    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float, user_season: Optional[str] = None, user_episode: Optional[str] = None, user_hosts: Optional[List[str]] = None) -> List[Dict]:
        start_time = time.time()

        if not api_key or not results:
            for result in results:
                result["cache_status"] = "uncached"
            return results

        supported_hosts = user_hosts if user_hosts else settings.ONEFICHIER_SUPPORTED_HOSTS

        initial_count = len(results)
        filtered_results = []
        for result in results:
            if result.get("model_type") == "nzb":
                continue
            hoster = result.get("hoster", "").lower()
            if any(supported_host in hoster for supported_host in supported_hosts):
                filtered_results.append(result)

        if len(filtered_results) < initial_count:
            debrid_logger.debug(f"Filtered: {initial_count} -> {len(filtered_results)} links (1fichier hosts only)")

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

        cleaned_link = link
        if "&af=" in cleaned_link:
            cleaned_link = cleaned_link.split("&af=")[0]

        debrid_logger.debug(f"Converting: {cleaned_link}")

        http_error_count = 0

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:
                response = await http_client.post(
                    f"{settings.ONEFICHIER_API_URL}/download/get_token.cgi",
                    json={"url": cleaned_link, "inline": 1},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": settings.ADDON_NAME
                    },
                    timeout=settings.HTTP_TIMEOUT
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response, http_error_count, "1FICHIER",
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

                if response.status_code == 403:
                    debrid_logger.error("Premium account required (403)")
                    return "FATAL_ERROR"

                if response.status_code == 404:
                    debrid_logger.error("Link not found (404)")
                    return "LINK_DOWN"

                if response.status_code == 410:
                    debrid_logger.error("Link removed (410)")
                    return "LINK_DOWN"

                if response.status_code != 200:
                    debrid_logger.error(f"HTTP {response.status_code}")
                    if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                        return "FATAL_ERROR"
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                data = response.json()

                if data.get("status") == "KO":
                    message = data.get("message", "Unknown error")
                    debrid_logger.debug(f"LINK_DOWN: {message}")
                    return "LINK_DOWN"

                direct_link = data.get("url")

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
onefichier_service = OneFichierService()
