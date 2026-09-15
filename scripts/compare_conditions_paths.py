"""같은 대화를 규칙 추출(slot_rules)과 Strands 에이전트에 각각 넣어 나란히 본다. DB 없음.

    uv run python scripts/compare_conditions_paths.py                 # 내장 예시 (컴퓨터)
    uv run python scripts/compare_conditions_paths.py --category baby "출산 예정이에요" "예산은 50만원"
    uv run python scripts/compare_conditions_paths.py --rules-only ...  # 키 없는 환경

에이전트 쪽은 .env 에 MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY 가 있어야 돈다
(CONDITIONS_AGENT 값은 여기서 보지 않는다 — 비교가 목적이라 항상 둘 다 돌린다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.categories import load_category  # noqa: E402
from src.engine import slot_rules  # noqa: E402
from src.services.session_service import _ALL_SET, _next_question, compute_missing  # noqa: E402

EXAMPLES = {
    "computer": [
        "발로란트랑 롤 위주로 할 게임용 PC 맞추려고요. 예산은 150만원 정도",
        "가성비요. 그리고 케이스는 흰색이었으면 좋겠고 RGB는 없었으면 해요",
        "아 예산 180만원까지는 괜찮아요. QHD 165Hz 모니터 쓸 거예요",
    ],
    "baby": [
        "출산 예정이에요. 수유랑 수면 쪽 물품 위주로 준비하려고요",
        "피부 특이사항은 없고, 아직 가진 건 하나도 없어요. 예산은 50만원",
    ],
}


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def run_rules(category: str, cat_def: dict, turns: list[str]) -> list[dict]:
    """session_service.handle_message 의 규칙 경로를 그대로 흉내 낸다."""
    values: dict = {"category": category}
    out = []
    for text in turns:
        extracted = slot_rules.extract(category, text)
        values.update(extracted)
        nq = _next_question(cat_def, values)
        reply = (nq["text"] if extracted else "죄송해요, 이해하지 못했어요. " + nq["text"]) if nq else _ALL_SET
        out.append({"patches": extracted, "reply": reply, "missing": compute_missing(cat_def, values), "secs": 0.0})
    out.append({"final": {k: v for k, v in values.items() if k != "category"}})
    return out


def run_agent(category: str, cat_def: dict, turns: list[str]) -> list[dict]:
    from src.agent import conditions_agent as ca

    values: dict = {"category": category}
    history: list[dict] = []
    out = []
    for text in turns:
        t0 = time.time()
        r = ca.run_turn(category, cat_def, values, history, text,
                        missing_fn=lambda v: compute_missing(cat_def, v),
                        next_question_fn=lambda v: _next_question(cat_def, v))
        values.update(r.patches)
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": r.reply}]
        out.append({"patches": r.patches, "reply": r.reply, "missing": compute_missing(cat_def, values),
                    "secs": time.time() - t0, "trace": r.trace})
    out.append({"final": {k: v for k, v in values.items() if k != "category"}})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("turns", nargs="*", help="사용자 메시지들 (없으면 내장 예시)")
    ap.add_argument("--category", default="computer", choices=["computer", "baby"])
    ap.add_argument("--rules-only", action="store_true")
    args = ap.parse_args()

    cat_def = load_category(args.category)
    turns = args.turns or EXAMPLES[args.category]

    rules = run_rules(args.category, cat_def, turns)
    agent = None
    if not args.rules_only:
        from src.agent import conditions_agent as ca
        if not (ca.LLM_PROVIDER == "openai" and ca.OPENAI_API_KEY and ca.LLM_MODEL and not ca.MOCK_MODE):
            print("에이전트 쪽은 건너뜀 — .env 에 MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY 필요\n")
        else:
            agent = run_agent(args.category, cat_def, turns)

    for i, text in enumerate(turns):
        print(f"\n{'═' * 100}\n[{i + 1}] 사용자: {text}")
        for label, res in (("규칙", rules), ("에이전트", agent)):
            if res is None:
                continue
            r = res[i]
            print(f"\n  {label:<4} 반영: {_j(r['patches']) if r['patches'] else '(없음)'}")
            print(f"       답변: {r['reply']}")
            print(f"       남은 필수: {_j(r['missing'])}" + (f"   ({r['secs']:.1f}s)" if r["secs"] else ""))
            for line in r.get("trace", []):
                print(f"         · {line}")

    print(f"\n{'═' * 100}\n최종 조건")
    print(f"  규칙:     {_j(rules[-1]['final'])}")
    if agent:
        print(f"  에이전트: {_j(agent[-1]['final'])}")
        only_agent = {k: v for k, v in agent[-1]["final"].items() if rules[-1]["final"].get(k) != v}
        if only_agent:
            print(f"  차이(에이전트만): {_j(only_agent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
