import sys
import logging
from loguru import logger


# ===========================
# Configuration
# ===========================
LOG_LEVEL = "INFO"


# ===========================
# Log Contexts Configuration
# ===========================
CONTEXTS = {
    "ADDON": {"color": "green", "icon": "🚀"},
    "API": {"color": "cyan", "icon": "🔗"},
    "STREAM": {"color": "yellow", "icon": "🎬"},
    "SCRAPER": {"color": "blue", "icon": "🌐"},
    "DEBRID": {"color": "magenta", "icon": "☁️"},
    "METADATA": {"color": "white", "icon": "🎭"},
    "CACHE": {"color": "white", "icon": "💾"},
    "DATABASE": {"color": "yellow", "icon": "🗄️"},
}


# ===========================
# Log Level Icons
# ===========================
LEVEL_ICONS = {
    "DEBUG": "🔍",
    "INFO": "ℹ️ ",
    "ERROR": "❌",
}


# ===========================
# Log Formatter
# ===========================
def format_log(record):
    context = record["extra"].get("context", "ADDON")
    context_data = CONTEXTS.get(context, {"color": "white", "icon": "📦"})
    context_color = context_data["color"]
    context_icon = context_data["icon"]
    level_icon = LEVEL_ICONS.get(record["level"].name, "")

    return (
        "<white>{time:YYYY-MM-DD}</white> "
        "<magenta>{time:HH:mm:ss}</magenta> | "
        f"<level>{level_icon} {{level: <8}}</level> | "
        f"<{context_color}>{context_icon} {{extra[context]: <10}}</{context_color}> | "
        "<level>{message}</level>\n"
    )


# ===========================
# Logger Setup Function
# ===========================
def setup_logger(level: str = "INFO"):
    global LOG_LEVEL
    LOG_LEVEL = level

    logger.remove()

    logger.add(
        sys.stderr,
        level=LOG_LEVEL,
        format=format_log,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )


# ===========================
# Logger Factory
# ===========================
def get_logger(context: str):
    return logger.bind(context=context)


# ===========================
# Logger Instances
# ===========================
addon_logger = get_logger("ADDON")
api_logger = get_logger("API")
stream_logger = get_logger("STREAM")
scraper_logger = get_logger("SCRAPER")
debrid_logger = get_logger("DEBRID")
metadata_logger = get_logger("METADATA")
cache_logger = get_logger("CACHE")
database_logger = get_logger("DATABASE")


# ===========================
# External Loggers Suppression
# ===========================
logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
logging.getLogger("fastapi").setLevel(logging.CRITICAL)
