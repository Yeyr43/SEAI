# ══════════════════════════════════════════════════
# api/models.py - Model & endpoint management
# ────────────────────────────────────────────────
# GET    /api/models          – list available models
# GET    /api/models/current  – get current model
# POST   /api/model/switch    – switch model
# GET    /api/endpoints       – list custom endpoints
# POST   /api/endpoints       – add a custom endpoint
# DELETE /api/endpoints/{name}– remove a custom endpoint
# ══════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import get_agent

router = APIRouter()


# ── Models ────────────────────────────────────────

class ModelSwitchRequest(BaseModel):
    model: str


class EndpointRequest(BaseModel):
    name: str
    api_base: str = ""
    api_key: str
    model_name: str = ""
    base_url: str = ""
    model: str = ""


# ── Model routes ──────────────────────────────────

@router.get("/api/models")
async def list_models():
    return {"models": get_agent().llm_manager.list_models()}


@router.get("/api/models/current")
async def current_model():
    return {"current_model": get_agent().llm_manager.current_model}


@router.post("/api/model/switch")
async def switch_model(req: ModelSwitchRequest):
    agent = get_agent()
    try:
        agent.llm_manager.set_current_model(req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    config = agent.load_config()
    config["current_model"] = req.model
    agent.config.save_config()
    return {"status": "ok"}


# ── Endpoint routes ──────────────────────────────

@router.get("/api/endpoints")
async def list_endpoints():
    config = get_agent().load_config()
    eps = config.get("llm_endpoints", [])
    return {
        "endpoints": [
            {
                "name": ep.get("name", ""),
                "api_base": ep.get("api_base", ""),
                "model": ep.get("model", ""),
                "base_url": ep.get("api_base", ""),
            }
            for ep in eps
        ]
    }


@router.post("/api/endpoints")
async def add_endpoint(req: EndpointRequest):
    agent = get_agent()
    name = req.name
    api_base = getattr(req, "api_base", None) or getattr(req, "base_url", "")
    api_key = req.api_key
    model_name = getattr(req, "model_name", None) or getattr(req, "model", "")
    agent.llm_manager.add_endpoint(name, api_base, api_key, model_name)
    config = agent.load_config()
    eps = config.get("llm_endpoints", [])
    eps = [ep for ep in eps if ep["name"] != name]
    eps.append({
        "name": name, "api_base": api_base,
        "api_key": api_key, "model": model_name,
    })
    config["llm_endpoints"] = eps
    agent.config.save_config()
    return {"status": "ok"}


@router.delete("/api/endpoints/{name}")
async def remove_endpoint_by_name(name: str):
    agent = get_agent()
    agent.llm_manager.remove_endpoint(name)
    config = agent.load_config()
    config["llm_endpoints"] = [
        ep for ep in config.get("llm_endpoints", []) if ep["name"] != name
    ]
    agent.config.save_config()
    return {"status": "ok"}
