# ══════════════════════════════════════════════════
# api/__init__.py - SEAI API subpackage
# ────────────────────────────────────────────────
# Exposes shared agent/terminal/mcp getters and the
# create_api_router() factory for the FastAPI app.
# ══════════════════════════════════════════════════
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.agent import SEAgent
    from ..core.terminal import TerminalManager
    from ..mcp_server import SEAIMCPServer

_agent: SEAgent | None = None
_terminal_manager: TerminalManager | None = None
_mcp_server: SEAIMCPServer | None = None


# ── Getters / Setters ──────────────────────────────

def get_agent() -> SEAgent:
    """Return the global SEAgent instance (must be initialised)."""
    if _agent is None:
        raise RuntimeError("Agent not initialised – call set_agent() first")
    return _agent


def set_agent(agent: SEAgent) -> None:
    global _agent
    _agent = agent


def get_terminal_manager() -> TerminalManager:
    if _terminal_manager is None:
        raise RuntimeError("TerminalManager not initialised")
    return _terminal_manager


def set_terminal_manager(tm: TerminalManager) -> None:
    global _terminal_manager
    _terminal_manager = tm


def get_mcp_server() -> SEAIMCPServer:
    if _mcp_server is None:
        raise RuntimeError("SEAIMCPServer not initialised")
    return _mcp_server


def set_mcp_server(srv: SEAIMCPServer) -> None:
    global _mcp_server
    _mcp_server = srv


# ── Router factory (lazy import to avoid circular deps) ─

def create_api_router():
    """Return an APIRouter with all API sub-routers included."""
    from .router import create_api_router as _impl
    return _impl()
