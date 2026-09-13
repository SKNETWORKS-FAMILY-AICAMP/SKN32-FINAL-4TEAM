"""전역 설정값 모음 (Truefit).

실제 배포 시 환경변수(.env / 컨테이너 환경변수)로 주입한다.
스켈레톤 단계에서는 MOCK_MODE 가 켜져 있어 외부 호출(LLM·임베딩)을 전부 가짜로 대체한다.
특정 클라우드/모델 벤더 이름은 코드에 넣지 않는다 — 전부 env 로 주입한다.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME: str = "Truefit"

# --------------------------------------------------------------------------
# 모드
# --------------------------------------------------------------------------
# "1" 이면 외부 호출을 하지 않고 고정된 가짜 데이터를 돌려준다. 실제 개발이 시작되면 0.
MOCK_MODE: bool = os.getenv("MOCK_MODE", "1") == "1"

# --------------------------------------------------------------------------
# LLM / 임베딩 (벤더 중립 — 값은 배포 시 주입)
# --------------------------------------------------------------------------
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock")   # mock | <managed-llm-api>
LLM_MODEL: str = os.getenv("LLM_MODEL", "")             # 경량 대화 모델 식별자
LLM_REGION: str = os.getenv("LLM_REGION", "")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "") # 텍스트 임베딩 모델 식별자

# --------------------------------------------------------------------------
# DB / 인증
# --------------------------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://truefit:truefit@localhost:5432/truefit"
)
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_TTL_DAYS: int = int(os.getenv("JWT_TTL_DAYS", "14"))
AUTH_CODE_TTL_MIN: int = 10
AUTH_CODE_MAX_ATTEMPTS: int = 5

# --------------------------------------------------------------------------
# 파이프라인 파라미터
# --------------------------------------------------------------------------
CONFIDENCE_THRESHOLD: int = 80        # [3-C] 이 점수 미만 → 재탐색
MAX_DEBATE_ROUNDS: int = 3            # 검사AI↔변호인AI 고정 라운드 하드캡
MAX_RESEARCH_ROUNDS: int = 3          # 재탐색 루프 최대 라운드
TOP_N_IMPACT: int = 5                 # GPU·CPU 등 영향 큰 슬롯의 상위 후보 수
TOP_N_DEFAULT: int = 3                # 그 외 슬롯
CLEANSE_RATIO_THRESHOLD: float = 0.20 # [3-C] 리뷰 근거 가중치 하락 트리거
PENDING_SCORE_PENALTY: float = 0.20   # [3-B] Pending 후보 스코어 감점

# --------------------------------------------------------------------------
# 경로
# --------------------------------------------------------------------------
ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = ROOT / "data"
CONFIG_DIR: Path = ROOT / "config"
CATEGORY_DIR: Path = CONFIG_DIR / "categories"
SCENARIO_DIR: Path = DATA_DIR / "scenarios"
FRONTEND_DIR: Path = ROOT / "frontend"
