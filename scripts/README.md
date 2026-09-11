# scripts/build_specs.py — 1차 출처 스펙 수집기

`data/parts_list.csv` 의 CPU/GPU/메인보드를 순회하며 **socket / tdp_w / length_mm /
form_factor / min_bios** 만 추출하고, 값마다 출처 URL을 저장한다.

```bash
pip install requests beautifulsoup4 lxml
python scripts/build_specs.py                     # 전체
python scripts/build_specs.py --only cpu --limit 5
python scripts/build_specs.py --delay 2.0 --force # 간격 2초, 캐시 무시
```

## 정책 (리스크 문서 1장 준수)
- 전역 **1건/초 이하** (`--delay`, 기본 1.2s + 지터)
- **robots.txt 준수** (`--ignore-robots` 로만 해제 — 권장 안 함)
- 응답 HTML **캐시**(`scripts/.cache_specs/`) → 재실행 시 재요청 안 함
- 429/5xx **지수 백오프** (Retry-After 존중)
- **사실값만** 추출. 표·문장 통째 저장 안 함. 값 + 단위 + 출처 URL + 짧은 원문 스니펫만.
- 각 사이트 이용약관은 별도 확인 필요.

## 출력
| 파일 | 내용 |
|---|---|
| `data/parts_specs_raw.csv` | long 포맷 (값 1개 = 1행, 출처 URL·신뢰도·원문 포함) |
| `data/parts_specs.json` | 부품별 nested |
| `data/parts_specs_todo.csv` | 자동 추출 실패 → **사람이 URL·값 채우는 목록** |

## 현실 (2026-09 실측)

정적 HTTP(`requests`)만으로는 **대상 사이트 대부분이 클라이언트 렌더(SPA)** 라 추출률이 낮다.

| 소스 | 정적 HTML로 얻는 것 |
|---|---|
| Intel ARK (스펙 URL 고정 시) | `tdp_w` ✅ / `socket` ❌ (JS 로드) |
| AMD 제품 페이지 | 응답 지연·UA 게이팅 잦음 → 대부분 TODO |
| NVIDIA GeForce 페이지 | SPA → 0 |
| ASUS/MSI/GIGABYTE 스펙·CPU지원 | SPA / PDF → 0, min_bios 표 파싱 불가 |

→ 현재 스크립트는 **"정확한 출처 URL + 소량 값 + 나머지는 TODO 목록"** 을 만든다.
`parts_list.csv` 의 `spec_url` / `cpu_support_url` 에 **공식 페이지 URL을 직접 채워** 두면
가장 안정적이다. ARK 자동검색은 엔드포인트 변동으로 불안정.

## 추출률을 올리려면 (`--render` 모드, 미구현)
헤드리스 크로미움(Playwright)으로 렌더 후 DOM에서 같은 추출기를 돌리면
NVIDIA/ASUS/AMD/ARK-socket 까지 커버 가능. rate limit·robots·캐시 로직은 그대로 재사용.
필요 시 추가 구현.
