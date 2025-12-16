from typing import List, Dict
from wastream.utils.logger import stream_logger
from wastream.utils.quality import extract_resolution
from wastream.utils.helpers import parse_size_to_gb


# ===========================
# Language Filtering
# ===========================
def filter_by_languages(results: List[Dict], user_languages: List[str]) -> List[Dict]:
    if not user_languages:
        return results

    filtered_results = []

    for result in results:
        result_language = result.get("language", "Unknown")

        include_result = False

        if result_language.startswith("Multi (") and result_language.endswith(")"):
            multi_langs = result_language[7:-1]
            multi_langs_list = [lang.strip() for lang in multi_langs.split(",")]

            for lang in multi_langs_list:
                if lang in user_languages:
                    include_result = True
                    break
        else:
            if result_language in user_languages:
                include_result = True

        if include_result:
            filtered_results.append(result)

    stream_logger.debug(f"Language filter: {len(results)} → {len(filtered_results)}")
    return filtered_results


# ===========================
# Resolution Filtering
# ===========================
def filter_by_resolutions(results: List[Dict], user_resolutions: List[str]) -> List[Dict]:
    filtered_results = []

    for result in results:
        result_quality = result.get("quality", "Unknown")

        result_resolution = extract_resolution(result_quality)

        if result_resolution in user_resolutions:
            filtered_results.append(result)

    stream_logger.debug(f"Resolution filter: {len(results)} → {len(filtered_results)}")
    return filtered_results


# ===========================
# Results Limiting Per Resolution
# ===========================
def limit_results_per_resolution(results: List[Dict], max_per_resolution: int) -> List[Dict]:
    if max_per_resolution == 0:
        return results

    resolution_groups = {}
    for result in results:
        result_quality = result.get("quality", "Unknown")
        result_resolution = extract_resolution(result_quality)

        if result_resolution not in resolution_groups:
            resolution_groups[result_resolution] = []

        resolution_groups[result_resolution].append(result)

    limited_results = []
    for resolution, group in resolution_groups.items():
        limited_group = group[:max_per_resolution]
        limited_results.extend(limited_group)

    stream_logger.debug(f"Limit per resolution ({max_per_resolution}): {len(results)} → {len(limited_results)}")
    return limited_results


# ===========================
# Maximum Size Filtering
# ===========================
def filter_by_max_size(results: List[Dict], max_size_gb: float) -> List[Dict]:
    if max_size_gb == 0.0:
        return results

    filtered_results = []

    for result in results:
        size_str = result.get("size", "Unknown")

        size_gb = parse_size_to_gb(size_str)

        if size_gb is None:
            continue

        if size_gb <= max_size_gb:
            filtered_results.append(result)

    stream_logger.debug(f"Max size filter ({max_size_gb} GB): {len(results)} → {len(filtered_results)}")
    return filtered_results


# ===========================
# Archive Files Filtering
# ===========================
def filter_archive_files(streams: List[Dict]) -> List[Dict]:
    archive_extensions = ('.rar', '.zip', '.7z', '.tar', '.gz')
    filtered_streams = []

    for stream in streams:
        stream_desc = stream.get("description", "")

        is_archive = False
        if "📁" in stream_desc:
            filename_part = stream_desc.split("📁")[-1].strip().lower()
            is_archive = any(filename_part.endswith(ext) for ext in archive_extensions)

        if not is_archive:
            filtered_streams.append(stream)

    stream_logger.debug(f"Archive filter: {len(streams)} → {len(filtered_streams)}")
    return filtered_streams


# ===========================
# Excluded Keywords Filtering
# ===========================
def filter_excluded_keywords(streams: List[Dict], excluded_keywords: List[str]) -> List[Dict]:
    if not excluded_keywords:
        return streams

    filtered_streams = []

    for stream in streams:
        stream_name = stream.get("name", "").lower()
        stream_desc = stream.get("description", "").lower()
        stream_text = f"{stream_name} {stream_desc}"

        exclude_stream = False
        for keyword in excluded_keywords:
            if keyword.lower() in stream_text:
                exclude_stream = True
                break

        if not exclude_stream:
            filtered_streams.append(stream)

    return filtered_streams


# ===========================
# All Filters Application
# ===========================
def apply_all_filters(results: List[Dict], config: Dict) -> List[Dict]:
    user_languages = config.get("languages", [])
    if user_languages:
        results = filter_by_languages(results, user_languages)

    user_resolutions = config.get("resolutions", [])
    results = filter_by_resolutions(results, user_resolutions)

    max_per_resolution = config.get("max_results_per_resolution", 0)
    results = limit_results_per_resolution(results, max_per_resolution)

    max_size_gb = config.get("max_size_gb", 0.0)
    results = filter_by_max_size(results, max_size_gb)

    return results
