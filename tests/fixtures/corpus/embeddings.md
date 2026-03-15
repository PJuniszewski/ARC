# Embedding Strategy

## Approach

ARC uses embeddings for two purposes: build-time duplicate detection and runtime selective loading. The embedding index is stored as a versioned layer in the archive.

## Model Selection

The default embedding model is TF-IDF with 256 dimensions. When sentence-transformers are available, the system upgrades to all-MiniLM-L6-v2 for better semantic similarity. Both models produce L2-normalized vectors for consistent cosine similarity computation.

## Hybrid Search

For best results, ARC combines embedding similarity with keyword matching. This hybrid approach captures both semantic meaning and exact terminology. The embedding layer provides the semantic component while text matching provides lexical precision.

## Index Versioning

Embedding indexes must be versioned alongside the archive content. An index generated with one model cannot be used with another. The EmbeddingIndex metadata tracks model name, dimensions, version, and namespace to prevent mismatched usage.
