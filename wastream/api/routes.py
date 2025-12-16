import time
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Request, Query, Path
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, HTMLResponse

from wastream.config.settings import settings
from wastream.utils.validators import validate_config
from wastream.services.stream import stream_service
from wastream.utils.languages import AVAILABLE_LANGUAGES
from wastream.utils.quality import AVAILABLE_RESOLUTIONS
from wastream.utils.logger import api_logger
from wastream.utils.http_client import http_client
from wastream.utils.database import database


# ===========================
# Router Instance
# ===========================
router = APIRouter()


# ===========================
# Content Type Enum
# ===========================
class ContentType(str, Enum):
    movie = "movie"
    series = "series"


# ===========================
# Service Type Enum
# ===========================
class ServiceType(str, Enum):
    alldebrid = "alldebrid"
    torbox = "torbox"
    premiumize = "premiumize"
    onefichier = "1fichier"
    tmdb = "tmdb"


# ===========================
# Web Interface Endpoints
# ===========================
@router.get("/", summary="Home", description="Redirects to the configuration page")
async def root():
    return RedirectResponse("/configure")


@router.get("/configure", summary="Configuration", description="Web interface to configure the addon")
async def configure():
    with open("wastream/public/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    html_content = html_content.replace("{{CUSTOM_HTML}}", settings.CUSTOM_HTML)
    html_content = html_content.replace("{{ADDON_NAME}}", settings.ADDON_NAME)
    html_content = html_content.replace("{{VERSION}}", settings.ADDON_MANIFEST["version"])

    return HTMLResponse(content=html_content)


@router.get("/{b64config}/configure", summary="Reconfigure", description="Modify existing configuration")
async def configure_addon(
    b64config: str = Path(..., description="Base64 encoded configuration")
):
    with open("wastream/public/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    html_content = html_content.replace("{{CUSTOM_HTML}}", settings.CUSTOM_HTML)
    html_content = html_content.replace("{{ADDON_NAME}}", settings.ADDON_NAME)
    html_content = html_content.replace("{{VERSION}}", settings.ADDON_MANIFEST["version"])

    return HTMLResponse(content=html_content)


# ===========================
# Stremio Addon Endpoints
# ===========================
@router.get("/{b64config}/manifest.json", summary="Stremio Manifest", description="Returns addon metadata for installation")
async def get_manifest(
    b64config: str = Path(..., description="Base64 encoded configuration")
):
    config = validate_config(b64config)

    manifest = settings.ADDON_MANIFEST.copy()

    if config and "debrid_services" in config:
        debrid_services = config["debrid_services"]
        if len(debrid_services) == 1:
            service_name = debrid_services[0].get("service", "alldebrid")
            if service_name == "alldebrid":
                manifest["name"] = f"{settings.ADDON_NAME} | AD"
            elif service_name == "torbox":
                manifest["name"] = f"{settings.ADDON_NAME} | TB"
            elif service_name == "premiumize":
                manifest["name"] = f"{settings.ADDON_NAME} | PM"
            elif service_name == "1fichier":
                manifest["name"] = f"{settings.ADDON_NAME} | 1F"
        elif len(debrid_services) > 1:
            manifest["name"] = f"{settings.ADDON_NAME} | MULTI"

    return JSONResponse(content=manifest)


@router.get("/{b64config}/stream/{content_type}/{content_id}",
            summary="Get streams",
            description="Returns available streams for the requested content")
async def get_streams(
    request: Request,
    b64config: str = Path(..., description="Base64 encoded configuration"),
    content_type: ContentType = Path(..., description="Content type"),
    content_id: str = Path(..., description="Content identifier")
):
    config = validate_config(b64config)
    if not config:
        api_logger.debug("Invalid config")
        return JSONResponse(content={"streams": []})

    content_id_formatted = content_id.replace(".json", "")
    api_logger.debug(f"Stream: {content_type.value}/{content_id_formatted}")

    try:
        base_url = str(request.base_url).rstrip("/")

        streams = await stream_service.get_streams(
            content_type=content_type.value,
            content_id=content_id_formatted,
            config=config,
            base_url=base_url
        )

        return JSONResponse(content={
            "streams": streams,
            "cacheMaxAge": 1
        })

    except Exception as e:
        api_logger.error(f"Stream failed: {type(e).__name__}")
        return JSONResponse(content={"streams": []})


# ===========================
# Utility Endpoints
# ===========================
@router.get("/resolve",
            summary="Resolve link",
            description="Converts a link to a direct streaming URL")
async def resolve(
    link: str = Query(..., description="Link to resolve"),
    b64config: str = Query(..., description="Base64 encoded configuration"),
    season: Optional[str] = Query(None, description="Season number for series"),
    episode: Optional[str] = Query(None, description="Episode number for series"),
    service: Optional[str] = Query(None, description="Debrid service to use")
):
    api_logger.debug(f"Resolving link: {link[:80]}")

    config = validate_config(b64config)
    if not config:
        api_logger.debug("Invalid config")
        return FileResponse("wastream/public/fatal_error.mp4")

    debrid_services = config.get("debrid_services", [])
    if not debrid_services:
        api_logger.debug("No debrid services configured")
        return FileResponse("wastream/public/fatal_error.mp4")

    return await stream_service.resolve_link_with_response(link, config, season, episode, service)


# ===========================
# Configuration Options Endpoints
# ===========================
@router.get("/available/languages",
            summary="Available languages",
            description="Returns available language options")
async def get_available_languages():
    return JSONResponse(content={
        "languages": AVAILABLE_LANGUAGES
    })


@router.get("/available/resolutions",
            summary="Available resolutions",
            description="Returns available quality options")
async def get_available_resolutions():
    return JSONResponse(content={
        "resolutions": AVAILABLE_RESOLUTIONS
    })


@router.get("/available/services",
            summary="Available services",
            description="Returns available debrid services with their supported hosts and sources")
async def get_available_services():
    return JSONResponse(content={
        "alldebrid": {
            "hosts": settings.ALLDEBRID_SUPPORTED_HOSTS,
            "sources": settings.ALLDEBRID_SUPPORTED_SOURCES
        },
        "torbox": {
            "hosts": settings.TORBOX_SUPPORTED_HOSTS,
            "sources": settings.TORBOX_SUPPORTED_SOURCES
        },
        "premiumize": {
            "hosts": settings.PREMIUMIZE_SUPPORTED_HOSTS,
            "sources": settings.PREMIUMIZE_SUPPORTED_SOURCES
        },
        "1fichier": {
            "hosts": settings.ONEFICHIER_SUPPORTED_HOSTS,
            "sources": settings.ONEFICHIER_SUPPORTED_SOURCES
        }
    })


@router.get("/password-config",
            summary="Password status",
            description="Checks if password protection is enabled")
async def get_password_config():
    return JSONResponse(content={
        "password_required": bool(settings.ADDON_PASSWORD.strip())
    })


@router.post("/verify-password",
             summary="Verify password",
             description="Validates the provided password")
async def verify_password(password: str = Query(..., description="Password to verify")):
    if not settings.ADDON_PASSWORD.strip():
        return JSONResponse(content={"valid": True})

    valid_passwords = [pwd.strip() for pwd in settings.ADDON_PASSWORD.split(",") if pwd.strip()]
    is_valid = password in valid_passwords

    return JSONResponse(content={"valid": is_valid})


@router.get("/verify-api-key",
            summary="Verify API key",
            description="Validates debrid service API key or TMDB token")
async def verify_api_key(
    service: ServiceType = Query(..., description="Service"),
    api_key: str = Query(..., description="API key")
):
    if not api_key or not api_key.strip():
        return JSONResponse(content={"valid": False})

    api_key = api_key.strip()

    try:
        if service == ServiceType.alldebrid:
            response = await http_client.get(
                f"{settings.ALLDEBRID_API_URL}/user",
                params={"agent": settings.ADDON_NAME, "apikey": api_key},
                timeout=settings.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return JSONResponse(content={"valid": True})
            return JSONResponse(content={"valid": False})

        elif service == ServiceType.torbox:
            response = await http_client.get(
                f"{settings.TORBOX_API_URL}/user/me",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=settings.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return JSONResponse(content={"valid": True})
            return JSONResponse(content={"valid": False})

        elif service == ServiceType.premiumize:
            response = await http_client.get(
                f"{settings.PREMIUMIZE_API_URL}/account/info",
                params={"apikey": api_key},
                timeout=settings.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return JSONResponse(content={"valid": True})
            return JSONResponse(content={"valid": False})

        elif service == ServiceType.onefichier:
            response = await http_client.post(
                f"{settings.ONEFICHIER_API_URL}/folder/ls.cgi",
                json={"folder_id": 0},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": settings.ADDON_NAME
                },
                timeout=settings.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "KO":
                    return JSONResponse(content={"valid": False})
                return JSONResponse(content={"valid": True})
            return JSONResponse(content={"valid": False})

        elif service == ServiceType.tmdb:
            response = await http_client.get(
                f"{settings.TMDB_API_URL}/configuration",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=settings.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                return JSONResponse(content={"valid": True})
            return JSONResponse(content={"valid": False})

        else:
            return JSONResponse(content={"valid": False})

    except Exception:
        return JSONResponse(content={"valid": False})


# ===========================
# Health Check Endpoint
# ===========================
@router.get("/health",
            summary="Health check",
            description="Returns the current health status of the service")
async def health_check():
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "version": settings.ADDON_MANIFEST["version"],
        "timestamp": int(time.time()),
        "checks": {}
    }

    health_status["checks"]["server"] = {
        "status": "ok",
        "message": "Addon server running"
    }

    try:
        await database.fetch_val("SELECT 1")
        health_status["checks"]["database"] = {
            "status": "ok",
            "message": "Database connection active"
        }
    except Exception as e:
        health_status["checks"]["database"] = {
            "status": "error",
            "message": f"Database error: {str(e)}"
        }
        health_status["status"] = "degraded"

    if settings.WAWACITY_URL:
        wastream_start = time.time()
        try:
            response = await http_client.get(settings.WAWACITY_URL, timeout=settings.HEALTH_CHECK_TIMEOUT)
            wawacity_time = round((time.time() - wastream_start) * 1000)

            if response.status_code == 200:
                health_status["checks"]["wawacity"] = {
                    "status": "ok",
                    "message": "Wawacity accessible",
                    "response_time_ms": wawacity_time
                }
            else:
                health_status["checks"]["wawacity"] = {
                    "status": "error",
                    "message": f"Wawacity HTTP {response.status_code}",
                    "response_time_ms": wawacity_time
                }
                health_status["status"] = "degraded"

        except Exception as e:
            wawacity_time = round((time.time() - wastream_start) * 1000)
            health_status["checks"]["wawacity"] = {
                "status": "error",
                "message": f"Wawacity unreachable: {str(e)}",
                "response_time_ms": wawacity_time
            }
            health_status["status"] = "unhealthy"
    else:
        health_status["checks"]["wawacity"] = {
            "status": "disabled",
            "message": "Wawacity not configured"
        }

    if settings.FREE_TELECHARGER_URL:
        free_telecharger_start = time.time()
        try:
            response = await http_client.get(settings.FREE_TELECHARGER_URL, timeout=settings.HEALTH_CHECK_TIMEOUT)
            free_telecharger_time = round((time.time() - free_telecharger_start) * 1000)

            if response.status_code == 200:
                health_status["checks"]["free_telecharger"] = {
                    "status": "ok",
                    "message": "Free-Telecharger accessible",
                    "response_time_ms": free_telecharger_time
                }
            else:
                health_status["checks"]["free_telecharger"] = {
                    "status": "error",
                    "message": f"Free-Telecharger HTTP {response.status_code}",
                    "response_time_ms": free_telecharger_time
                }
                health_status["status"] = "degraded"

        except Exception as e:
            free_telecharger_time = round((time.time() - free_telecharger_start) * 1000)
            health_status["checks"]["free_telecharger"] = {
                "status": "error",
                "message": f"Free-Telecharger unreachable: {str(e)}",
                "response_time_ms": free_telecharger_time
            }
            health_status["status"] = "unhealthy"
    else:
        health_status["checks"]["free_telecharger"] = {
            "status": "disabled",
            "message": "Free-Telecharger not configured"
        }

    if settings.DARKI_API_URL:
        darki_api_start = time.time()
        try:
            response = await http_client.get(f"{settings.DARKI_API_URL}/health", timeout=settings.HEALTH_CHECK_TIMEOUT)
            darki_api_time = round((time.time() - darki_api_start) * 1000)

            if response.status_code == 200:
                data = response.json()
                darkiworld_status = data.get("darkiworld_status", "Unknown")
                api_status = data.get("status", "Unknown")

                if api_status == "healthy" and darkiworld_status == "reachable":
                    health_status["checks"]["darki_api"] = {
                        "status": "ok",
                        "message": "Darki-API accessible",
                        "response_time_ms": darki_api_time,
                        "darkiworld_status": darkiworld_status
                    }
                else:
                    health_status["checks"]["darki_api"] = {
                        "status": "degraded",
                        "message": f"Darki-API degraded (API: {api_status}, darkiworld: {darkiworld_status})",
                        "response_time_ms": darki_api_time,
                        "darkiworld_status": darkiworld_status
                    }
                    health_status["status"] = "degraded"
            else:
                health_status["checks"]["darki_api"] = {
                    "status": "error",
                    "message": f"Darki-API HTTP {response.status_code}",
                    "response_time_ms": darki_api_time
                }
                health_status["status"] = "degraded"

        except Exception as e:
            darki_api_time = round((time.time() - darki_api_start) * 1000)
            health_status["checks"]["darki_api"] = {
                "status": "error",
                "message": f"Darki-API unreachable: {str(e)}",
                "response_time_ms": darki_api_time
            }
            health_status["status"] = "degraded"
    else:
        health_status["checks"]["darki_api"] = {
            "status": "disabled",
            "message": "Darki-API not configured"
        }

    if settings.PROXY_URL:
        try:
            test_response = await http_client.get("https://httpbin.org/ip", timeout=settings.HEALTH_CHECK_TIMEOUT)
            if test_response.status_code == 200:
                health_status["checks"]["proxy"] = {
                    "status": "ok",
                    "message": "Proxy functional"
                }
            else:
                health_status["checks"]["proxy"] = {
                    "status": "error",
                    "message": "Proxy not responding"
                }
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["checks"]["proxy"] = {
                "status": "error",
                "message": f"Proxy error: {str(e)}"
            }
            health_status["status"] = "degraded"
    else:
        health_status["checks"]["proxy"] = {
            "status": "disabled",
            "message": "No proxy configured"
        }

    total_time = round((time.time() - start_time) * 1000)
    health_status["total_response_time_ms"] = total_time

    return health_status
