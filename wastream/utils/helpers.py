import json
import re
import unicodedata
from base64 import b64encode, b64decode
from typing import Optional, Dict, Any
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from wastream.utils.languages import normalize_language
from wastream.utils.quality import normalize_quality


# ===========================
# Text Normalization
# ===========================
def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    text = "".join(c if c.isalnum() or c.isspace() else " " for c in text)
    text = " ".join(text.split())

    return text.strip()


# ===========================
# Configuration Encoding
# ===========================
def encode_config_to_base64(config: Dict[str, Any]) -> str:
    return b64encode(json.dumps(config).encode()).decode()


# ===========================
# Cache Key Creation
# ===========================
def create_cache_key(cache_type: str, title: str, year: Optional[str] = None) -> str:
    cache_key = f"{cache_type}:{quote_plus(title.lower())}"
    if year:
        cache_key += f":{year}"
    return cache_key


# ===========================
# URL Formatting
# ===========================
def format_url(url: str, base_url: str) -> str:
    if not url:
        return ""

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if url.startswith("/"):
        return f"{base_url}{url}"

    return f"{base_url}/{url}"


# ===========================
# URL Parameter Encoding
# ===========================
def quote_url_param(param: str) -> str:
    return quote_plus(param)


# ===========================
# Filename Extraction and Decoding
# ===========================
def extract_and_decode_filename(url: str) -> Optional[str]:
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        filename_encoded = query_params.get('fn', [None])[0]

        if filename_encoded:
            filename_unquoted = unquote(filename_encoded)
            decoded_filename = b64decode(filename_unquoted).decode('utf-8')
            return decoded_filename
    except Exception:
        pass
    return None


# ===========================
# Movie Info Parsing
# ===========================
def parse_movie_info(decoded_filename: str) -> Dict[str, str]:
    quality = "Unknown"
    language = "Unknown"

    if "[" in decoded_filename and "]" in decoded_filename:
        start = decoded_filename.find("[")
        end = decoded_filename.find("]", start)
        if start != -1 and end != -1:
            quality = decoded_filename[start + 1:end].strip()

    if " - " in decoded_filename:
        parts = decoded_filename.split(" - ")
        if len(parts) > 1:
            language = parts[1].strip()

    return {
        "quality": normalize_quality(quality),
        "language": normalize_language(language)
    }


# ===========================
# Series Info Parsing
# ===========================
def parse_series_info(decoded_filename: str) -> Dict[str, str]:
    season = "1"
    episode = "1"
    quality = "Unknown"
    language = "Unknown"

    season_match = re.search(r"Saison (\d+)", decoded_filename)
    if season_match:
        season = season_match.group(1)

    episode_match = re.search(r"Épisode (\d+)", decoded_filename)
    if episode_match:
        episode = episode_match.group(1)

    if "[" in decoded_filename and "]" in decoded_filename:
        start = decoded_filename.find("[")
        end = decoded_filename.find("]", start)
        if start != -1 and end != -1:
            bracket_content = decoded_filename[start + 1:end].strip()

            parts = bracket_content.split()

            if len(parts) >= 1:
                language = parts[0]

                if len(parts) > 1:
                    quality_parts = parts[1:]
                    quality = " ".join(quality_parts)

    return {
        "season": season,
        "episode": episode,
        "quality": normalize_quality(quality),
        "language": normalize_language(language)
    }


# ===========================
# Size Normalization
# ===========================
def normalize_size(raw_size: str) -> str:
    if not raw_size:
        return "Unknown"

    normalized = str(raw_size).strip()

    if normalized.upper() in ["N/A", "NULL", "UNKNOWN", "INCONNU", ""]:
        return "Unknown"

    normalized_upper = normalized.upper()
    normalized_upper = normalized_upper.replace(",", ".")
    normalized_upper = normalized_upper.replace(" GO", " GB")
    normalized_upper = normalized_upper.replace(" MO", " MB")
    normalized_upper = normalized_upper.replace(" KO", " KB")

    return normalized_upper


# ===========================
# Size Parsing to GB
# ===========================
def parse_size_to_gb(size_str: str) -> Optional[float]:
    if not size_str or size_str == "Unknown":
        return None

    size_upper = size_str.upper().strip()

    match = re.match(r"([\d.]+)\s*(GB|MB|KB)", size_upper)
    if not match:
        return None

    try:
        value = float(match.group(1))
        unit = match.group(2)

        if unit == "GB":
            return value
        elif unit == "MB":
            return value / 1024.0
        elif unit == "KB":
            return value / (1024.0 * 1024.0)
        else:
            return None

    except (ValueError, AttributeError):
        return None


# ===========================
# Results Deduplication and Sorting
# ===========================
def deduplicate_and_sort_results(results: list, quality_sort_key_func) -> list:
    seen_links = set()
    deduplicated = []

    for result in results:
        link_key = result.get("link", "")
        if link_key and link_key not in seen_links:
            seen_links.add(link_key)
            deduplicated.append(result)

    deduplicated.sort(key=quality_sort_key_func)
    return deduplicated


# ===========================
# Display Name Builder
# ===========================
def build_display_name(title: str, year: Optional[str] = None, language: str = "Unknown",
                       quality: str = "Unknown", season: Optional[str] = None,
                       episode: Optional[str] = None) -> str:
    display_name = title.replace(" ", ".")

    if year and str(year) not in title:
        display_name += f".{year}"

    if season:
        if episode:
            season_padded = str(season).zfill(2)
            episode_padded = str(episode).zfill(2)
            display_name += f".S{season_padded}E{episode_padded}"
        else:
            season_padded = str(season).zfill(2)
            display_name += f".S{season_padded}"

    if language and language != "Unknown":
        if language.startswith("Multi (") and language.endswith(")"):
            langs_str = language[7:-1]
            langs = [lang.strip() for lang in langs_str.split(",")]
            display_name += ".MULTi." + ".".join(langs)
        else:
            display_name += f".{language.replace(' ', '.')}"

    if quality and quality != "Unknown":
        quality_cleaned = quality.replace(" ", ".").replace("(", "").replace(")", "")
        display_name += f".{quality_cleaned}"

    return display_name


# ===========================
# Debrid API Key Retrieval
# ===========================
def get_debrid_api_key(config: Dict[str, Any], service_name: str) -> str:
    debrid_services = config.get("debrid_services", [])
    for entry in debrid_services:
        if entry.get("service") == service_name:
            return entry.get("api_key", "")
    return ""


# ===========================
# Debrid Services Retrieval
# ===========================
def get_debrid_services(config: Dict[str, Any]) -> list:
    return config.get("debrid_services", [])
