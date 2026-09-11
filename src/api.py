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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.config import APP_NAME
from src.errors import TruefitError
from src.routers import auth, dev, lists, reviews, session

app = FastAPI(title=f"{APP_NAME} API (skeleton)")

app.include_router(auth.router)
app.include_router(session.router)
app.include_router(lists.router)
app.include_router(reviews.router)
app.include_router(dev.router)


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
