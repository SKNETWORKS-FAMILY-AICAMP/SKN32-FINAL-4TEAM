"""Explicit Bedrock embedding and offline lexical test baseline."""

from __future__ import annotations
import hashlib
import json
import math
import os
from collections import Counter
from src.rag.contracts import EmbeddingError
from src.rag.text import VERSION, normalize, tokens


def validate_vector(vector, dimensions: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise EmbeddingError("embedding_dimension_mismatch")
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in vector
    ):
        raise EmbeddingError("embedding_not_finite")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise EmbeddingError("embedding_zero_vector")
    return [float(v / norm) for v in vector]


class LocalHashEmbedder:
    """Lexical feature hashing for regression ONLY; not semantic embeddings.
    Never substituted for a failed Bedrock call.
    """

    dimensions = 1024
    provider = "local-test"
    model = "lexical-hash-v1"
    profile_key = f"local-test-lexical-hash-v1-1024-{VERSION}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for token, count in Counter(tokens(text)).items():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vec[index] += (1 if digest[4] & 1 else -1) * (1 + math.log(count))
            result.append(validate_vector(vec, self.dimensions))
        return result


class BedrockEmbedder:
    provider = "bedrock"
    dimensions = 1024

    def __init__(self, *, model=None, region=None, client=None):
        self.model = (
            model or os.getenv("EMBEDDING_MODEL") or "amazon.titan-embed-text-v2:0"
        )
        self.profile_key = f"bedrock-{self.model}-1024-{VERSION}"
        self.client = client
        self.region = region or os.getenv("AWS_REGION") or os.getenv("LLM_REGION")

    def _client(self):
        if self.client is None:
            if not self.region:
                raise EmbeddingError("embedding_region_missing")
            import boto3
            from botocore.config import Config

            self.client = boto3.Session().client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=20,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        return self.client

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            if not text.strip() or len(text) > 12000:
                raise EmbeddingError("embedding_input_invalid")
            try:
                response = self._client().invoke_model(
                    modelId=self.model,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(
                        {
                            "inputText": normalize(text),
                            "dimensions": self.dimensions,
                            "normalize": True,
                            "embeddingTypes": ["float"],
                        }
                    ),
                )
                body = response["body"]
                try:
                    value = json.loads(body.read())
                finally:
                    body.close()
                result.append(validate_vector(value["embedding"], self.dimensions))
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError("embedding_unavailable") from exc
        return result


def get_embedder():
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", "bedrock")
    if provider == "bedrock":
        return BedrockEmbedder()
    if provider == "local-test":
        return LocalHashEmbedder()
    raise ValueError("RAG_EMBEDDING_PROVIDER must be bedrock or local-test")


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().embed(texts)
