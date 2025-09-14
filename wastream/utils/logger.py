import sys
import logging
from loguru import logger

# === CUSTOM LOG LEVELS ===
CUSTOM_LOG_LEVELS = {
    "STARTUP": {"no": 21, "icon": "🚀", "color": "<green>"},
    "SCRAPER": {"no": 22, "icon": "🌐", "color": "<blue>"},
    "API": {"no": 23, "icon": "🔗", "color": "<cyan>"},
    "STREAM": {"no": 24, "icon": "🎬", "color": "<green>"},
    "CACHE": {"no": 25, "icon": "💾", "color": "<white>"},
    "TMDB": {"no": 26, "icon": "🎭", "color": "<magenta>"},
    "ALLDEBRID": {"no": 27, "icon": "☁️", "color": "<blue>"},
    "DATABASE": {"no": 28, "icon": "🗄️", "color": "<yellow>"},
    "LOCK": {"no": 29, "icon": "🔒", "color": "<yellow>"},
    "CLEANUP": {"no": 30, "icon": "🧹", "color": "<white>"},
    "DEAD_LINK": {"no": 31, "icon": "💀", "color": "<red>"},
    "KITSU": {"no": 32, "icon": "🎌", "color": "<magenta>"},
}

# === STANDARD LOG LEVELS ===
STANDARD_LOG_LEVELS = {
    "ERROR": {"icon": "❌", "color": "<red>"},
    "WARNING": {"icon": "⚠️", "color": "<yellow>"},
    "INFO": {"icon": "ℹ️", "color": "<blue>"},
    "DEBUG": {"icon": "🐛", "color": "<white>"},
    "SUCCESS": {"icon": "✅", "color": "<green>"},
}

# Setup logger with custom formatting and levels
def setup_logger(level: str = "INFO"):
    
    logger.remove()
    
    for level_name, level_config in CUSTOM_LOG_LEVELS.items():
        logger.level(
            level_name,
            no=level_config["no"],
            icon=level_config["icon"],
            color=level_config["color"],
        )

    for level_name, level_config in STANDARD_LOG_LEVELS.items():
        logger.level(
            level_name, 
            icon=level_config["icon"], 
            color=level_config["color"]
        )

    log_format = (
        "<white>{time:YYYY-MM-DD}</white> <magenta>{time:HH:mm:ss}</magenta> | "
        "<level>{level.icon} {level}</level> | "
        "<cyan>{module}</cyan>.<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        level=level,
        format=log_format,
        backtrace=False,
        diagnose=False,
        enqueue=True,
        colorize=True
    )


setup_logger("INFO")

logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn.access").propagate = False

logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn").setLevel(logging.CRITICAL)

logging.getLogger("fastapi").setLevel(logging.CRITICAL)