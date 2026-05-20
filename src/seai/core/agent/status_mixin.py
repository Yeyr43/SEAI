""""""
from .. import net
from ..circuit_breaker import breaker_manager
from ..event_bus import event_bus
from typing import Any
from typing import Dict

class StatusMixin:
    def get_status(self) -> Dict[str, Any]:
        """获取智能体状态"""
        breaker_stats = {}
        for name, breaker in breaker_manager._breakers.items():
            stats = breaker.get_stats()
            breaker_stats[name] = {
                "state": stats.state.value,
                "failure_count": stats.failure_count,
                "success_count": stats.success_count
            }

        status = {
            "initialized": self.lifecycle_manager.is_initialized(),
            "components": self.lifecycle_manager.get_component_status(),
            "thinking_enabled": self.thinking_enabled,
            "web_search_enabled": net.is_enabled(),
            "conversation_count": len(self.session_manager.get_current_history()) if hasattr(self.session_manager, 'get_current_history') else 0,
            "cached_tools": len(self._tool_cache),
            "locale": self.current_locale,
            "role": self.current_role,
            "prompt_engine": self._prompt_engine.export_debug_info() if self._prompt_engine else None,
            "token_log_count": len(self._token_log),
            "circuit_breakers": breaker_stats,
            "error_stats": self._error_handler.error_stats if self._error_handler else {},
            "recent_errors_count": len(self._error_handler.recent_errors) if self._error_handler else 0,
            "multi_agent": {
                "enabled": self._multi_agent_config.get("enabled", False),
                "parallel_execution": self._multi_agent_config.get("parallel_execution", False),
                "max_sub_agents": self._multi_agent_config.get("max_sub_agents", 3),
                "complexity_threshold": self._multi_agent_config.get("complexity_threshold", 0.5),
                "pool_stats": self._agent_pool.get_stats() if self._agent_pool else {},
            },
            "harness": {
                "constraint_engine": self._constraint_engine.get_stats() if self._constraint_engine else {},
                "feedback_loop": self._feedback_loop.get_stats() if self._feedback_loop else {},
            },
            "services": {
                "conversation": self._conversation_service.get_stats() if self._conversation_service else {},
                "evolution": self._evolution_service.get_stats() if self._evolution_service else {},
            },
            "event_bus": event_bus.get_stats(),
            "pipeline": self._pipeline.get_pipeline_info() if self._pipeline else {},
            "pipeline_metrics": self._pipeline.get_metrics() if self._pipeline else {},
        }
        return status

    def load_config(self) -> dict:
        return self.config._config_cache if hasattr(self.config, '_config_cache') else {}

    async def reload_config(self, config: dict):
        if hasattr(self.config, '_config_cache'):
            self.config._config_cache.update(config)
        if hasattr(self, '_security'):
            self._security.load_config(self.load_config())
