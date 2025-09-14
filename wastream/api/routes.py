import time
from fastapi import APIRouter, Request, Query, Path
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, HTMLResponse
from typing import Optional

from wastream.core.config import ADDON_MANIFEST, WAWACITY_URL, PROXY_URL, CUSTOM_HTML, ADDON_PASSWORD, ADDON_NAME
from wastream.utils.validators import validate_config
from wastream.services.stream import stream_service
from wastream.services.alldebrid import alldebrid_service
from wastream.services.tmdb import tmdb_service
from wastream.services.kitsu import kitsu_service
from wastream.scrapers.movie import movie_scraper
from wastream.scrapers.series import series_scraper
from wastream.scrapers.anime import anime_scraper
from wastream.utils.logger import logger
from wastream.utils.http_client import http_client
from wastream.utils.database import database

router = APIRouter()

# === WEB INTERFACE ENDPOINTS ===

# Redirect root to configuration page
@router.get("/", summary="Accueil", description="Redirection automatique vers la page de configuration")
async def root():
    return RedirectResponse("/configure")

# Serve configuration page
@router.get("/configure", summary="Configuration", description="Interface web pour configurer vos clés AllDebrid et token d'accès TMDB")
async def configure():
    with open("wastream/public/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    
    html_content = html_content.replace("{{CUSTOM_HTML}}", CUSTOM_HTML)
    html_content = html_content.replace("{{ADDON_NAME}}", ADDON_NAME)
    
    return HTMLResponse(content=html_content)

# Serve reconfiguration page
@router.get("/{b64config}/configure", summary="Reconfigurer", description="Modifier la configuration existante avec vos nouvelles clés API")
async def configure_addon(
    b64config: str = Path(..., description="Configuration encodée (base64) avec clés AllDebrid/token TMDB")
):
    with open("wastream/public/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    
    html_content = html_content.replace("{{CUSTOM_HTML}}", CUSTOM_HTML)
    html_content = html_content.replace("{{ADDON_NAME}}", ADDON_NAME)
    
    return HTMLResponse(content=html_content)

# === STREMIO ADDON ENDPOINTS ===

# Provide Stremio addon manifest
@router.get("/{b64config}/manifest.json", summary="Manifest Stremio", description="Informations de l'addon pour l'installation dans Stremio")
async def get_manifest(
    b64config: str = Path(..., description="Configuration encodée (base64) avec clés AllDebrid/token TMDB")
):
    return JSONResponse(content=ADDON_MANIFEST)

# Search and return streams for content
@router.get("/{b64config}/stream/{content_type}/{content_id}", 
           summary="Rechercher des streams", 
           description="Trouve et retourne les liens de streaming pour un film ou une série depuis Wawacity")
async def get_streams(
    request: Request,
    b64config: str = Path(..., description="Configuration encodée (base64) avec clés AllDebrid/token TMDB"),
    content_type: str = Path(..., description="Type de contenu: 'movie' ou 'series'"),
    content_id: str = Path(..., description="ID IMDB (films) ou IMDB:saison:episode (séries)")
):
    config = validate_config(b64config)
    if not config:
        logger.log("API", "ERROR: Invalid configuration - Check format or missing/empty keys")
        return JSONResponse(content={"streams": []})
    
    content_id_formatted = content_id.replace(".json", "")
    logger.log("API", f"Stream request: {content_type}/{content_id_formatted}")
    
    try:
        base_url = str(request.base_url).rstrip('/')
        
        streams = await stream_service.get_streams(
            content_type=content_type,
            content_id=content_id_formatted,
            config=config,
            base_url=base_url
        )
        
        return JSONResponse(content={
            "streams": streams,
            "cacheMaxAge": 1
        })
        
    except Exception as e:
        logger.log("API", f"ERROR: Stream request failed: {e}")
        return JSONResponse(content={"streams": []})

# === UTILITY ENDPOINTS ===

# Resolve dl-protect links to direct URLs
@router.get("/resolve", 
           summary="Résoudre un lien", 
           description="Convertit un lien dl-protect en lien direct via AllDebrid pour le streaming")
async def resolve(
    link: str = Query(..., description="Lien dl-protect à convertir (ex: https://dl-protect.link/abc123)"),
    b64config: str = Query(..., description="Configuration encodée contenant votre clé API AllDebrid")
):
    config = validate_config(b64config)
    if not config:
        return FileResponse("wastream/public/error.mp4")
    
    apikey = config.get("alldebrid", "")
    if not apikey:
        return FileResponse("wastream/public/error.mp4")
    
    direct_link = await stream_service.resolve_link(link, apikey)
    
    if direct_link and direct_link != "LINK_DOWN":
        return RedirectResponse(url=direct_link, status_code=302)
    elif direct_link == "LINK_DOWN":
        return FileResponse("wastream/public/link_down_error.mp4")
    else:
        return FileResponse("wastream/public/error.mp4")

# === DEBUG ENDPOINTS ===

# Test metadata retrieval from TMDB and Kitsu
@router.get("/debug/test-metadata", 
           summary="Test Métadonnées", 
           description="Teste la récupération de métadonnées depuis TMDB ou Kitsu selon l'ID")
async def debug_metadata(
    content_id: str = Query(..., description="ID du contenu (tt1234567 pour IMDB ou kitsu:1234 pour Kitsu)"),
    tmdb_key: str = Query(None, description="TMDB Access Token (requis pour les IDs IMDB)")
):
    try:
        if content_id.startswith("kitsu:"):
            kitsu_id = content_id.split(":")[1]
            metadata = await kitsu_service.get_metadata(kitsu_id)
            
            if metadata:
                return {
                    "content_id": content_id,
                    "service": "kitsu",
                    "title": metadata.get("title"),
                    "year": metadata.get("year"),
                    "aliases": metadata.get("aliases", []),
                    "status": "success"
                }
            else:
                return {
                    "content_id": content_id,
                    "service": "kitsu", 
                    "error": "No metadata found",
                    "status": "failed"
                }
        else:
            if not tmdb_key:
                return {
                    "content_id": content_id,
                    "service": "tmdb",
                    "error": "TMDB Access Token required for IDs IMDB",
                    "status": "error"
                }
                
            metadata = await tmdb_service.get_enhanced_metadata(content_id, tmdb_key)
            
            if metadata:
                return {
                    "content_id": content_id,
                    "service": "tmdb",
                    "titles": metadata.get("titles", []),
                    "year": metadata.get("year"),
                    "content_type": metadata.get("content_type"),
                    "status": "success"
                }
            else:
                return {
                    "content_id": content_id,
                    "service": "tmdb",
                    "error": "No metadata found", 
                    "status": "failed"
                }
                
    except Exception as e:
        service = "kitsu" if content_id.startswith("kitsu:") else "tmdb"
        return {
            "content_id": content_id,
            "service": service,
            "error": str(e),
            "status": "error"
        }

# Test Wawacity search functionality
@router.get("/debug/test-search", 
           summary="Test de recherche", 
           description="Teste la recherche Wawacity directement")
async def debug_search(
    title: str = Query(..., description="Titre du film, série ou anime à rechercher"),
    year: Optional[str] = Query(None, description="Année de sortie (optionnel)"),
    type: str = Query(..., description="Type de contenu: 'film', 'serie' ou 'anime'")
):
    try:
        if type == "anime":
            results = await anime_scraper.search(title, year, None)
        elif type == "serie":
            results = await series_scraper.search(title, year, None)
        else:
            results = await movie_scraper.search(title, year, None)
        
        return {
            "title": title,
            "year": year,
            "type": type,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {
            "error": str(e),
            "title": title,
            "year": year,
            "type": type
        }

# Test AllDebrid link conversion
@router.get("/debug/test-alldebrid", 
           summary="Test AllDebrid", 
           description="Teste la conversion d'un lien dl-protect via votre clé AllDebrid")
async def debug_alldebrid(
    link: str = Query(..., description="Lien dl-protect à convertir (ex: https://dl-protect.link/abc123)"),
    apikey: str = Query(..., description="Clé API AllDebrid")
):
    try:
        result = await alldebrid_service.convert_link(link, apikey)
        return {
            "input_link": link,
            "alldebrid_link": result,
            "status": "success" if result and result != "LINK_DOWN" else "failed"
        }
    except Exception as e:
        return {
            "input_link": link,
            "error": str(e),
            "status": "error"
        }



# === AUTHENTICATION ENDPOINTS ===

# Get password configuration status
@router.get("/password-config", 
           summary="Configuration mot de passe", 
           description="Retourne si un mot de passe est requis pour la configuration")
async def get_password_config():
    return JSONResponse(content={
        "password_required": bool(ADDON_PASSWORD.strip())
    })

# Verify provided password
@router.post("/verify-password", 
            summary="Vérification mot de passe", 
            description="Vérifie si le mot de passe fourni est valide")
async def verify_password(password: str = Query(..., description="Mot de passe à vérifier")):
    if not ADDON_PASSWORD.strip():
        return JSONResponse(content={"valid": True})
    
    valid_passwords = [pwd.strip() for pwd in ADDON_PASSWORD.split(",") if pwd.strip()]
    is_valid = password in valid_passwords
    
    return JSONResponse(content={"valid": is_valid})

# === HEALTH CHECK ENDPOINT ===

# Check system health and connectivity
@router.get("/health", 
           summary="État de santé", 
           description="Teste l'état du serveur, de Wawacity, de la base de données et du proxy")
async def health_check():
    
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "version": ADDON_MANIFEST["version"],
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
    
    wastream_start = time.time()
    try:
        response = await http_client.get(WAWACITY_URL, timeout=5)
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
    
    if PROXY_URL:
        try:
            test_response = await http_client.get("https://httpbin.org/ip", timeout=5)
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