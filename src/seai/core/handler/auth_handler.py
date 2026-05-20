"""
认证处理器
提供 API Key 验证和速率限制中间件
"""
from fastapi import Request, Depends, HTTPException
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from ..service.auth_service import AuthService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_auth_service: AuthService = None

# API 路径白名单（不验证认证）
AUTH_WHITELIST_PATHS = {
    "/api/health",
    "/api/chat",     # chat 已有独立 verify_api_key
    "/webhook/telegram",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def init_auth_handler(auth_service: AuthService):
    global _auth_service
    _auth_service = auth_service


async def verify_api_key(api_key: str = Depends(api_key_header)):
    if _auth_service is None:
        return True
    if _auth_service.verify_api_key(api_key):
        return True
    raise HTTPException(status_code=403, detail="无效的 API Key")


async def auth_middleware(request: Request, call_next):
    """全局 API 认证中间件 — 保护所有 /api/* 路由（白名单除外）"""
    path = request.url.path

    # 白名单路径跳过认证
    if path in AUTH_WHITELIST_PATHS or path.startswith("/webhook/"):
        return await call_next(request)

    # 只拦截 /api/* 路径
    if not path.startswith("/api/"):
        return await call_next(request)

    if _auth_service is None:
        return await call_next(request)

    # 未配置 API Key 时放行
    if not _auth_service.is_api_key_configured():
        return await call_next(request)

    api_key = request.headers.get("X-API-Key", "")
    if _auth_service.verify_api_key(api_key):
        return await call_next(request)

    return JSONResponse(status_code=403, content={"error": "无效的 API Key"})


async def rate_limit_middleware(request: Request, call_next):
    if _auth_service is None:
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"
    if not _auth_service.check_rate_limit(client_ip):
        return JSONResponse(status_code=429, content={"error": "请求过于频繁，请稍后再试"})
    return await call_next(request)