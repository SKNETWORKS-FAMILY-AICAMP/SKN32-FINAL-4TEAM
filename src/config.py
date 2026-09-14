"""전역 설정값 모음 (Truefit).

실제 배포 시 환경변수(.env / 컨테이너 환경변수)로 주입한다.
스켈레톤 단계에서는 MOCK_MODE 가 켜져 있어 외부 호출(LLM·임베딩)을 전부 가짜로 대체한다.
특정 클라우드/모델 벤더 이름은 코드에 넣지 않는다 — 전부 env 로 주입한다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env → 프로세스 환경. 이미 설정된 실제 환경변수는 덮지 않는다(override=False 가 기본).
# 경로를 명시한다 — 실행 위치가 프로젝트 루트가 아닐 때도 같은 파일을 읽어야 한다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

APP_NAME: str = "Truefit"

# --------------------------------------------------------------------------
# 모드
# --------------------------------------------------------------------------
# "1" 이면 외부 호출을 하지 않고 고정된 가짜 데이터를 돌려준다. 실제 개발이 시작되면 0.
MOCK_MODE: bool = os.getenv("MOCK_MODE", "1") == "1"

# --------------------------------------------------------------------------
# LLM / 임베딩 (벤더 중립 — 값은 배포 시 주입)
# --------------------------------------------------------------------------
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock")   # mock | openai
LLM_MODEL: str = os.getenv("LLM_MODEL", "")             # 경량 대화 모델 식별자
LLM_REGION: str = os.getenv("LLM_REGION", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "") # 텍스트 임베딩 모델 식별자
# 조건 대화 에이전트(src/agent/conditions_agent.py, Strands Agents SDK). "1" 이면 /session/{id}/message 의
# 자유 텍스트를 LLM 도구 호출로 조건에 반영한다. 기본 "0" — 계약 §D-3([1]은 규칙 기반)이 아직 유효해서
# 프론트 담당자 합의 전까지는 opt-in. MOCK_MODE=1 이거나 OPENAI_API_KEY·LLM_MODEL 이 비면 켜도 규칙 경로.
CONDITIONS_AGENT: bool = os.getenv("CONDITIONS_AGENT", "0") == "1"
# 결과 화면 대화 에이전트(src/agent/result_agent.py, Strands). "1" 이면 /session/{id}/result-message 의
# 자유 텍스트를 LLM 도구 호출(후보 조회·교체·담기/빼기·수량·시점·근거 설명)로 처리한다. 기본 "0" — 규칙 경로.
RESULT_AGENT: bool = os.getenv("RESULT_AGENT", "0") == "1"
# 달러 입력("$1,500", "1500 dollars")을 원화 예산으로 바꾸는 고정 환율. 카탈로그·엔진은 전부 원화라 저장은 원화로 하고,
# 사용자가 달러로 말했으면(currency=USD) 답변·표시에서 달러를 앞에 두고 원화를 병기한다. 실시간 환율이 아니다.
USD_KRW_RATE: float = float(os.getenv("USD_KRW_RATE", "1400"))
# 조립 가이드 에이전트(src/agent/assembly_guide_agent.py, Strands Agents SDK). "1"이면 결과 화면의
# 확정된 부품 목록으로 조립 순서·주의사항 가이드를 만든다. 기본 "0" — opt-in. MOCK_MODE=1이거나
# OPENAI_API_KEY·LLM_MODEL이 비면 켜도 규칙 기반 폴백(검색은 실제로 하되 문장은 템플릿)으로 간다.
ASSEMBLY_GUIDE_AGENT: bool = os.getenv("ASSEMBLY_GUIDE_AGENT", "0") == "1"

# --------------------------------------------------------------------------
# DB / 인증
# --------------------------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://truefit:truefit@localhost:5432/truefit"
)
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_TTL_DAYS: int = int(os.getenv("JWT_TTL_DAYS", "14"))
# `src.auth.origin`과 앱 시작 훅은 기존 공개 API이므로, 새 쿠키 설정과 함께
# 유지한다. 환경 변수가 없을 때는 로컬 개발 설정을 사용한다.
APP_ENV: str = os.getenv("APP_ENV", "development")
IS_PRODUCTION: bool = APP_ENV == "production"
AUTH_COOKIE_SECURE: bool = IS_PRODUCTION or os.getenv("AUTH_COOKIE_SECURE", "0") == "1"
ALLOWED_ORIGINS: list[str] = [
    origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()
]
AUTH_CODE_TTL_MIN: int = 10
AUTH_CODE_MAX_ATTEMPTS: int = 5

# 이메일+비밀번호 로그인 (docs/frontend_외부수정요청.md §A)
COOKIE_NAME: str = os.getenv("COOKIE_NAME", "truefit_session")
COOKIE_SECURE: bool = AUTH_COOKIE_SECURE or os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "12"))
LOGIN_MAX_FAILURES: int = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCK_MINUTES: int = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
TERMS_VERSION: str = os.getenv("TERMS_VERSION", "2026-09-11")


def assert_production_secret_safe() -> None:
    """운영 환경에서 개발용 기본 JWT secret으로 기동하지 않는다."""
    if IS_PRODUCTION and JWT_SECRET == "dev-only-change-me":
        raise RuntimeError("APP_ENV=production 에서는 JWT_SECRET 환경변수를 반드시 설정해야 합니다.")

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

# [3-C] "구매 전 확인" — 부품 사용 가이드·주의 문구 RAG(임베딩 검색). 합성 작성 문서,
# 소량(16개)이라 벡터DB 없이 인메모리 코사인 검색으로 충분하다. RAG_EMBEDDING_PROVIDER(bedrock)와
# 무관한 별도 기능 — 이미 동작 확인된 OpenAI 키를 그대로 쓴다.
CARE_GUIDES_JSON: Path = DATA_DIR / "pc_care_guides.json"
CARE_GUIDE_EMBEDDING_MODEL: str = os.getenv("CARE_GUIDE_EMBEDDING_MODEL", "text-embedding-3-small")
