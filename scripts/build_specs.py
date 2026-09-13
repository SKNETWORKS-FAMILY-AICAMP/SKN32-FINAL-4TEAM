#!/usr/bin/env python3
"""parts_list.csv 의 CPU/GPU/메인보드를 1차 출처에서 순회하며
   socket / tdp_w / length_mm / form_factor / min_bios 필드만 추출하고,
   값마다 출처 URL을 함께 저장한다.

정책 (프로젝트 리스크 문서 1장에 맞춤):
  - 요청은 전역 1건/초 이하 (--delay, 기본 1.2s + 지터)
  - robots.txt 준수 (--ignore-robots 로만 해제, 권장 안 함)
  - 응답 HTML 캐시(cache/) → 재실행 시 재요청 안 함 (--force 로 무시)
  - 429 / 5xx 지수 백오프 (Retry-After 존중)
  - 사실값(스펙 수치·문자열)만 추출. 페이지 표·문장을 통째로 저장하지 않음.
    각 값은 [값 + 단위 + 출처 URL + 짧은 원문 스니펫 + 추출 방법 + 신뢰도] 로만 기록.
  - 각 사이트 이용약관은 별도 확인 필요(본 스크립트가 보장하지 않음).

입력:  data/parts_list.csv
        컬럼: type,name[,brand,spec_url,cpu_support_url]
출력:  data/parts_specs_raw.csv   long 포맷 (아래 CSV_COLS)
        data/parts_specs.json      부품별 nested
        data/parts_specs_todo.csv  자동 추출 실패 → 사람이 채울 URL 목록

의존성:  pip install requests beautifulsoup4 lxml

사용:
  python scripts/build_specs.py
  python scripts/build_specs.py --limit 5 --only cpu,gpu
  python scripts/build_specs.py --delay 2.0 --force
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("pip install requests beautifulsoup4 lxml 필요")

# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE_DIR = ROOT / "scripts" / ".cache_specs"
CACHE_TTL = 14 * 24 * 3600  # 14일

IN_CSV = DATA / "parts_list.csv"
OUT_RAW = DATA / "parts_specs_raw.csv"
OUT_JSON = DATA / "parts_specs.json"
OUT_TODO = DATA / "parts_specs_todo.csv"

USER_AGENT = (
    "PCBuildSpecBot/0.1 (+set-your-contact@example.com) "
    "factual-spec-collection; respects robots.txt; <=1req/s"
)

CSV_COLS = [
    "name", "type", "field", "key", "value", "unit",
    "source_url", "source_type", "method", "confidence", "raw", "fetched_at",
]

# 추출 대상 라벨 매칭 --------------------------------------------------------
LABEL_RE = {
    "socket": re.compile(r"\b(socket|소켓)\b|supported\s+sockets?|cpu\s*socket|package\s+type", re.I),
    "tdp_w": re.compile(
        r"\b(default\s+)?tdp\b|thermal\s+design\s+power|processor\s+base\s+power|"
        r"total\s+graphics\s+power|\btgp\b|\btbp\b|기본\s*tdp", re.I),
    "length_mm": re.compile(
        r"card\s+length|graphics?\s+card\s+dimensions?|length\b|길이", re.I),
    "form_factor": re.compile(r"form\s*factor|폼\s*팩터|폼팩터|board\s+form", re.I),
}

# 부품 종류별로 관심 있는 필드
FIELDS_BY_TYPE = {
    "cpu": ["socket", "tdp_w"],
    "gpu": ["tdp_w", "length_mm"],
    "mainboard": ["socket", "form_factor"],  # min_bios 는 별도 경로
}

_SOCKET_RE = re.compile(
    r"(LGA\s?\d{3,4}|AM[45]|sTRX?4|sWRX8|FCLGA\d{3,4}|Socket\s?AM[45])", re.I)
_FF_MAP = [
    (re.compile(r"\bE-?ATX\b|Extended ATX", re.I), "E-ATX"),
    (re.compile(r"\bMicro-?ATX\b|mATX|µATX|\bmicroATX\b", re.I), "mATX"),
    (re.compile(r"\bMini-?ITX\b|\bITX\b", re.I), "ITX"),
    (re.compile(r"\bATX\b", re.I), "ATX"),
]

# --------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap + random.uniform(0.0, 0.3))
        self._last = time.monotonic()


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _find_chrome() -> str | None:
    env = os.environ.get("CHROME_BIN")
    if env and Path(env).exists():
        return env
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(c).exists():
            return c
    for n in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        w = shutil.which(n)
        if w:
            return w
    return None


class Fetcher:
    def __init__(self, limiter: RateLimiter, ignore_robots: bool, force: bool,
                 ua: str = USER_AGENT, render: bool = False, render_budget_ms: int = 12000):
        self.limiter = limiter
        self.ignore_robots = ignore_robots
        self.force = force
        self.ua = ua
        self.render_budget_ms = render_budget_ms
        self.chrome = _find_chrome() if render else None
        self.can_render = self.chrome is not None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        })
        self._robots: dict[str, RobotFileParser] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def render(self, url: str) -> str | None:
        """headless Chrome 로 렌더된 DOM 반환. 실패 시 None. rate-limit·robots·캐시 적용."""
        if not self.can_render:
            return None
        key = hashlib.sha1(("RENDER::" + url).encode("utf-8")).hexdigest()
        cpath = CACHE_DIR / f"{key}.render.html"
        if cpath.exists() and not self.force:
            if time.time() - cpath.stat().st_mtime < CACHE_TTL:
                return cpath.read_text(encoding="utf-8", errors="replace")
        if not self._robots_ok(url):
            raise PermissionError(f"robots.txt disallow: {url}")
        self.limiter.wait()
        cmd = [
            self.chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--dump-dom",
            f"--virtual-time-budget={self.render_budget_ms}",
            "--run-all-compositor-stages-before-draw",
            "--window-size=1400,3000", f"--user-agent={self.ua}", url,
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=self.render_budget_ms / 1000 + 40)
        except (subprocess.TimeoutExpired, OSError):
            return None
        html = p.stdout or ""
        if len(html) < 800:
            return None
        cpath.write_text(html, encoding="utf-8")
        return html

    def _robots_ok(self, url: str) -> bool:
        if self.ignore_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            try:
                self.limiter.wait()
                r = self.session.get(base + "/robots.txt", timeout=15)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])  # robots 못 읽으면 보수적으로 허용(요청은 어차피 rate-limited)
            self._robots[base] = rp
        return rp.can_fetch(self.ua, url)

    def get(self, url: str) -> tuple[str, str]:
        """(html, source) 반환. source ∈ {'cache','fetch'}. 실패 시 예외."""
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        cpath = CACHE_DIR / f"{key}.html"
        if cpath.exists() and not self.force:
            if time.time() - cpath.stat().st_mtime < CACHE_TTL:
                return cpath.read_text(encoding="utf-8", errors="replace"), "cache"
        if not self._robots_ok(url):
            raise PermissionError(f"robots.txt disallow: {url}")
        backoff = 2.0
        for _ in range(4):
            self.limiter.wait()
            try:
                r = self.session.get(url, timeout=25)
            except requests.RequestException as e:
                time.sleep(backoff); backoff *= 2
                last = str(e); continue
            if r.status_code == 200:
                cpath.write_text(r.text, encoding="utf-8")
                return r.text, "fetch"
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After", "")
                wait = float(ra) if ra.isdigit() else backoff
                time.sleep(min(wait, 120)); backoff *= 2
                last = f"HTTP {r.status_code}"; continue
            if 500 <= r.status_code < 600:
                time.sleep(backoff); backoff *= 2
                last = f"HTTP {r.status_code}"; continue
            raise RuntimeError(f"HTTP {r.status_code}: {url}")
        raise RuntimeError(f"retry 소진 ({last}): {url}")


# --------------------------------------------------------------------------
@dataclass
class Row:
    name: str
    type: str
    field: str
    value: str
    unit: str = ""
    key: str = ""
    source_url: str = ""
    source_type: str = ""
    method: str = ""
    confidence: float = 0.0
    raw: str = ""
    fetched_at: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_num(text: str, unit_re: str) -> str | None:
    m = re.search(rf"(\d+(?:[.,]\d+)?)\s*{unit_re}", text, re.I)
    return m.group(1).replace(",", "") if m else None


def _extract_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """페이지에서 (라벨, 값) 후보쌍을 모은다. 구조 불문 best-effort."""
    pairs: list[tuple[str, str]] = []
    for tr in soup.select("tr"):
        cells = tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])
        if len(cells) >= 2:
            pairs.append((cells[0].get_text(" ", strip=True),
                          cells[1].get_text(" ", strip=True)))
    for dl in soup.select("dl"):
        dts, dds = dl.find_all("dt"), dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            pairs.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
    # Intel ARK: <span data-key="SocketsSupported">  + 인접 값
    for el in soup.select("[data-key]"):
        k = el.get("data-key", "")
        sib = el.find_next(string=False)
        val = el.parent.get_text(" ", strip=True) if el.parent else el.get_text(" ", strip=True)
        pairs.append((k, val))
    # 일반 div 쌍: class에 label/spec-name/tech-label 포함 → 다음 형제가 값
    for lab in soup.select(
            "[class*=label],[class*=spec-name],[class*=techLabel],[class*=tech-label],"
            "[class*=spec__label],[class*=specs-label]"):
        val = lab.find_next_sibling()
        if val is not None:
            pairs.append((lab.get_text(" ", strip=True), val.get_text(" ", strip=True)))
    # 잡음 제거
    out = []
    for a, b in pairs:
        a, b = a.strip(), b.strip()
        if a and b and len(a) < 120 and len(b) < 300:
            out.append((a, b))
    return out


def _match_field(label: str) -> str | None:
    for fld, rx in LABEL_RE.items():
        if rx.search(label):
            return fld
    return None


# 텍스트 근접 정규식 폴백용 ------------------------------------------------
_FIELD_KW = {
    "socket": re.compile(r"socket|소켓", re.I),
    "tdp_w": re.compile(
        r"\bTDP\b|thermal\s+design\s+power|processor\s+base\s+power|\bbase\s+power\b|"
        r"total\s+graphics\s+power|\bTGP\b|\bTBP\b|default\s+tdp|기본\s*tdp", re.I),
    "form_factor": re.compile(r"form\s*factor|폼\s*팩터|폼팩터", re.I),
    "length_mm": re.compile(r"card\s+length|\blength\b|dimensions?|\b길이\b", re.I),
}


def _flatten_text(soup: BeautifulSoup) -> str:
    """보이는 텍스트 + SSR JSON 페이로드(ASUS __NUXT_DATA__, Next __NEXT_DATA__, ld+json)를
    하나의 검색용 문자열로 합친다."""
    visible = soup.get_text(" ", strip=True)
    blobs: list[str] = []
    for sc in soup.select(
            'script[type="application/json"], script#__NEXT_DATA__, '
            'script#__NUXT_DATA__, script[type="application/ld+json"]'):
        t = sc.string or sc.get_text()
        if t and len(t) < 3_000_000:
            blobs.append(t)
    text = visible + "  ||JSON||  " + "  ".join(blobs)
    text = (text.replace("\\u003C", "<").replace("\\u003E", ">")
                .replace("\\u002F", "/").replace("\\/", "/").replace("\\n", " "))
    return re.sub(r"\s+", " ", text)


def _regex_field(field: str, text: str) -> tuple[str, str, float, str] | None:
    """(값, 단위, 신뢰도, 원문스니펫) 또는 None. 키워드 주변 창에서 값 패턴 탐색."""
    kw = _FIELD_KW.get(field)
    windows: list[str] = []
    if kw:
        for m in kw.finditer(text):
            windows.append(text[max(0, m.start() - 40): m.end() + 180])

    if field == "socket":
        for w in windows:
            mm = _SOCKET_RE.search(w)
            if mm:
                v = re.sub(r"\s+", "", mm.group(1)).upper().replace("SOCKET", "").replace("FCLGA", "LGA")
                return v, "", 0.75, w[:200]
        toks = {re.sub(r"\s+", "", t).upper().replace("SOCKET", "").replace("FCLGA", "LGA")
                for t in _SOCKET_RE.findall(text)}
        if len(toks) == 1:
            return next(iter(toks)), "", 0.55, "(page-wide unique socket token)"
        return None

    if field == "tdp_w":
        for w in windows:
            mm = re.search(r"(\d{2,4})\s*W\b", w)
            if mm:
                return mm.group(1), "W", 0.7, w[:200]
        return None

    if field == "form_factor":
        for w in windows + [text[:6000]]:
            for rx, norm in _FF_MAP:
                if rx.search(w):
                    return norm, "", 0.7, w[:200]
        return None

    if field == "length_mm":
        for w in windows:
            mm = re.search(r"(\d{2,3}(?:\.\d)?)\s*mm\b", w)
            if mm:
                return mm.group(1), "mm", 0.5, w[:200]
        return None
    return None


def _consider(best: dict, row) -> None:
    if row.field not in best or row.confidence > best[row.field].confidence:
        best[row.field] = row


def _normalize(field: str, value: str) -> tuple[str, str, float] | None:
    """(정규화값, 단위, 신뢰도) 또는 None."""
    if field == "socket":
        m = _SOCKET_RE.search(value)
        if m:
            return re.sub(r"\s+", "", m.group(1)).upper().replace("SOCKET", ""), "", 0.9
        return None  # 소켓 토큰이 안 보이면 값 버림(오탐 방지) → TODO로 감
    if field == "tdp_w":
        n = _clean_num(value, r"w(?:atts?)?\b")
        return (n, "W", 0.9) if n else None
    if field == "length_mm":
        n = _clean_num(value, r"mm")
        if n:
            return n, "mm", 0.6  # FE/레퍼런스 기준일 수 있음 → 신뢰도 낮춤
        return None
    if field == "form_factor":
        for rx, norm in _FF_MAP:
            if rx.search(value):
                return norm, "", 0.9
        return None
    return None


def extract_specs(html: str, part, wanted: list[str], source_type: str,
                  url: str) -> list[Row]:
    soup = BeautifulSoup(html, "html.parser")
    best: dict[str, Row] = {}

    # pass 1: DOM 라벨-값 쌍 (구조가 표준일 때 신뢰도 높음)
    for label, value in _extract_pairs(soup):
        fld = _match_field(label)
        if fld is None or fld not in wanted:
            continue
        norm = _normalize(fld, value)
        if norm is None:
            continue
        val, unit, conf = norm
        _consider(best, Row(
            name=part.name, type=part.type, field=fld, value=val, unit=unit,
            source_url=url, source_type=source_type, method="dom-pair",
            confidence=conf, raw=f"{label} = {value}"[:200], fetched_at=_now(),
        ))

    # pass 2: 텍스트 근접 정규식 (pass1이 못 채운 필드만) — SSR JSON 포함
    text = _flatten_text(soup)
    for fld in wanted:
        if fld in best:
            continue
        hit = _regex_field(fld, text)
        if hit is None:
            continue
        val, unit, conf, snip = hit
        _consider(best, Row(
            name=part.name, type=part.type, field=fld, value=val, unit=unit,
            source_url=url, source_type=source_type, method="text-regex",
            confidence=conf, raw=snip, fetched_at=_now(),
        ))
    return list(best.values())


# --- Intel ARK 자동 검색(스펙 URL 없을 때) --------------------------------
def ark_search(fetcher: Fetcher, name: str) -> str | None:
    """ARK autocomplete 로 사양 페이지 URL 추정. 실패 시 None."""
    q = quote(name)
    endpoints = [
        f"https://www.intel.com/libs/apps/intel/arksearch/autocomplete?locale=en-us&currency=USD&query={q}",
        f"https://www.intel.com/content/www/us/en/ark/search.html?q={q}",
    ]
    for ep in endpoints:
        try:
            html, _ = fetcher.get(ep)
        except Exception:
            continue
        # JSON 응답 시도
        try:
            j = json.loads(html)
            for item in (j if isinstance(j, list) else j.get("results", [])):
                u = item.get("product_url") or item.get("url") or ""
                if "/products/sku/" in u:
                    if u.startswith("/"):
                        u = "https://www.intel.com" + u
                    return u.split("?")[0].rstrip("/") + "/specifications.html"
        except (json.JSONDecodeError, AttributeError):
            pass
        # HTML 응답이면 sku 링크 스크랩
        m = re.search(r'href="(/content/www/us/en/products/sku/\d+/[^"]+)"', html)
        if m:
            return "https://www.intel.com" + m.group(1).split("?")[0].rstrip("/") + "/specifications.html"
    return None


# --- 메인보드 CPU 지원표 → 최소 BIOS ------------------------------------
_BIOS_VER_RE = re.compile(r"\b([0-9]{3,4}[A-Za-z]?|[Vv]?\d+\.\d+[A-Za-z0-9.]*)\b")


def extract_min_bios(html: str, part, url: str) -> tuple[list[Row], bool]:
    """CPU 지원표에서 (CPU, 최소 BIOS) 행 추출. (rows, parsed?)"""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Row] = []
    for table in soup.select("table"):
        head = " ".join(th.get_text(" ", strip=True).lower()
                        for th in table.select("tr th, tr td")[:8])
        if "bios" not in head or not re.search(r"cpu|processor|model|프로세서", head):
            continue
        headers = [c.get_text(" ", strip=True).lower()
                   for c in table.select("tr")[0].find_all(["th", "td"])]
        try:
            ci_cpu = next(i for i, h in enumerate(headers)
                          if re.search(r"cpu|processor|model|프로세서", h))
            ci_bios = next(i for i, h in enumerate(headers) if "bios" in h)
        except StopIteration:
            continue
        for tr in table.select("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= max(ci_cpu, ci_bios):
                continue
            cpu_model = cells[ci_cpu].strip()
            bios_raw = cells[ci_bios].strip()
            bm = _BIOS_VER_RE.search(bios_raw)
            if not cpu_model or not bm:
                continue
            rows.append(Row(
                name=part.name, type=part.type, field="min_bios",
                key=cpu_model, value=bm.group(1), unit="",
                source_url=url, source_type="mainboard_cpu_support",
                method="table", confidence=0.8,
                raw=f"{cpu_model} | {bios_raw}"[:200], fetched_at=_now(),
            ))
    return rows, bool(rows)


# --------------------------------------------------------------------------
SOURCE_TYPE = {
    "intel": "intel_ark", "amd": "amd_product", "nvidia": "nvidia_product",
}


def guess_brand(name: str, given: str) -> str:
    if given:
        return given.lower().strip()
    n = name.lower()
    if "intel" in n or re.search(r"\bcore i[3579]\b|\bcore ultra\b", n):
        return "intel"
    if "ryzen" in n or "amd" in n or "threadripper" in n or re.search(r"\brx ?\d{3,4}\b", n):
        return "amd"
    if "geforce" in n or "rtx" in n or "gtx" in n or "nvidia" in n:
        return "nvidia"
    for v in ("asus", "msi", "gigabyte", "asrock", "biostar"):
        if v in n:
            return v
    return ""


@dataclass
class Part:
    type: str
    name: str
    brand: str = ""
    spec_url: str = ""
    cpu_support_url: str = ""


def process(part: Part, fetcher: Fetcher, todo: list[dict]) -> list[Row]:
    rows: list[Row] = []
    wanted = FIELDS_BY_TYPE.get(part.type, [])
    stype = SOURCE_TYPE.get(part.brand, f"{part.type}_spec"
                            if part.type == "mainboard" else "unknown")

    spec_url = part.spec_url.strip()
    if not spec_url and part.type == "cpu" and part.brand == "intel":
        spec_url = ark_search(fetcher, part.name) or ""
        if spec_url:
            print(f"    ARK 자동검색 → {spec_url}")

    if spec_url:
        best: dict[str, Row] = {}
        note = ""
        try:
            html, src = fetcher.get(spec_url)
            for r in extract_specs(html, part, wanted, stype, spec_url):
                _consider(best, r)
            note = f"[{src}]"
        except Exception as e:
            note = f"[static실패: {e}]"

        missing = set(wanted) - set(best)
        if missing and fetcher.can_render:
            try:
                rhtml = fetcher.render(spec_url)
            except Exception as e:
                rhtml = None
                note += f" [render실패: {e}]"
            if rhtml:
                for r in extract_specs(rhtml, part, list(missing), stype, spec_url):
                    r.method = "render+" + r.method
                    _consider(best, r)
                note += " [render]"
                missing = set(wanted) - set(best)

        rows.extend(best.values())
        for miss in missing:
            todo.append({"name": part.name, "type": part.type, "field": miss,
                         "reason": "not_found(static/render)" if fetcher.can_render
                         else "not_found_on_page", "url": spec_url})
        print(f"    {note} {spec_url}  → {sorted(best) or '없음'}")
    else:
        for miss in wanted:
            todo.append({"name": part.name, "type": part.type, "field": miss,
                         "reason": "no_spec_url", "url": ""})
        print("    스펙 URL 없음 → TODO")

    # 메인보드 최소 BIOS
    if part.type == "mainboard":
        cs_url = part.cpu_support_url.strip()
        if cs_url:
            bios_rows: list[Row] = []
            parsed = False
            try:
                html, src = fetcher.get(cs_url)
                bios_rows, parsed = extract_min_bios(html, part, cs_url)
            except Exception as e:
                src = f"static실패:{e}"
            if not parsed and fetcher.can_render:
                try:
                    rhtml = fetcher.render(cs_url)
                    if rhtml:
                        bios_rows, parsed = extract_min_bios(rhtml, part, cs_url)
                        src = "render"
                except Exception as e:
                    src = f"render실패:{e}"
            if parsed:
                rows.extend(bios_rows)
                print(f"    [{src}] CPU 지원표  → {len(bios_rows)} rows")
            else:
                todo.append({"name": part.name, "type": part.type, "field": "min_bios",
                             "reason": "table_not_parseable(JS/PDF?)", "url": cs_url})
                print(f"    [{src}] CPU 지원표 파싱 실패 → TODO")
        else:
            todo.append({"name": part.name, "type": part.type, "field": "min_bios",
                         "reason": "no_cpu_support_url", "url": ""})
    return rows


# --------------------------------------------------------------------------
def load_parts(only: set[str] | None) -> list[Part]:
    parts: list[Part] = []
    with IN_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(r for r in f if not r.lstrip().startswith("#"))
        for d in reader:
            t = (d.get("type") or "").strip().lower()
            n = (d.get("name") or "").strip()
            if not t or not n:
                continue
            if only and t not in only:
                continue
            parts.append(Part(
                type=t, name=n,
                brand=guess_brand(n, (d.get("brand") or "").strip()),
                spec_url=(d.get("spec_url") or "").strip(),
                cpu_support_url=(d.get("cpu_support_url") or "").strip(),
            ))
    return parts


def write_outputs(rows: list[Row], todo: list[dict]):
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    with OUT_RAW.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: getattr(r, c) for c in CSV_COLS})

    nested: dict = {}
    for r in rows:
        p = nested.setdefault(r.name, {"type": r.type, "fields": {}, "min_bios": []})
        entry = {
            "value": r.value, "unit": r.unit, "source_url": r.source_url,
            "source_type": r.source_type, "method": r.method,
            "confidence": r.confidence, "fetched_at": r.fetched_at, "raw": r.raw,
        }
        if r.field == "min_bios":
            p["min_bios"].append({"cpu": r.key, **entry})
        else:
            prev = p["fields"].get(r.field)
            if prev is None or r.confidence > prev["confidence"]:
                p["fields"][r.field] = entry
    OUT_JSON.write_text(json.dumps(nested, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_TODO.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "type", "field", "reason", "url"])
        w.writeheader()
        w.writerows(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.2, help="전역 최소 요청 간격(초)")
    ap.add_argument("--limit", type=int, default=0, help="처리할 부품 수 제한(0=전체)")
    ap.add_argument("--only", default="", help="처리할 type 목록 (예: cpu,gpu)")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 재요청")
    ap.add_argument("--browser-ua", action="store_true",
                    help="봇 UA 대신 Chrome UA 사용 (WAF 차단 사이트 재시도용)")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="robots.txt 무시 (권장하지 않음)")
    ap.add_argument("--render", action="store_true",
                    help="정적 추출이 못 채운 필드는 headless Chrome 로 렌더 후 재시도")
    ap.add_argument("--render-budget", type=int, default=12000,
                    help="렌더 대기(virtual-time-budget) ms (기본 12000)")
    args = ap.parse_args()

    if args.delay < 1.0:
        print("경고: --delay 가 1.0 미만입니다. 초당 1건 이하 정책 위반.", file=sys.stderr)
    if args.ignore_robots:
        print("경고: robots.txt 를 무시합니다. 각 사이트 약관을 직접 확인하세요.", file=sys.stderr)

    only = {s.strip().lower() for s in args.only.split(",") if s.strip()} or None
    parts = load_parts(only)
    if args.limit:
        parts = parts[:args.limit]
    if not parts:
        sys.exit(f"{IN_CSV} 에서 처리할 부품이 없습니다.")

    fetcher = Fetcher(RateLimiter(args.delay), args.ignore_robots, args.force,
                      ua=BROWSER_UA if args.browser_ua else USER_AGENT,
                      render=args.render, render_budget_ms=args.render_budget)
    if args.render:
        print(f"render 모드: {fetcher.chrome or 'Chrome/Edge 미발견 → 정적만 사용'}")
    all_rows: list[Row] = []
    todo: list[dict] = []

    for i, part in enumerate(parts, 1):
        print(f"[{i}/{len(parts)}] {part.type} · {part.name} (brand={part.brand or '?'})")
        try:
            all_rows.extend(process(part, fetcher, todo))
        except KeyboardInterrupt:
            print("중단됨 — 여기까지 결과 저장")
            break
        except Exception as e:
            print(f"    !! 처리 실패: {e}")
            for fld in FIELDS_BY_TYPE.get(part.type, []):
                todo.append({"name": part.name, "type": part.type, "field": fld,
                             "reason": f"error: {e}", "url": part.spec_url})

    write_outputs(all_rows, todo)
    print(f"\n완료: {len(all_rows)} 값  →  {OUT_RAW.name}, {OUT_JSON.name}")
    print(f"      미해결 {len(todo)} 건  →  {OUT_TODO.name} (사람이 URL·값 채우기)")


if __name__ == "__main__":
    main()
