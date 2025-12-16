import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from wastream.api.routes import router
from wastream.utils.database import setup_database, teardown_database, cleanup_expired_data
from wastream.utils.http_client import http_client
from wastream.config.settings import settings
from wastream.utils.logger import setup_logger, addon_logger, api_logger


# ===========================
# Logger Setup
# ===========================
setup_logger(settings.LOG_LEVEL)


# ===========================
# Custom Middleware
# ===========================
class LoguruMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            api_logger.error(f"Exception: {type(e).__name__}")
            raise
        finally:
            process_time = time.time() - start_time
            if request.url.path != "/health":
                api_logger.debug(f"{request.method} {request.url.path} - {response.status_code if 'response' in locals() else '500'} - {process_time:.2f}s")
        return response


# ===========================
# Application Lifecycle
# ===========================
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


# ===========================
# FastAPI Application Setup
# ===========================
app = FastAPI(
    title=settings.ADDON_NAME,
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

STATIC_DIR = Path(__file__).parent / "public"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="public")
app.include_router(router)


# ===========================
# Application Entry Point
# ===========================
if __name__ == "__main__":

    if not settings.WAWACITY_URL and not settings.FREE_TELECHARGER_URL and not settings.DARKI_API_URL:
        addon_logger.error("No source configured (WAWACITY_URL, FREE_TELECHARGER_URL, DARKI_API_URL)!")
        addon_logger.error("The addon will not be able to find any content!")
        addon_logger.error("Please configure at least one source in your .env file")

    addon_logger.info(f"Starting {settings.ADDON_NAME} v{settings.ADDON_MANIFEST['version']} ({settings.ADDON_ID})")
    addon_logger.info(f"Server: http://localhost:{settings.PORT}/")
    addon_logger.info(f"Wawacity: {settings.WAWACITY_URL if settings.WAWACITY_URL else 'NOT CONFIGURED'}")
    addon_logger.info(f"Free-Telecharger: {settings.FREE_TELECHARGER_URL if settings.FREE_TELECHARGER_URL else 'NOT CONFIGURED'}")
    addon_logger.info(f"Darki-API: {settings.DARKI_API_URL if settings.DARKI_API_URL else 'NOT CONFIGURED'}")
    addon_logger.info(f"Database: {settings.DATABASE_TYPE} v{settings.DATABASE_VERSION}")
    addon_logger.info(f"Proxy: {'enabled' if settings.PROXY_URL else 'disabled'}")
    addon_logger.info(f"Log level: {settings.LOG_LEVEL}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.PORT,
        log_config=None
    )
