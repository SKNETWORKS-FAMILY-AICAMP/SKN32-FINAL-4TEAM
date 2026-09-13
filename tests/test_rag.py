"""Offline contracts; no cloud or DB required."""

import io
import json
import shutil
from pathlib import Path

import pytest

from src.rag.contracts import EmbeddingError, SearchRequest
from src.rag.embedding import BedrockEmbedder, LocalHashEmbedder, validate_vector
from src.rag.ingestion import read_manual

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "generated/synthetic_manuals/stroller_example"


def test_manual_conditions_and_exact_locators():
    doc = read_manual(BUNDLE)
    assert len(doc.chunks) == 5
    for chunk in doc.chunks:
        assert (
            doc.text[chunk.locator["char_start"] : chunk.locator["char_end"]]
            == chunk.text
        )
        assert doc.text.splitlines()[chunk.locator["line_start"] - 1].startswith("## ")
    eligibility = doc.chunks[0].text
    assert all(
        s in eligibility for s in ["6 개월", "22 kg", "혼자 앉을 수 있음", "모두 충족"]
    )


def test_answer_ledger_not_read(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "bundle")
    root = tmp_path / "bundle"
    (root / "facts.jsonl").write_text(
        "POISONED_GOLD: seat limit is 999 kg", encoding="utf-8"
    )
    (root / "product.snapshot.json").unlink()
    (root / "profile.snapshot.json").unlink()
    doc = read_manual(root)
    assert all(
        "999" not in c.text and "POISONED_GOLD" not in c.text for c in doc.chunks
    )


@pytest.mark.parametrize("filename", ["manual.md", "mapping.json"])
def test_changed_artifact_rejected(tmp_path, filename):
    shutil.copytree(BUNDLE, tmp_path / "bundle")
    with (tmp_path / "bundle" / filename).open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="hash_mismatch"):
        read_manual(tmp_path / "bundle")


def test_local_embedding_is_deterministic_and_explicit():
    model = LocalHashEmbedder()
    vectors = model.embed(["바구니 최대 하중", "바구니 최대 하중", "신생아 구성"])
    assert vectors[0] == vectors[1] and vectors[0] != vectors[2]
    assert "local-test" in model.profile_key
    assert sum(v * v for v in vectors[0]) == pytest.approx(1)


@pytest.mark.parametrize(
    "vector",
    [[0.0] * 1024, [float("nan")] * 1024, [float("inf")] * 1024, [1.0], [True] * 1024],
)
def test_invalid_vectors_rejected(vector):
    with pytest.raises(EmbeddingError):
        validate_vector(vector, 1024)


def test_bedrock_request_contract_and_body_close():
    class Client:
        calls = []

        def invoke_model(self, **kwargs):
            self.calls.append(kwargs)
            self.body = io.BytesIO(
                json.dumps({"embedding": [1.0] + [0.0] * 1023}).encode()
            )
            return {"body": self.body}

    client = Client()
    model = BedrockEmbedder(client=client)
    assert len(model.embed(["한 손 접기"])[0]) == 1024
    payload = json.loads(client.calls[0]["body"])
    assert payload == {
        "inputText": "한 손 접기",
        "dimensions": 1024,
        "normalize": True,
        "embeddingTypes": ["float"],
    }
    assert client.body.closed


def test_bedrock_outage_never_falls_back():
    class FailingClient:
        def invoke_model(self, **kwargs):
            raise RuntimeError("private-endpoint-and-secret")

    with pytest.raises(EmbeddingError, match="^embedding_unavailable$"):
        BedrockEmbedder(client=FailingClient()).embed(["query"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"product_key": ""},
        {"query": " "},
        {"k": 0},
        {"corpus": "all"},
        {"domain": "anything"},
    ],
)
def test_invalid_scope(overrides):
    args = {"domain": "baby", "product_key": "SYN-STROLLER-001", "query": "체중"}
    with pytest.raises(ValueError):
        SearchRequest(**{**args, **overrides})
