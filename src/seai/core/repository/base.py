"""
Repository 基类
提供统一的数据访问抽象，封装数据库操作和文件存储操作
"""
from typing import TypeVar, Generic, Optional, List, Dict, Any
from pathlib import Path
import json
from loguru import logger

T = TypeVar("T")


class BaseRepository(Generic[T]):
    def __init__(self):
        self._cache: Dict[str, T] = {}

    def _read_json(self, path: Path, default: Any = None) -> Any:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"读取 JSON 文件失败 [{path}]: {e}")
        return default if default is not None else {}

    def _write_json(self, path: Path, data: Any) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"写入 JSON 文件失败 [{path}]: {e}")
            return False

    def _read_text(self, path: Path, default: str = "") -> str:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取文本文件失败 [{path}]: {e}")
        return default

    def _write_text(self, path: Path, content: str) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"写入文本文件失败 [{path}]: {e}")
            return False

    def clear_cache(self):
        self._cache.clear()