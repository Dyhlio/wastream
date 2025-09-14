import asyncio
import time
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from wastream.api.routes import router
from wastream.utils.database import setup_database, teardown_database, cleanup_expired_data
from wastream.utils.http_client import http_client
from wastream.core.config import (
    PORT, PROXY_URL, ADDON_NAME, ADDON_ID, ADDON_MANIFEST,
    WAWACITY_URL, DATABASE_TYPE, DATABASE_VERSION,
    CONTENT_CACHE_TTL, DEAD_LINK_TTL, SCRAPE_LOCK_TTL, SCRAPE_WAIT_TIMEOUT,
    ALLDEBRID_MAX_RETRIES, RETRY_DELAY_SECONDS, CLEANUP_INTERVAL
)
from wastream.utils.logger import logger

# === MIDDLEWARE ===

# Custom middleware for API request logging
class LoguruMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            logger.log("API", f"ERROR: Exception during request processing: {e}")
            raise
        finally:
            process_time = time.time() - start_time
            if request.url.path != "/health":
                logger.log(
                    "API",
                    f"{request.method} {request.url.path} - {response.status_code if 'response' in locals() else '500'} - {process_time:.2f}s",
                )
        return response

# === APPLICATION SETUP ===

# Manage application lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_database()
    cleanup_task = asyncio.create_task(cleanup_expired_data())
    
    yield
    
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    await http_client.close()
    await teardown_database()
app = FastAPI(
    title=ADDON_NAME,
    description="Accès au contenu de Wawacity via Stremio & AllDebrid (non officiel)",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(LoguruMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="wastream/public"), name="public")
app.include_router(router)

if __name__ == "__main__":
    
    if not WAWACITY_URL:
        logger.log("WARNING", "WAWACITY_URL is not configured! The addon will not work.")
        logger.log("WARNING", "Please configure WAWACITY_URL in your .env file")
        logger.log("WARNING", "Example: WAWACITY_URL=https://example.com")
    
    logger.log("STARTUP", f"Addon: {ADDON_NAME} v{ADDON_MANIFEST['version']} ({ADDON_ID})")
    logger.log("STARTUP", f"Server: http://localhost:{PORT}/")
    logger.log("STARTUP", f"Source: {WAWACITY_URL if WAWACITY_URL else 'NOT CONFIGURED'}")
    logger.log("STARTUP", f"Database: {DATABASE_TYPE} v{DATABASE_VERSION}")
    logger.log("STARTUP", f"Cache TTL: content={CONTENT_CACHE_TTL}s, dead_links={DEAD_LINK_TTL}s")
    logger.log("STARTUP", f"Locks: duration={SCRAPE_LOCK_TTL}s, timeout={SCRAPE_WAIT_TIMEOUT}s")
    logger.log("STARTUP", f"AllDebrid: {ALLDEBRID_MAX_RETRIES} retries, {RETRY_DELAY_SECONDS}s delay")
    logger.log("STARTUP", f"Cleanup: {CLEANUP_INTERVAL}s interval")
    
    if PROXY_URL:
        logger.log("STARTUP", "Proxy: enabled")
    else:
        logger.log("STARTUP", "Proxy: disabled")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=PORT,
        log_config=None
    )