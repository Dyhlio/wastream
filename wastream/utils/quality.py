from typing import Dict, Any

# ===========================
# Quality Sort Constants
# ===========================
QUALITY_SORT_KEY_UNKNOWN = 999

# ===========================
# Available Resolutions
# ===========================
AVAILABLE_RESOLUTIONS = [
    "2160p",
    "1080p",
    "720p",
    "480p",
    "Unknown"
]

# ===========================
# Resolution Extraction
# ===========================
def extract_resolution(quality: str) -> str:
    if not quality or quality == "Unknown":
        return "Unknown"

    quality_upper = str(quality).strip().upper()

    if "2160" in quality_upper or "4K" in quality_upper or "UHD" in quality_upper or "ULTRA" in quality_upper:
        return "2160p"

    elif "1080" in quality_upper or (quality_upper == "HD" and "720" not in quality_upper):
        return "1080p"

    elif "720" in quality_upper:
        return "720p"

    elif "480" in quality_upper:
        return "480p"

    else:
        return "Unknown"

# ===========================
# Quality Normalization
# ===========================
def normalize_quality(raw_quality: str) -> str:
    if not raw_quality or raw_quality is None:
        return "Unknown"

    normalized = str(raw_quality).strip()

    if normalized.upper() in ["N/A", "NULL", "UNKNOWN", "INCONNU", ""]:
        return "Unknown"

    return normalized

# ===========================
# Quality Sort Key
# ===========================
def quality_sort_key(item: Dict[str, Any]) -> tuple:
    quality_raw = item.get("quality", "")

    if not quality_raw or quality_raw is None or str(quality_raw).strip().upper() in ["N/A", "NULL", "UNKNOWN", "INCONNU", ""]:
        return (QUALITY_SORT_KEY_UNKNOWN, QUALITY_SORT_KEY_UNKNOWN)

    quality_upper = str(quality_raw).strip().upper()

    is_2160p = "2160" in quality_upper or "4K" in quality_upper or "UHD" in quality_upper or "ULTRA" in quality_upper
    is_1080p = "1080" in quality_upper or (quality_upper == "HD" and "720" not in quality_upper)
    is_720p = "720" in quality_upper

    if "REMUX" in quality_upper:
        release_type = 0

    elif "BLURAY" in quality_upper or "BLU-RAY" in quality_upper or "BDRIP" in quality_upper or "BRRIP" in quality_upper or "BD-RIP" in quality_upper or "BR-RIP" in quality_upper:
        release_type = 1

    elif "WEB-DL" in quality_upper or "WEBDL" in quality_upper or ("WEB" in quality_upper and "WEBRIP" not in quality_upper):
        release_type = 2

    elif "HDLIGHT" in quality_upper or "LIGHT" in quality_upper:
        release_type = 3

    elif "WEBRIP" in quality_upper or "WEB-RIP" in quality_upper:
        release_type = 4

    elif "HDRIP" in quality_upper or "HD-RIP" in quality_upper:
        release_type = 5

    elif "HDTV" in quality_upper or "HD-TV" in quality_upper:
        release_type = 6

    elif "DVDRIP" in quality_upper or "DVD-RIP" in quality_upper:
        release_type = 7

    elif "TVRIP" in quality_upper or "TV-RIP" in quality_upper:
        release_type = 8

    else:
        release_type = 99

    if is_2160p:
        return (0, release_type)
    elif is_1080p:
        return (1, release_type)
    elif is_720p:
        return (2, release_type)
    else:
        return (99, release_type)
