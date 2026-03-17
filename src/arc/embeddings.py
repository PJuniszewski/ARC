"""Embedding generation and vector search — sentence-transformers with TF-IDF fallback."""

from __future__ import annotations

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
    embedder_state: dict = field(default_factory=dict)

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
            "embedder_state": self.embedder_state,
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
        vs.embedder_state = d.get("embedder_state", {})
        return vs

    def restore_embedder(self):
        """Restore the embedder that was used at build time.

        Checks index_info.model to determine the embedder type:
        - "tfidf": restore from stored vocab/idf state
        - other: try loading as a sentence-transformer model
        Returns None if restoration fails.
        """
        # Try TF-IDF restoration from stored state
        if self.embedder_state:
            vocab = self.embedder_state.get("vocab")
            idf = self.embedder_state.get("idf")
            if vocab and idf:
                dims = self.embedder_state.get("dimensions", 256)
                embedder = TfidfEmbedder(dimensions=dims)
                embedder.vocab = vocab
                embedder.idf = idf
                embedder.fitted = True
                return embedder

        # Try sentence-transformer based on index model name
        if self.index_info and self.index_info.model != "tfidf":
            st = try_load_sentence_transformer(self.index_info.model)
            if st is not None:
                return st

        return None


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


_st_cache: dict = {}


def try_load_sentence_transformer(model_name: str = "all-MiniLM-L6-v2"):
    """Try to load sentence-transformers. Returns embedder or None.

    Caches the loaded model so repeated calls don't re-download or re-init.
    """
    if model_name in _st_cache:
        return _st_cache[model_name]

    try:
        from sentence_transformers import SentenceTransformer

        class SentenceTransformerEmbedder:
            def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
                self.model = SentenceTransformer(model_name)
                self.dimensions = self.model.get_sentence_embedding_dimension()
                self.model_name = model_name
                self.fitted = True  # pre-trained

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

            # Reuse TfidfEmbedder's tokenizer for keyword matching in the
            # loader. Embedding uses the neural model; tokenization is
            # only for the hybrid keyword boost.
            _stem = staticmethod(TfidfEmbedder._stem)

            def _tokenize(self, text: str) -> list[str]:
                words = re.findall(r'\b\w{2,}\b', text.lower())
                return [self._stem(w) for w in words]

        embedder = SentenceTransformerEmbedder(model_name)
        # Validate model loaded correctly (not a garbage fallback)
        test_vec = embedder.embed("test sentence")
        if test_vec is None or len(test_vec) < 32:
            _st_cache[model_name] = None
            return None
        # all-MiniLM-L6-v2 has 384 dims; reject suspiciously small models
        if embedder.dimensions < 64:
            _st_cache[model_name] = None
            return None
        _st_cache[model_name] = embedder
        return embedder
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load sentence-transformer %r: %s", model_name, e)
        _st_cache[model_name] = None
        return None


def get_embedder(dimensions: int = 256, force_tfidf: bool = False):
    """Get the best available embedder. Falls back to TF-IDF.

    Args:
        dimensions: Dimensions for TF-IDF embedder (ignored for sentence-transformers).
        force_tfidf: If True, skip sentence-transformers and use TF-IDF.
    """
    if not force_tfidf:
        st = try_load_sentence_transformer()
        if st is not None:
            return st
    return TfidfEmbedder(dimensions=dimensions)
