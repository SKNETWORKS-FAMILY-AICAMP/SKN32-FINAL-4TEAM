# 백엔드 요청 — CORS 설정 (해커톤 전, 시급)

작성일: 2026-09-12 · 작성: 프론트 · 관련: `docs/frontend_외부수정요청.md` §E (기존에 등록된 항목을 별도 파일로 분리·상세화)

## 증상

프론트(`http://127.0.0.1:5500`)와 백엔드(`http://127.0.0.1:8000`)를 각각 로컬에서 띄우고 실제 브라우저로 전 화면(랜딩·카테고리·로그인·회원가입·회원정보·조건입력·추천결과)을 확인한 결과, **모든 화면에서 공통으로** 아래 콘솔 오류가 발생한다.

```
Access to fetch at 'http://127.0.0.1:8000/auth/me' from origin 'http://127.0.0.1:5500'
has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present
on the requested resource.
Failed to load resource: net::ERR_FAILED
```

`/auth/me`, `/lists` 등 거의 모든 API 호출이 실패하며, 화면에는 "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요." 문구가 뜬다. 회원가입 버튼을 눌러도 같은 이유로 실패한다.

- 백엔드 자체는 정상 동작 중임을 확인했다 (`curl http://127.0.0.1:8000/health` → `200`).
- 즉 서버 다운이나 백엔드 로직 오류가 아니라 **브라우저의 CORS 정책 차단**이 원인이다.

## 원인

`src/api.py`에 CORS 관련 설정(`CORSMiddleware` 등)이 없다. 프론트와 백엔드가 서로 다른 포트(5500 / 8000)에서 서빙되는 개발 환경에서는, 백엔드가 명시적으로 허용 origin을 응답 헤더에 포함해줘야 브라우저가 fetch 응답을 통과시킨다.

## 요청 — 둘 중 하나 선택

1. **CORS 미들웨어 추가** (가장 빠름)
   ```python
   from fastapi.middleware.cors import CORSMiddleware

   app.add_middleware(
       CORSMiddleware,
       allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
       allow_credentials=True,   # 로그인 쿠키(httpOnly) 포함 요청을 쓰므로 필수
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```

2. **같은 도메인에서 서빙** (배포 구조상 더 권장): API 라우터 등록 뒤 `frontend/`를 `StaticFiles`로 같이 서빙해 애초에 크로스 오리진 호출 자체를 없앤다.
   - 공개 범위는 `frontend/*.html`(10개 페이지), `frontend/css/`, `frontend/js/`, `frontend/assets/`만. `frontend/CLAUDE.md` 같은 개발 문서는 제외.

`allow_credentials=True`를 쓸 경우 `allow_origins`에 `"*"`를 쓸 수 없다(브라우저 스펙상 금지) — 위처럼 개발 서버 포트를 명시해야 한다.

## 확인 방법

CORS 헤더가 붙으면 프론트 콘솔의 위 오류가 사라지고, `signup.html`에서 회원가입이 정상적으로 서버 응답을 받는지로 확인 가능. 프론트 쪽 재현 절차:

```powershell
# 터미널 1
uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
# 터미널 2
uv run python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

`http://127.0.0.1:5500/index.html` 접속 후 브라우저 개발자 도구 콘솔 확인.

## 시급도

**해커톤(2026-09-15) 전 필수.** 이 문제가 해결되지 않으면 로그인·회원가입·장바구니 등 API 연동이 필요한 모든 화면이 로컬에서 검증 불가능하다.
