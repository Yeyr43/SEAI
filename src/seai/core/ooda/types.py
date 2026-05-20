"""OODA type definitions — all dataclasses for the four-stage loop."""
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Intent:
    raw: str
    category: str
    confidence: float
    sub_intents: list["Intent"] = field(default_factory=list)
    resolved: bool = False


@dataclass
class MemoryHit:
    content: str
    score: float
    mem_type: str


@dataclass
class KGNode:
    entity: str
    relation: str
    target: str
    confidence: float


@dataclass
class BusEvent:
    topic: str
    data: dict
    ts: float


@dataclass
class CircuitStatus:
    state: str
    failures: int


@dataclass
class SituationContext:
    intent: Intent
    sub_intents: list[Intent] = field(default_factory=list)
    related_memories: list[MemoryHit] = field(default_factory=list)
    related_knowledge: list[KGNode] = field(default_factory=list)
    recent_events: list[BusEvent] = field(default_factory=list)
    circuit_state: dict[str, CircuitStatus] = field(default_factory=dict)
    last_tool_results: dict[str, Any] = field(default_factory=dict)
    session_summary: str | None = None
    context_usage_ratio: float = 0.0
    turn_count: int = 0
    user_profile: dict = field(default_factory=dict)
    active_subtask: str | None = None


# ── Orient output ──

ExecutionStrategy = Literal["SERIAL", "PARALLEL", "BID", "FALLBACK"]


@dataclass
class SubTask:
    description: str
    capability: str


@dataclass
class TaskGoal:
    description: str
    success_criteria: list[str] = field(default_factory=list)


@dataclass
class ActionPlan:
    intent: Intent
    goal: TaskGoal | None = None
    gap_analysis: str = ""
    strategy: ExecutionStrategy = "SERIAL"
    required_capabilities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    sub_tasks: list[SubTask] | None = None
    estimated_tool_calls: int = 1
    estimated_tokens: int = 0
    timeout: int = 30_000
    fallback_conditions: list[str] = field(default_factory=list)
    fallback_strategy: ExecutionStrategy | None = None


# ── Decide output ──

@dataclass
class RetryPolicy:
    max_retries: int = 0
    backoff: float = 1.0


@dataclass
class ToolBinding:
    name: str
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class Decision:
    primary_tool: ToolBinding | None = None
    fallback_tool: ToolBinding | None = None
    side_tools: list[ToolBinding] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_ms: int = 30_000
    tool_context_prompt: str = ""
    strategy: str = "SERIAL"  # from ActionPlan


# ── Act output ──

@dataclass
class EvolutionSignal:
    type: str
    tool: str
    reason: str
    severity: float


@dataclass
class ActionResult:
    success: bool
    primary_tool: str
    primary_result: Any = None
    primary_error: str | None = None
    fallback_used: bool = False
    fallback_tool: str | None = None
    fallback_result: Any = None
    side_results: dict[str, Any] = field(default_factory=dict)
    new_context_summary: str = ""
    tokens_used: int = 0
    elapsed_ms: int = 0
    evolution_signals: list[EvolutionSignal] = field(default_factory=list)


# ── Tool stats (for dynamic weighting) ──

@dataclass
class ToolStats:
    successes: int = 0
    failures: int = 0
    total_latency_ms: int = 0
    calls: int = 0

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 0.5

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.calls if self.calls > 0 else 0.0


# ── Circuit breaker config ──

@dataclass
class CircuitConfig:
    """Per-tool circuit breaker configuration."""
    failure_threshold: int = 5       # failures to open circuit
    cooldown_s: float = 60.0         # seconds before half_open
    half_open_success_threshold: int = 3  # successes to re-close


# ── Unified OODA config ──

@dataclass
class OODAConfig:
    """Unified configuration for the entire OODA pipeline.

    Centralizes all tunables that were previously scattered across stage
    constructors, event bus, evolution bridge, and loop config.
    """
    # ── Loop ──
    max_iterations: int = 10
    evolution_check_interval: int = 3
    context_critical_ratio: float = 0.85

    # ── Timeouts (ms) ──
    default_timeout_ms: int = 30_000
    observe_timeout_ms: int = 10_000
    orient_timeout_ms: int = 30_000
    decide_timeout_ms: int = 30_000

    # ── Circuit breaker ──
    circuit: CircuitConfig = field(default_factory=CircuitConfig)
    tool_circuits: dict[str, CircuitConfig] = field(default_factory=dict)

    # ── Evolution ──
    evolution_failure_threshold: int = 2
    evolution_deep_evolve_threshold: int = 3
    evolution_window_s: float = 300.0
    evolution_deep_evolve_cooldown_s: float = 60.0

    # ── Cache ──
    orient_cache_ttl_s: float = 60.0

    # ── Event bus ──
    event_max_history: int = 500

    @classmethod
    def from_dict(cls, data: dict) -> "OODAConfig":
        """Build OODAConfig from a configuration dictionary."""
        circuit_data = data.get("circuit", {})
        circuit = CircuitConfig(
            failure_threshold=circuit_data.get("failure_threshold", 5),
            cooldown_s=circuit_data.get("cooldown_s", 60.0),
            half_open_success_threshold=circuit_data.get("half_open_success_threshold", 3),
        )
        tool_circuits = {}
        for name, tc in data.get("tool_circuits", {}).items():
            tool_circuits[name] = CircuitConfig(
                failure_threshold=tc.get("failure_threshold", 5),
                cooldown_s=tc.get("cooldown_s", 60.0),
                half_open_success_threshold=tc.get("half_open_success_threshold", 3),
            )
        return cls(
            max_iterations=data.get("max_iterations", 10),
            evolution_check_interval=data.get("evolution_check_interval", 3),
            context_critical_ratio=data.get("context_critical_ratio", 0.85),
            default_timeout_ms=data.get("default_timeout_ms", 30_000),
            observe_timeout_ms=data.get("observe_timeout_ms", 10_000),
            orient_timeout_ms=data.get("orient_timeout_ms", 30_000),
            decide_timeout_ms=data.get("decide_timeout_ms", 30_000),
            circuit=circuit,
            tool_circuits=tool_circuits,
            evolution_failure_threshold=data.get("evolution_failure_threshold", 2),
            evolution_deep_evolve_threshold=data.get("evolution_deep_evolve_threshold", 3),
            evolution_window_s=data.get("evolution_window_s", 300.0),
            evolution_deep_evolve_cooldown_s=data.get("evolution_deep_evolve_cooldown_s", 60.0),
            orient_cache_ttl_s=data.get("orient_cache_ttl_s", 60.0),
            event_max_history=data.get("event_max_history", 500),
        )


# Backward-compatible alias
OODALoopConfig = OODAConfig


def estimate_tokens(text: str) -> int:
    """Rough token count — ~4 chars per token for English/Code, ~1.5 for CJK."""
    if not text:
        return 0
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '　' <= c <= '〿')
    non_cjk = len(text) - cjk
    return int(cjk / 1.5 + non_cjk / 4)


def build_action_summary(actions: list["ActionResult"], signals: list["EvolutionSignal"] | None = None,
                         intent_raw: str | None = None) -> str:
    """Build a human-readable summary string from actions and evolution signals."""
    success_count = sum(1 for a in actions if a.success)
    failure_count = len(actions) - success_count
    tools_used = [a.primary_tool for a in actions if a.primary_tool]
    parts = []
    if intent_raw:
        parts.append(f"Intent: {intent_raw}")
    parts.append(f"{len(actions)} action(s): {success_count} success, {failure_count} failure")
    if tools_used:
        parts.append(f"Tools: {', '.join(tools_used)}")
    if signals:
        failure_signals = [s for s in signals if s.type == "tool_failure"]
        if failure_signals:
            parts.append(f"{len(failure_signals)} evolution signal(s)")
    return ". ".join(parts)


# ── Loop result ──


LoopStatus = Literal["completed", "max_iterations", "context_exhausted", "error"]


@dataclass
class IterationTrace:
    """Per-iteration trace for diagnostics and observability."""
    iteration: int
    observe_ms: int = 0
    orient_ms: int = 0
    decide_ms: int = 0
    act_ms: int = 0
    orient_strategy: str = ""
    orient_capabilities: list[str] = field(default_factory=list)
    orient_confidence: float = 0.0
    decide_tool: str = ""
    decide_confidence: float = 0.0
    act_success: bool = False
    act_elapsed_ms: int = 0
    signals_count: int = 0


@dataclass
class OODAResult:
    status: LoopStatus
    summary: str
    situation: SituationContext | None = None
    actions: list[ActionResult] = field(default_factory=list)
    evolution_triggered: bool = False
    trace: list[IterationTrace] = field(default_factory=list)
    total_ms: int = 0
    total_tokens: int = 0
