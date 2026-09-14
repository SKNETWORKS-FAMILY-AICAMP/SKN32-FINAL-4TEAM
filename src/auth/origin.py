"""Origin 검증 — 쿠키 인증 변경 요청의 CSRF 경계 (CONTRACTS.md "Check Origin for
cookie-authenticated mutations"; P6 review R3).

브라우저는 cross-site 변경 요청에도 Origin 헤더를 붙인다. Origin이 있는데 이 요청이
실제로 도달한 서버 자신의 origin(스킴+호스트, 또는 `ALLOWED_ORIGINS`에 명시된 추가
origin)과 다르면 거부한다. Origin이 아예 없는 요청(curl/서버-서버 호출/일부 구형
클라이언트)은 명시적으로 허용한다 — CONTRACTS "preserve existing CLI/test callers with
explicit documented no-Origin policy". 전체 CORS 정책이 아니라 게이트 하나뿐이다: 이
서버는 브라우저의 cross-origin 요청 자체를 지원하지 않으므로 Access-Control-* 헤더는
발급하지 않는다.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import ALLOWED_ORIGINS

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_allowed(origin: str, request: Request) -> bool:
    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    if (parsed.scheme, parsed.netloc) == (request.url.scheme, request.url.netloc):
        return True
    return origin in ALLOWED_ORIGINS


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _MUTATING_METHODS:
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(origin, request):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "origin_not_allowed",
                                       "message": "허용되지 않은 출처의 요청입니다.", "field": None}},
                )
        return await call_next(request)
