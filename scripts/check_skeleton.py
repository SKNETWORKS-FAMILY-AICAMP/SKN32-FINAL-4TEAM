#!/usr/bin/env python3
"""뼈대가 제대로 섰는지 확인하는 헬스체크.

    python scripts/check_skeleton.py

DB·네트워크 없이 돈다. "실제 로직이 맞는지"가 아니라 "구조·연결·문법"만 본다.
"""
from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(*args):
    return subprocess.run(list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_ENV)


ok = True


def check(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok = ok and passed
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))


# 1. 문법
files = list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
r = _run(sys.executable, "-m", "py_compile", *map(str, files))
check("전 파일 문법", r.returncode == 0, f"{len(files)}개" if r.returncode == 0 else r.stderr.strip()[:200])

# 2. import (순환·오타·끊긴 참조)
import src  # noqa: E402

bad = []
for m in pkgutil.walk_packages(src.__path__, "src."):
    try:
        importlib.import_module(m.name)
    except Exception as e:  # noqa: BLE001
        bad.append(f"{m.name}: {e!r}")
check("전 모듈 import", not bad, "; ".join(bad) if bad else "순환/누락 없음")

# 3. FastAPI 앱 + 엔드포인트
try:
    from src.api import app

    paths = app.openapi()["paths"]
    n_ops = sum(len(v) for v in paths.values())
    check("FastAPI 앱 조립", n_ops >= 20, f"{len(paths)} 경로 / {n_ops} 오퍼레이션")
except Exception as e:  # noqa: BLE001
    check("FastAPI 앱 조립", False, repr(e))

# 4. 엔진 파이프라인 e2e
r = _run(sys.executable, str(ROOT / "main.py"), "computer_research")
check("엔진 파이프라인 완주", "파이프라인 종료" in (r.stdout or ""), r.stderr.strip()[:200])
r = _run(sys.executable, "-m", "pytest", "-q", str(ROOT / "tests"))
check("pytest 스모크", r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else "")

# 5. stub 신호 (미구현은 NotImplementedError 를 던지는가)
total = stub = 0
for m in pkgutil.walk_packages(src.__path__, "src."):
    mod = importlib.import_module(m.name)
    members = list(inspect.getmembers(mod, inspect.isfunction))
    for _, obj in list(inspect.getmembers(mod, inspect.isclass)):
        if obj.__module__ == m.name:
            members += [(n, f) for n, f in inspect.getmembers(obj, inspect.isfunction)
                        if f.__qualname__.startswith(obj.__name__)]
    for _, f in members:
        if getattr(f, "__module__", None) != m.name:
            continue
        total += 1
        try:
            if "NotImplementedError" in inspect.getsource(f):
                stub += 1
        except OSError:
            pass
check("stub 명시성", stub > total / 5, f"함수/메서드 {total}개 중 {stub}개 명시적 미구현")

# 6. 구조 대조 (기대 개수)
def cnt(glob: str) -> int:
    return len([p for p in (ROOT / "src").glob(glob) if p.stem != "__init__"])

exp = {"repo/*.py": 11, "services/*.py": 6, "routers/*.py": 5, "workers/*.py": 5}
struct_ok = all(cnt(g) == v for g, v in exp.items())
check("구조 개수", struct_ok, " ".join(f"{g.split('/')[0]}={cnt(g)}/{v}" for g, v in exp.items()))
check("엔진 8단계+[6]", len(list((ROOT / "src/engine").glob("stage*.py"))) == 9)
migrations = sorted((ROOT / "db/migrations").glob("*.sql"))
versions = [int(p.name.split("_", 1)[0]) for p in migrations]
check("마이그레이션 순서", len(versions) >= 6 and versions == list(range(len(versions))),
      f"{len(versions)}개 연속 버전")

print()
print("전체:", "PASS — 뼈대 정상" if ok else "FAIL — 위 항목 확인")
sys.exit(0 if ok else 1)
