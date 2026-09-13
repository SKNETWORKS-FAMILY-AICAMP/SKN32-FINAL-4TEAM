"""RAG 자료 추출·임베딩 워커.

queued 인 rag.ingestion_job 을 잡아 rag.ingestion.run_ingestion 실행 →
검토 후 material_repo.publish_revision 로 게시.
"""
from __future__ import annotations


def tick() -> None:
    """큐에서 작업 1건 처리 (행 잠금·재시도)."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit("worker 루프 미구현")
