import binascii
import json
from base64 import b64decode
from typing import Optional, Dict

from wastream.utils.logger import api_logger
from wastream.utils.quality import AVAILABLE_RESOLUTIONS

# ===========================
# Configuration Validation
# ===========================
def validate_config(config_base64: Optional[str]) -> Optional[Dict[str, str]]:
    if not config_base64:
        api_logger.debug("Empty config provided")
        return None

    try:
        api_logger.debug("Validating configuration")
        decoded_bytes = b64decode(config_base64, validate=True)
        decoded_str = decoded_bytes.decode('utf-8')

        config_dict = json.loads(decoded_str)

        if not isinstance(config_dict, dict):
            api_logger.debug("Config is not a dict")
            return None

        if "tmdb_api_token" not in config_dict or not config_dict["tmdb_api_token"]:
            api_logger.debug("Missing or empty tmdb_api_token")
            return None

        if "debrid_service" not in config_dict or not config_dict["debrid_service"]:
            api_logger.debug("Missing or empty debrid_service")
            return None

        if "debrid_api_key" not in config_dict or not config_dict["debrid_api_key"]:
            api_logger.debug("Missing or empty debrid_api_key")
            return None

        if config_dict["debrid_service"] not in ["alldebrid", "torbox"]:
            api_logger.debug(f"Invalid debrid_service: {config_dict['debrid_service']}")
            return None

        if "excluded_keywords" in config_dict:
            excluded_keywords = config_dict["excluded_keywords"]
            if not isinstance(excluded_keywords, list):
                return None

            for keyword in excluded_keywords:
                if not isinstance(keyword, str):
                    return None
        else:
            config_dict["excluded_keywords"] = []

        if "languages" in config_dict:
            languages = config_dict["languages"]
            if not isinstance(languages, list):
                return None

            for lang in languages:
                if not isinstance(lang, str):
                    return None
        else:
            config_dict["languages"] = []

        if "resolutions" in config_dict:
            resolutions = config_dict["resolutions"]
            if not isinstance(resolutions, list):
                return None

            for res in resolutions:
                if not isinstance(res, str):
                    return None
        else:
            config_dict["resolutions"] = AVAILABLE_RESOLUTIONS

        if "max_results_per_resolution" in config_dict:
            max_results = config_dict["max_results_per_resolution"]
            if not isinstance(max_results, int) or max_results < 0:
                return None
        else:
            config_dict["max_results_per_resolution"] = 0

        if "max_size_gb" in config_dict:
            max_size = config_dict["max_size_gb"]
            if not isinstance(max_size, (int, float)) or max_size < 0:
                return None
            config_dict["max_size_gb"] = float(max_size)
        else:
            config_dict["max_size_gb"] = 0.0

        api_logger.debug("Configuration validated successfully")
        return config_dict

    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
        api_logger.debug(f"Config validation failed: {type(e).__name__}")
        return None

# ===========================
# Media Info Extraction
# ===========================
def extract_media_info(content_id: str, content_type: str) -> Dict[str, Optional[str]]:
    content_id_formatted = content_id.replace(".json", "")

    if content_id_formatted.startswith("kitsu:"):
        parts = content_id_formatted.split(":")
        return {
            "kitsu_id": parts[1] if len(parts) > 1 else "",
            "episode": parts[2] if len(parts) > 2 else None,
            "season": "1",
            "imdb_id": None
        }

    if content_type == "series" and ":" in content_id_formatted:
        parts = content_id_formatted.split(":")
        return {
            "imdb_id": parts[0],
            "season": parts[1] if len(parts) > 1 else "1",
            "episode": parts[2] if len(parts) > 2 else "1",
            "kitsu_id": None
        }

    return {
        "imdb_id": content_id_formatted,
        "season": None,
        "episode": None,
        "kitsu_id": None
    }
