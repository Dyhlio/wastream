import asyncio
import hashlib
import time
from asyncio import sleep
from typing import List, Dict, Optional, Tuple

from wastream.core.config import settings
from wastream.debrid.base import BaseDebridService, HTTP_RETRY_ERRORS
from wastream.utils.http_client import http_client
from wastream.utils.logger import debrid_logger, cache_logger

# ===========================
# TorBox Error Constants
# ===========================
RETRY_ERRORS = [
    "DOWNLOAD_SERVER_ERROR",
    "NO_SERVERS_AVAILABLE_ERROR",
]

# ===========================
# TorBox Service Class
# ===========================
class TorBoxService(BaseDebridService):
    def __init__(self):
        self.API_URL = settings.TORBOX_API_URL

    def get_service_name(self) -> str:
        return "TorBox"

    async def _handle_cooldown_limit(
        self,
        error_code: str,
        http_error_count: int
    ) -> Tuple[Optional[str], int]:
        if error_code != "COOLDOWN_LIMIT":
            return (None, http_error_count)

        http_error_count += 1
        if http_error_count > settings.DEBRID_HTTP_ERROR_MAX_RETRIES:
            debrid_logger.error(f"COOLDOWN_LIMIT: Max ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
            return ("RETRY_ERROR", http_error_count)

        debrid_logger.debug(f"COOLDOWN_LIMIT: Retry {http_error_count}/{settings.DEBRID_HTTP_ERROR_MAX_RETRIES}")
        await sleep(settings.DEBRID_HTTP_ERROR_RETRY_DELAY)
        return ("RETRY", http_error_count)

    def _handle_api_error(
        self,
        error_code: str,
        detail: str,
        attempt: int
    ) -> Optional[str]:
        if error_code == "LINK_OFFLINE":
            debrid_logger.debug(f"{error_code}")
            return "LINK_DOWN"

        if error_code in RETRY_ERRORS:
            debrid_logger.error(f"{error_code}")
            if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                return "RETRY_ERROR"
            return "RETRY"

        debrid_logger.error(f"Fatal: {error_code}")
        return "FATAL_ERROR"

    def _calculate_hash(self, url: str) -> str:
        cleaned_url = url
        if "&af=" in cleaned_url:
            cleaned_url = cleaned_url.split("&af=")[0]

        return hashlib.md5(cleaned_url.encode("utf-8")).hexdigest()

    def _get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}"
        }

    async def check_cache_single_link(self, link: str, link_hash: str, api_key: str) -> Dict:
        http_error_count = 0

        while True:
            try:
                headers = self._get_headers(api_key)

                response = await http_client.get(
                    f"{self.API_URL}/webdl/checkcached",
                    params={"hash": [link_hash], "format": "object"},
                    headers=headers,
                    timeout=settings.DEBRID_CACHE_CHECK_HTTP_TIMEOUT
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response, http_error_count, "TORBOX",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif response.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"HTTP {response.status_code} - Max retries")
                    return {"status": "uncached", "original_link": link, "hash": link_hash, "http_error": True}

                if response.status_code == 401:
                    debrid_logger.error("Invalid API key (401)")
                    return {"status": "hidden", "original_link": link, "hash": link_hash}

                if response.status_code == 404:
                    debrid_logger.error("Endpoint not found (404)")
                    return {"status": "hidden", "original_link": link, "hash": link_hash}

                if response.status_code != 200:
                    debrid_logger.debug(f"HTTP {response.status_code}")
                    return {"status": "uncached", "original_link": link, "hash": link_hash}

                response_json = response.json()

                cache_data = response_json.get("data", {})
                if link_hash in cache_data:
                    cached_info = cache_data[link_hash]

                    if cached_info and isinstance(cached_info, dict):
                        filename = cached_info.get("name")
                        return {
                            "status": "cached",
                            "original_link": link,
                            "hash": link_hash,
                            "cached_data": cached_info,
                            "debrid_filename": filename
                        }

                return {"status": "uncached", "original_link": link, "hash": link_hash}

            except Exception as e:
                debrid_logger.error(f"Cache check error: {type(e).__name__}")
                return {"status": "uncached", "original_link": link, "hash": link_hash}

    async def check_cache_batch(self, links: List[Dict], api_key: str, config: Dict) -> List[Dict]:
        if not links or not api_key:
            return links

        cache_timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT)

        cache_logger.debug(f"Checking {len(links)} links (timeout: {cache_timeout}s)")
        start_time = time.time()

        link_to_hash = {}
        hashes = []
        for link_dict in links:
            link = link_dict.get("link")
            if link:
                link_hash = self._calculate_hash(link)
                link_to_hash[link] = link_hash
                hashes.append(link_hash)

        if not hashes:
            cache_logger.debug("No valid links")
            return links

        http_error_count = 0

        while True:
            try:
                headers = self._get_headers(api_key)

                response = await http_client.get(
                    f"{self.API_URL}/webdl/checkcached",
                    params={"hash": hashes, "format": "object"},
                    headers=headers,
                    timeout=cache_timeout
                )

                if response.status_code != 200:
                    cache_logger.error(f"Batch failed: HTTP {response.status_code}")
                    for link_dict in links:
                        link_dict["cache_status"] = "uncached"
                    return links

                response_json = response.json()

                error_code = response_json.get("error")
                cooldown_result, http_error_count = await self._handle_cooldown_limit(error_code, http_error_count)
                if cooldown_result == "RETRY_ERROR":
                    for link_dict in links:
                        link_dict["cache_status"] = "uncached"
                    return links
                elif cooldown_result == "RETRY":
                    continue

                http_error_count = 0

                cache_data = response_json.get("data", {})
                for link_dict in links:
                    link = link_dict.get("link")
                    link_hash = link_to_hash.get(link)

                    if link_hash and link_hash in cache_data:
                        cached_info = cache_data[link_hash]

                        if cached_info and isinstance(cached_info, dict):
                            link_dict["cache_status"] = "cached"
                            link_dict["cached_data"] = cached_info
                            link_dict["debrid_filename"] = cached_info.get("name")
                        else:
                            link_dict["cache_status"] = "uncached"
                    else:
                        link_dict["cache_status"] = "uncached"

                break

            except Exception as e:
                cache_logger.error(f"Batch error: {type(e).__name__}")
                for link_dict in links:
                    link_dict["cache_status"] = "uncached"
                break

        cached_count = sum(1 for r in links if r.get("cache_status") == "cached")
        elapsed = time.time() - start_time
        cache_logger.debug(f"Done in {elapsed:.1f}s: {cached_count} cached / {len(links) - cached_count} uncached")

        return links

    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float) -> List[Dict]:
        from wastream.utils.quality import quality_sort_key

        start_time = time.time()

        if not api_key or not results:
            for result in results:
                result["cache_status"] = "uncached"
            return results

        initial_count = len(results)
        filtered_results = []
        for result in results:
            hoster = result.get("hoster", "").lower()
            if any(supported_host in hoster for supported_host in settings.TORBOX_SUPPORTED_HOSTS):
                filtered_results.append(result)

        if len(filtered_results) < initial_count:
            debrid_logger.debug(f"Filtered: {initial_count} → {len(filtered_results)} links")

        if not filtered_results:
            debrid_logger.debug("No supported hosts")
            return []

        results = filtered_results

        cache_timeout = max(0, timeout_remaining)
        config = {**config, "stream_request_timeout": cache_timeout}

        checked_results = await self.check_cache_batch(results, api_key, config)

        groups = self.group_identical_links(checked_results)

        grouped = {}
        for group_key, group_links in groups.items():
            grouped[group_key] = {"cached": None, "uncached": []}

            for result in group_links:
                if result.get("cache_status") == "cached":
                    if not grouped[group_key]["cached"]:
                        grouped[group_key]["cached"] = result
                else:
                    grouped[group_key]["uncached"].append(result)

        cached_results = []
        uncached_results = []

        for group_data in grouped.values():
            if group_data["cached"]:
                cached_results.append(group_data["cached"])
            else:
                uncached_results.extend(group_data["uncached"])

        cached_results.sort(key=quality_sort_key)
        uncached_results.sort(key=quality_sort_key)

        all_visible = cached_results + uncached_results

        if config.get("show_only_cached", False):
            elapsed = time.time() - start_time
            cache_logger.debug(f"Done in {elapsed:.1f}s: Only cached: {len(cached_results)} results")
            return cached_results

        elapsed = time.time() - start_time
        deduplicated = len(results) - len(all_visible)
        cache_logger.debug(f"Done in {elapsed:.1f}s: {len(all_visible)} results ({deduplicated} duplicates)")
        cache_logger.debug(f"Visible: {len(cached_results)} cached / {len(uncached_results)} uncached")

        return all_visible

    async def _create_webdownload_with_retry(self, cleaned_link: str, headers: Dict, http_error_count: int, return_web_id: bool = True):
        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:
                create_response = await http_client.post(
                    f"{self.API_URL}/webdl/createwebdownload",
                    data={
                        "link": cleaned_link,
                        "add_only_if_cached": False
                    },
                    headers=headers,
                    timeout=settings.HTTP_TIMEOUT
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    create_response, http_error_count, "TORBOX",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif create_response.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"Max HTTP retries ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
                    return "RETRY_ERROR", http_error_count

                http_error_count = 0

                if create_response.status_code == 401:
                    debrid_logger.error("Invalid API key (401)")
                    return "FATAL_ERROR", http_error_count

                if create_response.status_code == 403:
                    debrid_logger.error("Auth error (403)")
                    return "FATAL_ERROR", http_error_count

                if create_response.status_code != 200:
                    debrid_logger.error(f"Create HTTP {create_response.status_code}")
                    if attempt < settings.DEBRID_MAX_RETRIES - 1:
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue
                    return "FATAL_ERROR", http_error_count

                create_data = create_response.json()

                if isinstance(create_data, dict):
                    success = create_data.get("success", True)
                    error_code = create_data.get("error")
                    detail = create_data.get("detail", "Unknown error")

                    if not success and error_code:
                        cooldown_result, http_error_count = await self._handle_cooldown_limit(error_code, http_error_count)
                        if cooldown_result == "RETRY_ERROR":
                            return "RETRY_ERROR", http_error_count
                        elif cooldown_result == "RETRY":
                            continue

                        api_error_result = self._handle_api_error(error_code, detail, attempt)
                        if api_error_result in ["LINK_DOWN", "FATAL_ERROR", "RETRY_ERROR"]:
                            return api_error_result, http_error_count
                        elif api_error_result == "RETRY":
                            await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                            continue

                http_error_count = 0

                if return_web_id:
                    web_id = create_data.get("data", {}).get("webdownload_id")
                    if not web_id:
                        debrid_logger.error("No web_id")
                        if attempt < settings.DEBRID_MAX_RETRIES - 1:
                            await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                            continue
                        return "FATAL_ERROR", http_error_count
                    return web_id, http_error_count
                else:
                    return "SUCCESS", http_error_count

            except Exception as e:
                debrid_logger.error(f"Create attempt {attempt + 1} failed: {type(e).__name__}")
                if attempt < settings.DEBRID_MAX_RETRIES - 1:
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue
                return "FATAL_ERROR", http_error_count

        debrid_logger.error(f"Failed after {settings.DEBRID_MAX_RETRIES} attempts")
        return "FATAL_ERROR", http_error_count

    async def convert_link(self, link: str, api_key: str) -> Optional[str]:
        if not api_key:
            debrid_logger.error("Empty API key")
            return "FATAL_ERROR"

        debrid_logger.debug(f"Converting: {link[:80]}")

        cleaned_link = link
        if "&af=" in cleaned_link:
            cleaned_link = cleaned_link.split("&af=")[0]

        headers = self._get_headers(api_key)

        link_hash = self._calculate_hash(cleaned_link)
        cache_result = await self.check_cache_single_link(cleaned_link, link_hash, api_key)

        http_error_count = 0
        web_id = None

        if cache_result.get("status") != "cached":
            debrid_logger.debug("Uncached, re-checking...")

            recheck_result = await self.check_cache_single_link(cleaned_link, link_hash, api_key)

            if recheck_result.get("status") == "cached":
                debrid_logger.debug("Now cached!")
                cache_result = recheck_result
            else:
                debrid_logger.debug("Still uncached, starting download...")

                result, http_error_count = await self._create_webdownload_with_retry(cleaned_link, headers, http_error_count, return_web_id=False)

                if result == "SUCCESS":
                    debrid_logger.debug("Download started - uncached")
                    return "LINK_UNCACHED"
                else:
                    return result

        result, http_error_count = await self._create_webdownload_with_retry(cleaned_link, headers, http_error_count, return_web_id=True)

        if isinstance(result, str) and result in ["FATAL_ERROR", "RETRY_ERROR", "LINK_DOWN"]:
            return result

        web_id = result

        if not web_id:
            debrid_logger.error("Failed to get web_id")
            return "FATAL_ERROR"

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:

                request_response = await http_client.get(
                    f"{self.API_URL}/webdl/requestdl",
                    params={
                        "token": api_key,
                        "web_id": web_id,
                        "file_id": 0,
                        "zip_link": False
                    },
                    headers=headers,
                    timeout=settings.HTTP_TIMEOUT
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    request_response, http_error_count, "TORBOX",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif request_response.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"Max HTTP retries ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
                    return "RETRY_ERROR"

                http_error_count = 0

                if request_response.status_code != 200:
                    debrid_logger.error(f"Request HTTP {request_response.status_code}")
                    if attempt < settings.DEBRID_MAX_RETRIES - 1:
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue
                    return "FATAL_ERROR"

                request_data = request_response.json()

                if isinstance(request_data, dict):
                    success = request_data.get("success", True)
                    error_code = request_data.get("error")
                    detail = request_data.get("detail", "Unknown error")

                    if not success and error_code:
                        cooldown_result, http_error_count = await self._handle_cooldown_limit(error_code, http_error_count)
                        if cooldown_result == "RETRY_ERROR":
                            return "RETRY_ERROR"
                        elif cooldown_result == "RETRY":
                            continue

                        api_error_result = self._handle_api_error(error_code, detail, attempt)
                        if api_error_result in ["LINK_DOWN", "FATAL_ERROR", "RETRY_ERROR"]:
                            return api_error_result
                        elif api_error_result == "RETRY":
                            await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                            continue

                direct_link = request_data.get("data")

                if direct_link:
                    debrid_logger.debug("Converted")
                    return direct_link

                debrid_logger.error("No direct link")
                if attempt < settings.DEBRID_MAX_RETRIES - 1:
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                return "FATAL_ERROR"

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
torbox_service = TorBoxService()
