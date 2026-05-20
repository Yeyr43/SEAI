"""Provider protocols for OODA data sources."""
from typing import Protocol, runtime_checkable

from .types import MemoryHit, KGNode, BusEvent, CircuitStatus


@runtime_checkable
class MemoryProvider(Protocol):
    async def search(self, query: str, top_k: int = 5,
                     filter_types: list[str] | None = None) -> list[MemoryHit]: ...
    async def get_profile(self, user_id: str) -> dict: ...
    async def get_session_summary(self, session_id: str) -> str | None: ...


@runtime_checkable
class KGProvider(Protocol):
    async def query(self, entities: list[str], hop: int = 1,
                    relation_types: list[str] | None = None) -> list[KGNode]: ...


@runtime_checkable
class EventBusProvider(Protocol):
    def snapshot(self, topics: list[str] | None = None,
                 max_events: int = 20) -> tuple[list[BusEvent], dict[str, CircuitStatus]]: ...
