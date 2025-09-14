from typing import Optional
from asyncio import sleep
from wastream.utils.http_client import http_client
from wastream.core.config import ALLDEBRID_API_URL, ALLDEBRID_MAX_RETRIES, RETRY_DELAY_SECONDS, ADDON_NAME
from wastream.utils.logger import logger

# AllDebrid link conversion service
class AllDebridService:
    
    async def convert_link(self, dl_protect_link: str, apikey: str) -> Optional[str]:
        if not apikey:
            logger.log("ALLDEBRID", "ERROR: AllDebrid key is empty")
            return None
        
        logger.log("ALLDEBRID", f"Converting: {dl_protect_link}")
        
        for attempt in range(ALLDEBRID_MAX_RETRIES):
            try:
                response1 = await http_client.get(
                    f"{ALLDEBRID_API_URL}/link/redirector",
                    params={"agent": ADDON_NAME, "apikey": apikey, "link": dl_protect_link}
                )
                
                if response1.status_code != 200:
                    logger.log("ALLDEBRID", f"ERROR: Redirector failed: {response1.status_code} (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                    await sleep(RETRY_DELAY_SECONDS)
                    continue
                
                data1 = response1.json()
                if data1.get("status") != "success":
                    error = data1.get("error", {})
                    if error.get("code") == "LINK_HOST_NOT_SUPPORTED":
                        logger.log("ALLDEBRID", f"ERROR: Redirector error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')}")
                        return None
                    elif error.get("code") == "LINK_HOST_UNAVAILABLE":
                        logger.log("ALLDEBRID", f"ERROR: Redirector error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')}")
                        return None
                    elif error.get("code") == "LINK_DOWN":
                        logger.log("ALLDEBRID", f"ERROR: Redirector error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')}")
                        return "LINK_DOWN"
                    
                    logger.log("ALLDEBRID", f"ERROR: Redirector error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')} (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                    await sleep(RETRY_DELAY_SECONDS)
                    continue
                
                redirected_links = data1.get("data", {}).get("links", [])
                if not redirected_links:
                    logger.log("ALLDEBRID", f"ERROR: No redirected links (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                    await sleep(RETRY_DELAY_SECONDS)
                    continue
                
                first_link = redirected_links[0]
                response2 = await http_client.get(
                    f"{ALLDEBRID_API_URL}/link/unlock",
                    params={"agent": ADDON_NAME, "apikey": apikey, "link": first_link}
                )
                
                if response2.status_code != 200:
                    logger.log("ALLDEBRID", f"ERROR: Unlock failed: {response2.status_code} (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                    await sleep(RETRY_DELAY_SECONDS)
                    continue
                
                data2 = response2.json()
                if data2.get("status") != "success":
                    error = data2.get("error", {})
                    
                    if error.get("code") == "LINK_DOWN":
                        logger.log("ALLDEBRID", f"ERROR: Unlock error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')}")
                        return "LINK_DOWN"
                    
                    logger.log("ALLDEBRID", f"ERROR: Unlock error: {error.get('code', 'UNKNOWN')} - {error.get('message', 'Unknown')} (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                    await sleep(RETRY_DELAY_SECONDS)
                    continue
                
                direct_link = data2.get("data", {}).get("link")
                if direct_link:
                    logger.log("ALLDEBRID", "Link converted successfully")
                    return direct_link
                
            except Exception as e:
                logger.log("ALLDEBRID", f"ERROR: Attempt {attempt + 1} failed: {e} (attempt {attempt + 1}/{ALLDEBRID_MAX_RETRIES}, retry in {RETRY_DELAY_SECONDS}s)")
                if attempt < ALLDEBRID_MAX_RETRIES - 1:
                    await sleep(RETRY_DELAY_SECONDS)
        
        logger.log("ALLDEBRID", f"ERROR: Failed after {ALLDEBRID_MAX_RETRIES} attempts")
        return None

alldebrid_service = AllDebridService()