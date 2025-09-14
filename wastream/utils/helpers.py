import json
import re
import unicodedata
from typing import Optional, Dict, Any
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from base64 import b64encode, b64decode

# Normalize text for comparison
def normalize_text(text: str) -> str:
    if not text:
        return ""
    
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    text = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in text)
    text = ' '.join(text.split())
    
    return text.strip()

# Encode configuration to base64
def encode_config_to_base64(config: Dict[str, Any]) -> str:
    return b64encode(json.dumps(config).encode()).decode()

# Create cache key from parameters
def create_cache_key(cache_type: str, title: str, year: Optional[str] = None) -> str:
    cache_key = f"{cache_type}:{quote_plus(title.lower())}"
    if year:
        cache_key += f":{year}"
    return cache_key

# Extract filename from dl-protect link
def extract_filename_from_link(url: str, link_text: str) -> str:
    original_filename = link_text.split(":")[-1].strip() if ":" in link_text else link_text.strip()
    
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        fn_encoded = query_params.get('fn', [None])[0]
        
        if fn_encoded:
            fn_unquoted = unquote(fn_encoded)
            decoded_fn = b64decode(fn_unquoted).decode('utf-8')
            return decoded_fn if decoded_fn else original_filename
    except Exception:
        pass
    
    return original_filename

# Format URL with base URL
def format_url(url: str, base_url: str) -> str:
    if not url:
        return ""
    
    if url.startswith("http://") or url.startswith("https://"):
        return url
    
    if url.startswith("/"):
        return f"{base_url}{url}"
    
    return url

# Encode URL parameter
def quote_url_param(param: str) -> str:
    return quote_plus(param)

# Extract and decode filename from dl-protect URL
def extract_and_decode_filename(url: str) -> Optional[str]:
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        fn_encoded = query_params.get('fn', [None])[0]
        
        if fn_encoded:
            fn_unquoted = unquote(fn_encoded)
            decoded_fn = b64decode(fn_unquoted).decode('utf-8')
            return decoded_fn
    except Exception:
        pass
    return None

# Parse movie info from decoded filename
def parse_movie_info(decoded_filename: str) -> Dict[str, str]:
    quality = "N/A"
    language = "N/A"
    
    if '[' in decoded_filename and ']' in decoded_filename:
        start = decoded_filename.find('[')
        end = decoded_filename.find(']', start)
        if start != -1 and end != -1:
            quality = decoded_filename[start+1:end].strip()
    
    if ' - ' in decoded_filename:
        parts = decoded_filename.split(' - ')
        if len(parts) > 1:
            language = parts[1].strip()
    
    return {
        "quality": quality,
        "language": language
    }

# Parse series info from decoded filename
def parse_series_info(decoded_filename: str) -> Dict[str, str]:
    season = "1"
    episode = "1"
    quality = "N/A"
    language = "N/A"
    
    season_match = re.search(r"Saison (\d+)", decoded_filename)
    if season_match:
        season = season_match.group(1)
    
    episode_match = re.search(r"Épisode (\d+)", decoded_filename)
    if episode_match:
        episode = episode_match.group(1)
    
    if '[' in decoded_filename and ']' in decoded_filename:
        start = decoded_filename.find('[')
        end = decoded_filename.find(']', start)
        if start != -1 and end != -1:
            bracket_content = decoded_filename[start+1:end].strip()
            
            parts = bracket_content.split()
            
            if len(parts) >= 1:
                language = parts[0]
                
                if len(parts) > 1:
                    quality_parts = parts[1:]
                    quality = " ".join(quality_parts)
    
    return {
        "season": season,
        "episode": episode, 
        "quality": quality,
        "language": language
    }