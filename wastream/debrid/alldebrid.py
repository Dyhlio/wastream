import asyncio
import time
from asyncio import sleep
from typing import Optional, List, Dict

from wastream.config.settings import settings
from wastream.debrid.base import BaseDebridService, HTTP_RETRY_ERRORS
from wastream.utils.http_client import http_client
from wastream.utils.logger import debrid_logger, cache_logger
from wastream.utils.quality import quality_sort_key

# ===========================
# AllDebrid Error Constants
# ===========================
RETRY_ERRORS = [
    "LINK_HOST_UNAVAILABLE",
    "LINK_TEMPORARY_UNAVAILABLE",
    "LINK_TOO_MANY_DOWNLOADS",
    "LINK_HOST_FULL",
    "LINK_HOST_LIMIT_REACHED",
    "REDIRECTOR_ERROR",
]

# ===========================
# AllDebrid Service Class
# ===========================
class AllDebridService(BaseDebridService):
    def get_service_name(self) -> str:
        return "AllDebrid"

    async def check_cache_single_link(self, link: str, api_key: str) -> Dict:
        if not api_key:
            return {"status": "hidden", "original_link": link}

        is_direct_link = any(host in link for host in ["1fichier.com", "turbobit.net", "rapidgator.net"])
        http_error_count = 0

        while True:
            try:
                if is_direct_link:
                    response = await http_client.get(
                        f"{settings.ALLDEBRID_API_URL}/link/unlock",
                        params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": link},
                        timeout=settings.DEBRID_CACHE_CHECK_HTTP_TIMEOUT
                    )
                else:
                    response = await http_client.get(
                        f"{settings.ALLDEBRID_API_URL}/link/redirector",
                        params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": link},
                        timeout=settings.DEBRID_CACHE_CHECK_HTTP_TIMEOUT
                    )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response, http_error_count, "ALLDEBRID",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif response.status_code in HTTP_RETRY_ERRORS:
                    return {"status": "uncached", "original_link": link, "http_error": True}

                if response.status_code == 404:
                    debrid_logger.error("404 - Endpoint not found")
                    return {"status": "hidden", "original_link": link}

                if response.status_code != 200:
                    debrid_logger.debug(f"HTTP {response.status_code}")
                    return {"status": "uncached", "original_link": link}

                data = response.json()

                if data.get("status") != "success":
                    error_code = data.get("error", {}).get("code")

                    if error_code == "LINK_DOWN":
                        debrid_logger.debug("LINK_DOWN")
                        return {"status": "hidden", "original_link": link, "error": "LINK_DOWN"}

                    if error_code in RETRY_ERRORS:
                        debrid_logger.debug(f"{error_code}")
                        return {"status": "uncached", "original_link": link}

                    debrid_logger.error(f"Fatal: {error_code}")
                    return {"status": "hidden", "original_link": link}

                result = data.get("data", {})

                if "delayed" in result:
                    debrid_logger.debug("Delayed")
                    return {"status": "uncached", "original_link": link}

                if not is_direct_link:
                    redirected_links = result.get("links", [])
                    if not redirected_links:
                        return {"status": "uncached", "original_link": link}

                    first_link = redirected_links[0]
                    response2 = await http_client.get(
                        f"{settings.ALLDEBRID_API_URL}/link/unlock",
                        params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": first_link},
                        timeout=settings.DEBRID_CACHE_CHECK_HTTP_TIMEOUT
                    )

                    if response2.status_code != 200:
                        return {"status": "uncached", "original_link": link}

                    data2 = response2.json()
                    if data2.get("status") != "success":
                        error_code2 = data2.get("error", {}).get("code")
                        if error_code2 == "LINK_DOWN":
                            return {"status": "hidden", "original_link": link, "error": "LINK_DOWN"}
                        return {"status": "uncached", "original_link": link}

                    result = data2.get("data", {})
                    if "delayed" in result:
                        return {"status": "uncached", "original_link": link}

                direct_link = result.get("link")
                filename = result.get("filename")
                if direct_link:
                    debrid_logger.debug("Cached")
                    return {
                        "status": "cached",
                        "cached_link": direct_link,
                        "original_link": link,
                        "debrid_filename": filename
                    }

                return {"status": "uncached", "original_link": link}

            except Exception as e:
                debrid_logger.error(f"Cache check error: {type(e).__name__}")
                return {"status": "uncached", "original_link": link}

    async def check_cache_batch(self, links: List[Dict], api_key: str, config: Dict = None) -> List[Dict]:
        if not links or not api_key:
            return links

        cache_timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT) if config else settings.STREAM_REQUEST_TIMEOUT

        cache_logger.debug(f"Checking {len(links)} links (timeout: {cache_timeout}s)")

        start_time = time.time()
        results = []
        global_http_error_count = 0
        stop_all = False

        batch_size = settings.ALLDEBRID_BATCH_SIZE

        for i in range(0, len(links), batch_size):
            if time.time() - start_time > cache_timeout:
                cache_logger.debug(f"Timeout {cache_timeout}s reached")
                for remaining_link in links[i:]:
                    results.append({**remaining_link, "status": "uncached"})
                break

            if stop_all:
                cache_logger.error("Too many HTTP errors")
                for remaining_link in links[i:]:
                    results.append({**remaining_link, "status": "uncached"})
                break

            batch = links[i:i + batch_size]
            cache_logger.debug(f"Batch {i//batch_size + 1} ({len(batch)} links)")

            batch_tasks = [
                self.check_cache_single_link(link_dict.get("link"), api_key)
                for link_dict in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    results.append({**batch[j], "status": "uncached"})
                else:
                    if result.get("http_error"):
                        global_http_error_count += 1
                        if global_http_error_count >= settings.DEBRID_HTTP_ERROR_MAX_RETRIES:
                            cache_logger.error(f"Global HTTP errors: {global_http_error_count}")
                            stop_all = True

                    results.append({**batch[j], **result})

            if i + batch_size < len(links) and not stop_all:
                await sleep(1)

        cached_count = sum(1 for r in results if r.get("status") == "cached")
        uncached_count = sum(1 for r in results if r.get("status") == "uncached")
        hidden_count = sum(1 for r in results if r.get("status") == "hidden")

        elapsed = time.time() - start_time
        cache_logger.debug(f"Done in {elapsed:.1f}s: {cached_count} cached / {uncached_count} uncached / {hidden_count} hidden")

        return results

    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float, user_season: Optional[str] = None, user_episode: Optional[str] = None) -> List[Dict]:
        start_time = time.time()

        if not api_key or not results:
            for result in results:
                result["cache_status"] = "uncached"
            return results

        initial_count = len(results)
        filtered_results = []
        for result in results:
            if result.get("model_type") == "nzb":
                continue
            hoster = result.get("hoster", "").lower()
            if any(supported_host in hoster for supported_host in settings.ALLDEBRID_SUPPORTED_HOSTS):
                filtered_results.append(result)

        if len(filtered_results) < initial_count:
            debrid_logger.debug(f"Filtered: {initial_count} → {len(filtered_results)} links (AllDebrid doesn't support Usenet)")

        if not filtered_results:
            debrid_logger.debug("No supported hosts")
            return []

        results = filtered_results

        cache_timeout = max(0, timeout_remaining)

        groups = self.group_identical_links(results)

        group_states = {}
        for group_key, group_links in groups.items():
            group_states[group_key] = {
                "links": group_links,
                "resolved": False,
                "cached_found": None,
                "uncached": []
            }

        links_queue = []
        max_group_size = max(len(state["links"]) for state in group_states.values())

        for round_idx in range(max_group_size):
            for group_key, state in group_states.items():
                if round_idx < len(state["links"]):
                    links_queue.append((group_key, state["links"][round_idx]))

        batch_size = settings.ALLDEBRID_BATCH_SIZE
        total_tested = 0
        total_skipped = 0

        while links_queue:
            links_queue = [(group_key, link) for group_key, link in links_queue if not group_states[group_key]["resolved"]]

            if not links_queue:
                break

            elapsed = time.time() - start_time
            if elapsed > cache_timeout:
                cache_logger.debug(f"Timeout {cache_timeout}s reached")
                for group_key, link_data in links_queue:
                    if not group_states[group_key]["resolved"]:
                        link_data["cache_status"] = "uncached"
                        group_states[group_key]["uncached"].append(link_data)
                break

            time_remaining = cache_timeout - elapsed

            batch = links_queue[:batch_size]
            links_queue = links_queue[batch_size:]

            tasks = [self.check_cache_single_link(link.get("link"), api_key)
                     for group_key, link in batch]

            try:
                results_batch = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=time_remaining
                )
            except asyncio.TimeoutError:
                cache_logger.debug("Timeout during batch")
                for group_key, link_data in batch:
                    if not group_states[group_key]["resolved"]:
                        link_data["cache_status"] = "uncached"
                        group_states[group_key]["uncached"].append(link_data)
                for group_key, link_data in links_queue:
                    if not group_states[group_key]["resolved"]:
                        link_data["cache_status"] = "uncached"
                        group_states[group_key]["uncached"].append(link_data)
                break

            total_tested += len(batch)

            for (group_key, link_data), result in zip(batch, results_batch):
                if isinstance(result, Exception):
                    continue

                state = group_states[group_key]
                status = result.get("status")

                if status == "cached":
                    link_data["cache_status"] = "cached"
                    link_data["cached_link"] = result.get("cached_link")
                    link_data["debrid_filename"] = result.get("debrid_filename")
                    state["cached_found"] = link_data
                    state["resolved"] = True

                    skipped_links = [(queued_group_key, queued_link) for queued_group_key, queued_link in links_queue if queued_group_key == group_key]
                    if skipped_links:
                        total_skipped += len(skipped_links)
                        cache_logger.debug(f"Group cached, skipped {len(skipped_links)} identical")

                elif status == "uncached":
                    link_data["cache_status"] = "uncached"
                    state["uncached"].append(link_data)

            if links_queue:
                await sleep(1)

        cached_results = []
        uncached_results = []

        for state in group_states.values():
            if state["cached_found"]:
                cached_results.append(state["cached_found"])
            else:
                uncached_results.extend(state["uncached"])

        cached_results.sort(key=quality_sort_key)
        uncached_results.sort(key=quality_sort_key)

        all_visible = cached_results + uncached_results

        if config.get("show_only_cached", False):
            elapsed = time.time() - start_time
            cache_logger.debug(f"Done in {elapsed:.1f}s: {total_tested} tested, saved {total_skipped} requests")
            cache_logger.debug(f"Only cached: {len(all_visible)} → {len(cached_results)} results")
            return cached_results

        elapsed = time.time() - start_time
        cache_logger.debug(f"Done in {elapsed:.1f}s: {total_tested} tested, saved {total_skipped} requests")
        cache_logger.debug(f"Visible: {len(cached_results)} cached / {len(uncached_results)} uncached")

        return all_visible

    async def convert_link(self, link: str, api_key: str, season: Optional[str] = None, episode: Optional[str] = None) -> Optional[str]:
        if not api_key:
            debrid_logger.error("Empty API key")
            return None

        debrid_logger.debug(f"Converting: {link}")

        is_direct_link = any(host in link for host in ["1fichier.com", "turbobit.net", "rapidgator.net"])
        http_error_count = 0

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:
                if is_direct_link:
                    response1 = await http_client.get(
                        f"{settings.ALLDEBRID_API_URL}/link/unlock",
                        params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": link}
                    )
                else:
                    response1 = await http_client.get(
                        f"{settings.ALLDEBRID_API_URL}/link/redirector",
                        params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": link}
                    )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response1, http_error_count, "ALLDEBRID",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif response1.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"Max HTTP retries ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
                    return "RETRY_ERROR"

                http_error_count = 0

                if response1.status_code != 200:
                    debrid_logger.error(f"Redirector HTTP {response1.status_code}")
                    if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                        return "FATAL_ERROR"
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                data1 = response1.json()
                if data1.get("status") != "success":
                    error = data1.get("error", {})
                    error_code = error.get("code")

                    if error_code == "LINK_DOWN":
                        debrid_logger.debug(f"{error_code}")
                        return "LINK_DOWN"

                    if error_code in RETRY_ERRORS:
                        debrid_logger.error(f"{error_code}")
                        if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                            return "RETRY_ERROR"
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue

                    debrid_logger.error(f"Fatal: {error_code}")
                    return "FATAL_ERROR"

                if is_direct_link:
                    if "delayed" in data1.get("data", {}):
                        debrid_logger.debug("Delayed - uncached")
                        return "LINK_UNCACHED"

                    direct_link = data1.get("data", {}).get("link")
                    if direct_link:
                        debrid_logger.debug("Converted")
                        return direct_link
                    else:
                        debrid_logger.error("No direct link")
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue

                redirected_links = data1.get("data", {}).get("links", [])
                if not redirected_links:
                    debrid_logger.error("No redirected links")
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                first_link = redirected_links[0]
                response2 = await http_client.get(
                    f"{settings.ALLDEBRID_API_URL}/link/unlock",
                    params={"agent": settings.ADDON_NAME, "apikey": api_key, "link": first_link}
                )

                should_retry, http_error_count = await self._handle_http_retry_error(
                    response2, http_error_count, "ALLDEBRID",
                    settings.DEBRID_HTTP_ERROR_RETRY_DELAY, settings.DEBRID_HTTP_ERROR_MAX_RETRIES
                )
                if should_retry:
                    continue
                elif response2.status_code in HTTP_RETRY_ERRORS:
                    debrid_logger.error(f"Max HTTP retries ({settings.DEBRID_HTTP_ERROR_MAX_RETRIES})")
                    return "RETRY_ERROR"

                http_error_count = 0

                if response2.status_code != 200:
                    debrid_logger.error(f"Unlock HTTP {response2.status_code}")
                    if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                        return "FATAL_ERROR"
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                    continue

                data2 = response2.json()
                if data2.get("status") != "success":
                    error = data2.get("error", {})
                    error_code2 = error.get("code")

                    if error_code2 == "LINK_DOWN":
                        debrid_logger.debug(f"{error_code2}")
                        return "LINK_DOWN"

                    if error_code2 in RETRY_ERRORS:
                        debrid_logger.error(f"{error_code2}")
                        if attempt >= settings.DEBRID_MAX_RETRIES - 1:
                            return "RETRY_ERROR"
                        await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                        continue

                    debrid_logger.error(f"Fatal: {error_code2}")
                    return "FATAL_ERROR"

                if "delayed" in data2.get("data", {}):
                    debrid_logger.debug("Delayed - uncached")
                    return "LINK_UNCACHED"

                direct_link = data2.get("data", {}).get("link")
                if direct_link:
                    debrid_logger.debug("Converted")
                    return direct_link

            except Exception as e:
                debrid_logger.error(f"Attempt {attempt + 1} failed: {type(e).__name__}")
                if attempt < settings.DEBRID_MAX_RETRIES - 1:
                    await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)

        debrid_logger.error(f"Failed after {settings.DEBRID_MAX_RETRIES} attempts")
        return "FATAL_ERROR"

# ===========================
# Singleton Instance
# ===========================
alldebrid_service = AllDebridService()
