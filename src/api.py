"""FastAPI 앱 조립 — 라우터 include + 공통 에러 핸들러.

실행:  uvicorn src.api:app --reload   →   http://127.0.0.1:8000/docs

라우터:
  /auth/*     이메일 코드 → JWT
  /session/*  S1~S3 대화·조건 수집 + [추천 실행]   (인증 불요)
  /lists/*    S5-a 확정 · S5-b 리포트 · 알림        (JWT 필수)
  /reviews/*  A7 리뷰 작성·게시                     (JWT 필수)
  /dev/*      시나리오 기반 파이프라인 (DB 미사용, 개발용)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import APP_NAME, FRONTEND_DIR
from src.db import close_pool
from src.errors import TruefitError
from src.routers import auth, dev, lists, reviews, session


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    close_pool()


app = FastAPI(title=f"{APP_NAME} API (skeleton)", lifespan=_lifespan)

app.include_router(auth.router)
app.include_router(session.router)
app.include_router(lists.router)
app.include_router(reviews.router)
app.include_router(dev.router)

# API 라우터를 먼저 등록해 API 경로가 정적 파일보다 우선하도록 한다. 공개할
# 프런트 파일만 각각 마운트해 frontend/ 안의 개발 문서 등은 노출하지 않는다.
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")


@app.exception_handler(TruefitError)
def _truefit_error_handler(_req: Request, exc: TruefitError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_envelope())


@app.exception_handler(NotImplementedError)
def _not_impl_handler(_req: Request, exc: NotImplementedError) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": str(exc) or "미구현", "field": None}},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": APP_NAME}


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{page_name}.html", include_in_schema=False)
def frontend_page(page_name: str) -> FileResponse:
    """Serve only top-level frontend HTML pages, never arbitrary frontend files."""
    page = FRONTEND_DIR / f"{page_name}.html"
    if not page.is_file() or page.parent != FRONTEND_DIR:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(page)
