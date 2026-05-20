# ══════════════════════════════════════════════════
# utils/logger.py - 日志配置
# ══════════════════════════════════════════════════
from loguru import logger
import sys
from pathlib import Path

def setup_logger(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(log_dir / "seai.log", rotation="1 day", retention="7 days", level="DEBUG")