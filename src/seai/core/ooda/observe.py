"""Observe stage — gathers situation context from Memory, KG, and EventBus."""
import asyncio
from typing import Any

from .types import (
    Intent,
    SituationContext,
    MemoryHit,
    KGNode,
    BusEvent,
    CircuitStatus,
)
from .providers import MemoryProvider, KGProvider, EventBusProvider


class ObserveStage:
    """Gathers environmental context from all data sources in parallel."""

    def __init__(
        self,
        memory: MemoryProvider,
        kg: KGProvider,
        event_bus: EventBusProvider,
        timeout_ms: int = 10_000,
    ):
        self._memory = memory
        self._kg = kg
        self._event_bus = event_bus
        self._timeout_ms = timeout_ms
        self._session_summary: str | None = None
        self._user_profile: dict = {}

    async def gather(
        self,
        intent: Intent | SituationContext,
        previous_result: Any = None,
        session_id: str = "",
    ) -> SituationContext:
        # Extract intent from either form
        if isinstance(intent, SituationContext):
            situation_intent = intent.intent
            carry = intent
        else:
            situation_intent = intent
            carry = None

        timeout_s = self._timeout_ms / 1000.0

        # Fire all three data sources in parallel with timeout
        memories_task = asyncio.create_task(self._query_memory(situation_intent))
        kg_task = asyncio.create_task(self._query_kg(situation_intent))
        # EventBus snapshot is sync
        events, circuits = self._query_event_bus()

        try:
            memories = await asyncio.wait_for(memories_task, timeout=timeout_s)
        except asyncio.TimeoutError:
            memories = []
        try:
            kg_nodes = await asyncio.wait_for(kg_task, timeout=timeout_s)
        except asyncio.TimeoutError:
            kg_nodes = []

        last_tool_results = carry.last_tool_results if carry else {}

        return SituationContext(
            intent=situation_intent,
            related_memories=memories,
            related_knowledge=kg_nodes,
            recent_events=events,
            circuit_state={
                topic: CircuitStatus(state=cs.state, failures=cs.failures)
                for topic, cs in circuits.items()
            },
            last_tool_results=last_tool_results,
            session_summary=self._session_summary,
            user_profile=self._user_profile,
            turn_count=0,
        )

    async def _query_memory(self, intent: Intent) -> list[MemoryHit]:
        try:
            results = await self._memory.search(intent.raw)
            hit_list = []
            for r in results:
                if isinstance(r, MemoryHit):
                    hit_list.append(r)
                else:
                    hit_list.append(MemoryHit(
                        content=getattr(r, "content", str(r)),
                        score=getattr(r, "score", 0.0),
                        mem_type=getattr(r, "mem_type", "unknown"),
                    ))
            # Side-load profile
            try:
                self._user_profile = await self._memory.get_profile("default")
                self._session_summary = await self._memory.get_session_summary(session_id="")
            except Exception:
                self._user_profile = {}
                self._session_summary = None
            return hit_list
        except Exception:
            self._session_summary = None
            return []

    async def _query_kg(self, intent: Intent) -> list[KGNode]:
        try:
            entities = [intent.raw[:50]]
            results = await self._kg.query(entities)
            node_list = []
            for r in results:
                if isinstance(r, KGNode):
                    node_list.append(r)
                else:
                    node_list.append(KGNode(
                        entity=getattr(r, "entity", str(r)),
                        relation=getattr(r, "relation", ""),
                        target=getattr(r, "target", ""),
                        confidence=getattr(r, "confidence", 0.0),
                    ))
            return node_list
        except Exception:
            return []

    def _query_event_bus(self) -> tuple[list[BusEvent], dict[str, Any]]:
        try:
            events, circuits = self._event_bus.snapshot()
            event_list = []
            for e in events:
                if isinstance(e, BusEvent):
                    event_list.append(e)
                else:
                    event_list.append(BusEvent(
                        topic=getattr(e, "topic", "unknown"),
                        data=getattr(e, "data", {}),
                        ts=getattr(e, "ts", 0.0),
                    ))
            return event_list, circuits
        except Exception:
            return [], {}
