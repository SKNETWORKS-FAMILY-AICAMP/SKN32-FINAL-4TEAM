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

# 리뷰 관계·행동 축 — 배치(review_cleanse_worker) 산출물과 데모 부품 ↔ ASIN 매핑.
# 산출 JSON 이 없으면 ProductRiskStore 는 None 이고 호출자는 "관측 없음" 으로 다룬다
REVIEW_RISK_JSON: Path = DATA_DIR / "amazon23" / "pcparts_product_risk.json"   # 대조군 = PC 부품 (Computer Components|Data Storage)
PARTS_ASIN_MAP: Path = DATA_DIR / "parts_asin_map.csv"
REVIEW_SUMMARIES_DEMO: Path = DATA_DIR / "review_summaries.json"     # 합성 데모 (is_synthetic=true) — 항목별 평가·요약 3건
REVIEW_AXIS_EXCESS: float = 2.0       # [3-B] 관측값이 대조군 중앙값의 몇 배를 넘으면 "검토 필요" 로 보는가 (영어 실측 라벨에서만 확인한 랭킹용 문턱)
# 산출물의 meta.control_scope 가 이 값과 다르면 관측을 쓰지 않는다.
# 대조군은 같은 부류여야 한다 — 전체 중앙값을 PC 부품에 대면 다작 계정 비율만으로 절반이 걸린다.
# 틀린 대조군은 에러를 내지 않고 "틀린 중앙값과 비교한 관측 사실" 을 내므로 조용히 지나간다.
REVIEW_RISK_CONTROL_SCOPE: str = "Computer Components|Data Storage"
# 규칙 기반 "의심 지표 2개+ 리뷰 수". 조작 판정이 아니다 — 리뷰 단위 라벨이 없어 정밀도를 못 잰다.
# 파일이 자기 방법·한계를 담고 있다(method · limits · baseline). 없으면 이 문장을 내지 않는다.
REVIEW_SUSPECT_COUNTS: Path = DATA_DIR / "review_suspect_counts.json"
