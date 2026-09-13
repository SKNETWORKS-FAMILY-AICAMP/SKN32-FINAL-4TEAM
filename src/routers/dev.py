"""/dev/* — 개발용. 시나리오 파일 기반 파이프라인 실행 (DB 미사용).

프론트 연동 전, 엔진 흐름을 눈으로 보기 위한 엔드포인트. 운영에서는 비활성.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import SCENARIO_DIR
from src.dto import PipelineResult
from src.services import recommendation_service

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/scenarios")
def scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


class RunIn(BaseModel):
    scenario: str = "computer_pass"


@router.post("/run", response_model=PipelineResult)
def run(body: RunIn) -> PipelineResult:
    try:
        return recommendation_service.run_from_scenario(body.scenario)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
