import asyncio
import hashlib
import time
from asyncio import sleep
from typing import List, Dict, Optional, Tuple

from wastream.config.settings import settings
from wastream.debrid.base import BaseDebridService, HTTP_RETRY_ERRORS
from wastream.utils.http_client import http_client
from wastream.utils.logger import debrid_logger, cache_logger
from wastream.utils.quality import quality_sort_key

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

    async def check_cache_single_link(self, link: str, link_hash: str, api_key: str, download_type: str = "webdl", result: Optional[Dict] = None) -> Dict:
        http_error_count = 0

        check_endpoint = "usenet/checkcached" if download_type == "usenet" else "webdl/checkcached"

        while True:
            try:
                headers = self._get_headers(api_key)

                params = {"hash": [link_hash], "format": "object"}
                if download_type == "usenet":
                    params["list_files"] = "true"

                response = await http_client.get(
                    f"{self.API_URL}/{check_endpoint}",
                    params=params,
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
                        filename = None

                        if download_type == "usenet" and "files" in cached_info:
                            files = cached_info.get("files", [])
                            if files:
                                selected_file = None

                                if result and result.get("season") and result.get("episode"):
                                    try:
                                        pattern = f"S{int(result.get('season')):02d}E{int(result.get('episode')):02d}"
                                        matching_files = [f for f in files if pattern.upper() in f.get("short_name", "").upper()]
                                        if matching_files:
                                            selected_file = max(matching_files, key=lambda f: f.get("size", 0))
                                    except (ValueError, TypeError):
                                        pass

                                if not selected_file:
                                    selected_file = max(files, key=lambda f: f.get("size", 0))

                                filename = selected_file.get("short_name")
                        else:
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

    async def check_cache_batch(self, links: List[Dict], api_key: str, config: Dict, download_type: str = "webdl", user_season: Optional[str] = None, user_episode: Optional[str] = None) -> List[Dict]:
        if not links or not api_key:
            return links

        cache_timeout = config.get("stream_request_timeout", settings.STREAM_REQUEST_TIMEOUT)
        check_endpoint = "usenet/checkcached" if download_type == "usenet" else "webdl/checkcached"

        cache_logger.debug(f"Checking {len(links)} links (timeout: {cache_timeout}s)")
        start_time = time.time()

        link_to_hash = {}
        hashes = []
        for link_dict in links:
            link = link_dict.get("link")
            if link:
                if download_type == "usenet":
                    nzb_id = link.split("/")[-1]
                    download_url = f"{settings.DARKI_API_URL}/nzb/{nzb_id}/download"
                    link_hash = hashlib.md5(download_url.encode()).hexdigest()
                else:
                    cleaned_link = link
                    if "&af=" in cleaned_link:
                        cleaned_link = cleaned_link.split("&af=")[0]
                    link_hash = self._calculate_hash(cleaned_link)
                link_to_hash[link] = link_hash
                hashes.append(link_hash)

        if not hashes:
            cache_logger.debug("No valid links")
            return links

        http_error_count = 0

        while True:
            try:
                headers = self._get_headers(api_key)

                params = {"hash": hashes, "format": "object"}
                if download_type == "usenet":
                    params["list_files"] = "true"

                response = await http_client.get(
                    f"{self.API_URL}/{check_endpoint}",
                    params=params,
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

                            filename = None

                            if download_type == "usenet" and "files" in cached_info:
                                files = cached_info.get("files", [])
                                if files:
                                    selected_file = None
                                    check_season = user_season if user_season else link_dict.get("season")
                                    check_episode = user_episode if user_episode else link_dict.get("episode")

                                    if check_episode and check_season:
                                        try:
                                            pattern = f"S{int(check_season):02d}E{int(check_episode):02d}"
                                            matching_files = [f for f in files if pattern.upper() in f.get("short_name", "").upper()]
                                            if matching_files:
                                                selected_file = max(matching_files, key=lambda f: f.get("size", 0))
                                        except (ValueError, TypeError):
                                            pass

                                    if not selected_file:
                                        selected_file = max(files, key=lambda f: f.get("size", 0))

                                    filename = selected_file.get("short_name")
                            else:
                                filename = cached_info.get("name")

                            link_dict["debrid_filename"] = filename
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

    async def check_cache_and_enrich(self, results: List[Dict], api_key: str, config: Dict, timeout_remaining: float, user_season: Optional[str] = None, user_episode: Optional[str] = None) -> List[Dict]:
        start_time = time.time()

        if not api_key or not results:
            for result in results:
                result["cache_status"] = "uncached"
            return results

        enable_nzb = config.get("enable_nzb", False)

        initial_count = len(results)
        filtered_results = []
        nzb_results = []

        for result in results:
            if result.get("model_type") == "nzb":
                if enable_nzb:
                    nzb_results.append(result)
            else:
                hoster = result.get("hoster", "").lower()
                if any(supported_host in hoster for supported_host in settings.TORBOX_SUPPORTED_HOSTS):
                    filtered_results.append(result)

        if len(filtered_results) + len(nzb_results) < initial_count:
            debrid_logger.debug(f"Filtered: {initial_count} → {len(filtered_results)} DDL + {len(nzb_results)} NZB")

        if not filtered_results and not nzb_results:
            debrid_logger.debug("No supported hosts or NZB")
            return []

        cache_timeout = max(0, timeout_remaining)
        config_with_timeout = {**config, "stream_request_timeout": cache_timeout}

        ddl_checked = []
        if filtered_results:
            ddl_checked = await self.check_cache_batch(filtered_results, api_key, config_with_timeout, download_type="webdl", user_season=user_season, user_episode=user_episode)

        nzb_checked = []
        if nzb_results:
            nzb_checked = await self.check_cache_batch(nzb_results, api_key, config_with_timeout, download_type="usenet", user_season=user_season, user_episode=user_episode)

        checked_results = ddl_checked + nzb_checked

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

    async def _create_download_with_retry(self, link: str, headers: Dict, http_error_count: int, return_id: bool = True, download_type: str = "webdl"):
        create_endpoint = "usenet/createusenetdownload" if download_type == "usenet" else "webdl/createwebdownload"
        id_key = "usenetdownload_id" if download_type == "usenet" else "webdownload_id"

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:
                data_payload = {"link": link}
                if download_type == "webdl":
                    data_payload["add_only_if_cached"] = False

                create_response = await http_client.post(
                    f"{self.API_URL}/{create_endpoint}",
                    data=data_payload,
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

                if return_id:
                    download_id = create_data.get("data", {}).get(id_key)
                    if not download_id:
                        debrid_logger.error(f"No {id_key}")
                        if attempt < settings.DEBRID_MAX_RETRIES - 1:
                            await sleep(settings.DEBRID_RETRY_DELAY_SECONDS)
                            continue
                        return "FATAL_ERROR", http_error_count
                    return download_id, http_error_count
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

    async def convert_link(self, link: str, api_key: str, season: Optional[str] = None, episode: Optional[str] = None) -> Optional[str]:
        if not api_key:
            debrid_logger.error("Empty API key")
            return "FATAL_ERROR"

        download_type = "usenet" if "/nzb/" in link else "webdl"
        request_endpoint = "usenet/requestdl" if download_type == "usenet" else "webdl/requestdl"
        id_param_key = "usenet_id" if download_type == "usenet" else "web_id"

        debrid_logger.debug(f"Converting ({download_type}): {link[:80]}")

        cleaned_link = link
        if download_type == "webdl" and "&af=" in cleaned_link:
            cleaned_link = cleaned_link.split("&af=")[0]
        elif download_type == "usenet":
            nzb_id = link.split("/")[-1]
            cleaned_link = f"{settings.DARKI_API_URL}/nzb/{nzb_id}/download"

        headers = self._get_headers(api_key)

        if download_type == "usenet":
            link_hash = hashlib.md5(cleaned_link.encode()).hexdigest()
        else:
            link_hash = self._calculate_hash(cleaned_link)

        cache_result = await self.check_cache_single_link(link, link_hash, api_key, download_type)

        http_error_count = 0
        download_id = None

        if cache_result.get("status") != "cached":
            debrid_logger.debug("Uncached, starting download...")

            result, http_error_count = await self._create_download_with_retry(cleaned_link, headers, http_error_count, return_id=False, download_type=download_type)

            if result == "SUCCESS":
                debrid_logger.debug("Download started - uncached")
                return "LINK_UNCACHED"
            else:
                return result

        result, http_error_count = await self._create_download_with_retry(cleaned_link, headers, http_error_count, return_id=True, download_type=download_type)

        if isinstance(result, str) and result in ["FATAL_ERROR", "RETRY_ERROR", "LINK_DOWN"]:
            return result

        download_id = result

        if not download_id:
            debrid_logger.error(f"Failed to get {id_param_key}")
            return "FATAL_ERROR"

        file_id = 0
        if download_type == "usenet":
            try:
                mylist_response = await http_client.get(
                    f"{self.API_URL}/usenet/mylist",
                    params={"id": download_id},
                    headers=headers,
                    timeout=settings.HTTP_TIMEOUT
                )

                if mylist_response.status_code != 200:
                    debrid_logger.error(f"mylist HTTP {mylist_response.status_code}")
                    return "FATAL_ERROR"

                mylist_data = mylist_response.json()

                if not mylist_data.get("success"):
                    debrid_logger.error("mylist failed")
                    return "FATAL_ERROR"

                files = mylist_data.get("data", {}).get("files", [])

                if not files:
                    debrid_logger.error("mylist no files")
                    return "FATAL_ERROR"

                selected_file = None

                if season and episode:
                    try:
                        pattern = f"S{int(season):02d}E{int(episode):02d}"
                        matching_files = [f for f in files if pattern.upper() in f.get("short_name", "").upper()]

                        if matching_files:
                            selected_file = max(matching_files, key=lambda f: f.get("size", 0))
                    except (ValueError, TypeError):
                        pass

                if not selected_file:
                    selected_file = max(files, key=lambda f: f.get("size", 0))

                file_id = selected_file.get('id', 0)

            except Exception as e:
                debrid_logger.error(f"mylist exception: {e}")
                return "FATAL_ERROR"

        for attempt in range(settings.DEBRID_MAX_RETRIES):
            try:

                request_response = await http_client.get(
                    f"{self.API_URL}/{request_endpoint}",
                    params={
                        "token": api_key,
                        id_param_key: download_id,
                        "file_id": file_id,
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
