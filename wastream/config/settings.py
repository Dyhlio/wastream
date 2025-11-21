from typing import Optional, List, Dict, Any
from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    # ===========================
    # Addon Customization
    # ===========================
    ADDON_ID: Optional[str] = "community.wastream"
    ADDON_NAME: Optional[str] = "WAStream"

    # ===========================
    # Server Configuration
    # ===========================
    PORT: Optional[int] = 7000

    # ===========================
    # Source Configuration
    # ===========================
    WAWACITY_URL: Optional[str] = None
    DARKI_API_URL: Optional[str] = None
    DARKI_API_KEY: Optional[str] = None

    # ===========================
    # Pagination Configuration
    # ===========================
    WAWACITY_MAX_SEARCH_PAGES: Optional[int] = 3
    DARKI_API_MAX_LINK_PAGES: Optional[int] = 5

    # ===========================
    # Database Configuration
    # ===========================
    DATABASE_VERSION: str = "1.0"
    DATABASE_TYPE: Optional[str] = "sqlite"
    DATABASE_PATH: Optional[str] = "/app/data/wastream.db"
    DATABASE_URL: Optional[str] = ""

    # ===========================
    # Cache Configuration
    # ===========================
    CONTENT_CACHE_TTL: Optional[int] = 3600
    DEAD_LINK_TTL: Optional[int] = 2592000

    # ===========================
    # Lock Configuration
    # ===========================
    SCRAPE_LOCK_TTL: Optional[int] = 300
    SCRAPE_WAIT_TIMEOUT: Optional[int] = 30

    # ===========================
    # HTTP Timeout Configuration
    # ===========================
    HTTP_TIMEOUT: Optional[int] = 15
    METADATA_TIMEOUT: Optional[int] = 10
    HEALTH_CHECK_TIMEOUT: Optional[int] = 5

    # ===========================
    # Debrid Services Configuration
    # ===========================
    DEBRID_MAX_RETRIES: Optional[int] = 5
    DEBRID_RETRY_DELAY_SECONDS: int = 4
    STREAM_REQUEST_TIMEOUT: int = 20
    DEBRID_CACHE_CHECK_HTTP_TIMEOUT: Optional[int] = 3
    DEBRID_HTTP_ERROR_MAX_RETRIES: Optional[int] = 5
    DEBRID_HTTP_ERROR_RETRY_DELAY: Optional[int] = 1

    # ===========================
    # AllDebrid Configuration
    # ===========================
    ALLDEBRID_API_URL: str = "https://api.alldebrid.com/v4"
    ALLDEBRID_BATCH_SIZE: int = 12
    ALLDEBRID_SUPPORTED_HOSTS: List[str] = ["1fichier", "turbobit", "rapidgator"]
    ALLDEBRID_SUPPORTED_SOURCES: List[str] = ["wawacity", "darki-api"]

    # ===========================
    # TorBox Configuration
    # ===========================
    TORBOX_API_URL: str = "https://api.torbox.app/v1/api"
    TORBOX_SUPPORTED_HOSTS: List[str] = ["1fichier", "turbobit", "rapidgator", "dailyuploads", "sendcm", "darkibox"]
    TORBOX_SUPPORTED_SOURCES: List[str] = ["darki-api"]

    # ===========================
    # Premiumize Configuration
    # ===========================
    PREMIUMIZE_API_URL: str = "https://www.premiumize.me/api"
    PREMIUMIZE_SUPPORTED_HOSTS: List[str] = ["1fichier", "turbobit", "rapidgator", "dailyuploads"]
    PREMIUMIZE_SUPPORTED_SOURCES: List[str] = ["darki-api"]

    # ===========================
    # TMDB Configuration
    # ===========================
    TMDB_API_URL: str = "https://api.themoviedb.org/3"

    # ===========================
    # Kitsu Configuration
    # ===========================
    KITSU_API_URL: str = "https://kitsu.io/api/edge"
    KITSU_ALIAS_URL: str = "https://find-my-anime.dtimur.de/api"

    # ===========================
    # Proxy Configuration
    # ===========================
    PROXY_URL: Optional[str] = None

    # ===========================
    # Security Configuration
    # ===========================
    ADDON_PASSWORD: Optional[str] = ""

    # ===========================
    # Logging Configuration
    # ===========================
    LOG_LEVEL: Optional[str] = "DEBUG"

    # ===========================
    # Interface Customization
    # ===========================
    CUSTOM_HTML: Optional[str] = ""

    # ===========================
    # Internal Configuration
    # ===========================
    CLEANUP_INTERVAL: int = 60

    # ===========================
    # Field Validators
    # ===========================
    @field_validator("WAWACITY_URL", "DARKI_API_URL", "PROXY_URL")
    @classmethod
    def normalize_urls(cls, v):
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def normalize_log_level(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

    # ===========================
    # Computed Properties
    # ===========================
    @computed_field
    @property
    def ADDON_MANIFEST(self) -> Dict[str, Any]:
        return {
            "id": self.ADDON_ID,
            "name": self.ADDON_NAME,
            "version": "2.3.1",
            "description": "Stremio addon to convert DDL to streams via debrid services",
            "catalogs": [],
            "resources": ["stream"],
            "types": ["movie", "series", "anime"],
            "idPrefixes": ["tt", "kitsu"],
            "behaviorHints": {
                "configurable": True
            },
            "logo": "https://raw.githubusercontent.com/Dyhlio/wastream/refs/heads/main/wastream/public/wastream-logo.jpg",
            "background": "https://raw.githubusercontent.com/Dyhlio/wastream/refs/heads/main/wastream/public/wastream-background.png"
        }

    def get_database_url(self) -> str:
        if self.DATABASE_TYPE == "sqlite":
            return f"sqlite:///{self.DATABASE_PATH}"
        return f"postgresql://{self.DATABASE_URL}"


# ===========================
# Settings Instance
# ===========================
settings = Settings()
