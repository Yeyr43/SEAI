"""
Lazy module import with optional install hint and singleton caching.
"""
import importlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class LazyImport:
    """Lazily import a module on first access, cached globally.

    Usage:
        tiktoken = LazyImport("tiktoken", "pip install tiktoken")
        if tiktoken.available:
            enc = tiktoken.get().get_encoding("cl100k_base")
    """

    _instances: Dict[str, Optional[Any]] = {}

    def __init__(self, module_name: str, install_hint: str = ""):
        self.module_name = module_name
        self.install_hint = install_hint

    def get(self):
        if self.module_name not in self._instances:
            try:
                self._instances[self.module_name] = importlib.import_module(self.module_name)
            except ImportError:
                self._instances[self.module_name] = None
                if self.install_hint:
                    logger.warning("%s not installed. %s", self.module_name, self.install_hint)
        return self._instances[self.module_name]

    @property
    def available(self) -> bool:
        return self.get() is not None
