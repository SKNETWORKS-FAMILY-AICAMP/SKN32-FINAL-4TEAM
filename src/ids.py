"""Stable, deterministic UUID derivation shared across catalog/material code.

Moved out of `src/repo/rag_repo.py` when the PostgreSQL `rag` schema was dropped
(develop `da79839` / P0 v3) so catalog synthetic-id derivation (P2) does not depend
on a module that otherwise only concerns the removed vector-search path.
"""

from uuid import NAMESPACE_URL, UUID, uuid5


def stable_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, "truefit:synthetic:" + key)
