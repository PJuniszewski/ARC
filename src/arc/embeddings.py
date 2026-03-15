"""Embedding generation and vector search — sentence-transformers with TF-IDF fallback."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class EmbeddingIndex:
    """Descriptor for an embedding index shard."""

    model: str
    dimensions: int
    version: str = "1.0"
    namespace: str = "default"
    count: int = 0


@dataclass
class VectorStore:
    """In-memory vector store with cosine similarity search."""

    ids: list[str] = field(default_factory=list)
    vectors: Optional[np.ndarray] = None  # shape: (n, dim)
    texts: list[str] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    index_info: Optional[EmbeddingIndex] = None

    def add(self, id: str, vector: np.ndarray, text: str = "", meta: dict | None = None):
        self.ids.append(id)
        self.texts.append(text)
        self.metadata.append(meta or {})
        if self.vectors is None:
            self.vectors = vector.reshape(1, -1)
        else:
            self.vectors = np.vstack([self.vectors, vector.reshape(1, -1)])

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[tuple[str, float, str]]:
        """Search by cosine similarity. Returns [(id, score, text), ...]."""
        if self.vectors is None or len(self.ids) == 0:
            return []

        # Cosine similarity
        query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-10)
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True) + 1e-10
        normalized = self.vectors / norms
        scores = normalized @ query_norm.reshape(-1, 1)
        scores = scores.flatten()

        # Top-k
        k = min(top_k, len(self.ids))
        top_indices = np.argsort(scores)[-k:][::-1]

        results = []
        for idx in top_indices:
            results.append((self.ids[idx], float(scores[idx]), self.texts[idx]))
        return results

    def to_dict(self) -> dict:
        return {
            "ids": self.ids,
            "vectors": self.vectors.tolist() if self.vectors is not None else [],
            "texts": self.texts,
            "metadata": self.metadata,
            "index_info": {
                "model": self.index_info.model,
                "dimensions": self.index_info.dimensions,
                "version": self.index_info.version,
                "namespace": self.index_info.namespace,
                "count": self.index_info.count,
            } if self.index_info else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VectorStore:
        vs = cls()
        vs.ids = d.get("ids", [])
        vs.texts = d.get("texts", [])
        vs.metadata = d.get("metadata", [])
        vectors_data = d.get("vectors", [])
        if vectors_data:
            vs.vectors = np.array(vectors_data, dtype=np.float32)
        if d.get("index_info"):
            vs.index_info = EmbeddingIndex(**d["index_info"])
        return vs


class TfidfEmbedder:
    """TF-IDF based embedder — works without any ML dependencies."""

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions
        self.vocab: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.fitted = False

    def fit(self, texts: list[str]) -> None:
        """Build vocabulary and IDF from corpus."""
        n_docs = len(texts)
        doc_freq: Counter[str] = Counter()
        all_words: Counter[str] = Counter()

        for text in texts:
            words = self._tokenize(text)
            all_words.update(words)
            unique_words = set(words)
            doc_freq.update(unique_words)

        # Select top-N words as vocabulary
        top_words = [w for w, _ in all_words.most_common(self.dimensions)]
        self.vocab = {w: i for i, w in enumerate(top_words)}

        # Compute IDF
        for word, idx in self.vocab.items():
            self.idf[word] = math.log((n_docs + 1) / (doc_freq.get(word, 0) + 1)) + 1

        self.fitted = True

    def embed(self, text: str) -> np.ndarray:
        """Generate TF-IDF embedding vector for text."""
        if not self.fitted:
            # Single-text fallback: hash-based embedding
            return self._hash_embed(text)

        words = self._tokenize(text)
        tf = Counter(words)
        max_tf = max(tf.values()) if tf else 1

        vector = np.zeros(self.dimensions, dtype=np.float32)
        for word, count in tf.items():
            if word in self.vocab:
                idx = self.vocab[word]
                tf_norm = count / max_tf
                vector[idx] = tf_norm * self.idf.get(word, 1.0)

        # L2 normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed multiple texts."""
        return np.array([self.embed(t) for t in texts], dtype=np.float32)

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r'\b\w{2,}\b', text.lower())
        return [self._stem(w) for w in words]

    @staticmethod
    def _stem(word: str) -> str:
        """Minimal suffix stemmer for TF-IDF vocabulary matching."""
        if word.endswith('ing') and len(word) > 5:
            stem = word[:-3]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            return stem
        if word.endswith('tion') and len(word) > 5:
            return word[:-4]
        if word.endswith('ness') and len(word) > 5:
            return word[:-4]
        if word.endswith('ment') and len(word) > 5:
            return word[:-4]
        if word.endswith('ies') and len(word) > 4:
            return word[:-3] + 'y'
        if word.endswith('es') and len(word) > 4:
            return word[:-2]
        if word.endswith('s') and not word.endswith('ss') and len(word) > 3:
            return word[:-1]
        if word.endswith('ed') and len(word) > 4:
            return word[:-2]
        return word

    def _hash_embed(self, text: str) -> np.ndarray:
        """Hash-based embedding for unfitted embedder."""
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for word in self._tokenize(text):
            idx = hash(word) % self.dimensions
            vector[idx] += 1.0
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def get_index_info(self) -> EmbeddingIndex:
        return EmbeddingIndex(
            model="tfidf",
            dimensions=self.dimensions,
            version="1.0",
            namespace="default",
            count=len(self.vocab),
        )


def try_load_sentence_transformer():
    """Try to load sentence-transformers. Returns embedder or None."""
    try:
        from sentence_transformers import SentenceTransformer

        class SentenceTransformerEmbedder:
            def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
                self.model = SentenceTransformer(model_name)
                self.dimensions = self.model.get_sentence_embedding_dimension()
                self.model_name = model_name

            def fit(self, texts: list[str]) -> None:
                pass  # Pre-trained, no fitting needed

            def embed(self, text: str) -> np.ndarray:
                return self.model.encode(text, normalize_embeddings=True)

            def embed_batch(self, texts: list[str]) -> np.ndarray:
                return self.model.encode(texts, normalize_embeddings=True)

            def get_index_info(self) -> EmbeddingIndex:
                return EmbeddingIndex(
                    model=self.model_name,
                    dimensions=self.dimensions,
                    version="1.0",
                )

        return SentenceTransformerEmbedder()
    except ImportError:
        return None


def get_embedder(dimensions: int = 256) -> TfidfEmbedder:
    """Get the best available embedder. Falls back to TF-IDF."""
    st = try_load_sentence_transformer()
    if st is not None:
        return st
    return TfidfEmbedder(dimensions=dimensions)
