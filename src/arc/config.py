"""Configuration constants for ARC loader and builder."""

# --- Selective loading thresholds ---

# Minimum hybrid score for a claim to be included in primary selection
MIN_SCORE: float = 0.15

# Minimum hybrid score for evidence graph expansion candidates
EXPANSION_MIN: float = 0.10

# Maximum claims returned from task-based filtering
MAX_FILTERED_CLAIMS: int = 12

# Top-K claims to consider in primary selection (adjusted by archive size)
TOP_K_BASE: int = 8

# Minimum top-K floor regardless of archive size
TOP_K_FLOOR: int = 3

# Fraction of total claims used to compute dynamic top-K
TOP_K_RATIO: float = 0.1

# --- BFS graph traversal ---

# Minimum hybrid score for BFS expansion in evidence graph traversal
BFS_EXPANSION_MIN: float = 0.10

# Maximum results from BFS graph traversal
MAX_BFS_RESULTS: int = 30

# --- Keyword scoring ---

# Keyword boost weight applied to vector similarity scores
KEYWORD_BOOST_WEIGHT: float = 0.3

# Heading match boost weight for section-heading alignment
HEADING_BOOST_WEIGHT: float = 0.2

# Minimum heading token match ratio to trigger heading boost
HEADING_MATCH_THRESHOLD: float = 0.5

# Minimum shared tokens for keyword seeding in graph traversal
KEYWORD_SEED_MIN_TOKENS: int = 3

# Stop words excluded from content-aware keyword matching
STOP_WORDS: frozenset[str] = frozenset({
    "the", "is", "are", "was", "were", "in", "on", "at", "to", "for",
    "of", "and", "or", "an", "be", "by", "it", "do", "no", "not",
    "what", "how", "which", "who", "when", "where", "why", "that",
    "this", "with", "from", "has", "have", "does", "did", "will",
    "can", "should", "would", "could", "may", "use", "used",
})

# --- Scoped retrieval limits ---

# Max files after scope reduction
MAX_SCOPE_FILES: int = 50

# Max chunks after phase 1 narrowing
MAX_PHASE1_CHUNKS: int = 200

# Max chunks into phase 2 hybrid scoring
MAX_PHASE2_CHUNKS: int = 30

# Max claims in final output
MAX_SCOPED_CLAIMS: int = 20

# Max raw chunks kept verbatim
MAX_RAW_PASSTHROUGH: int = 8

# Token budget for scoped output
SCOPED_TOKEN_BUDGET: int = 4000

# Min score for path inclusion in scope
PATH_MATCH_THRESHOLD: float = 0.3

# --- Retrieval hygiene penalties ---

# Score multiplier for migration data files (0001_initial.py etc.)
MIGRATION_SCORE_PENALTY: float = 0.3

# Score multiplier for short keyword-heavy chunks
SHORT_CHUNK_PENALTY: float = 0.4

# Score multiplier for boilerplate __init__.py files
BOILERPLATE_PENALTY: float = 0.5

# Token threshold below which a chunk is considered "short"
SHORT_CHUNK_TOKEN_THRESHOLD: int = 10

# --- Dynamic retrieval-k by query mode ---

# retrieval_k for cross-file queries
CROSS_FILE_RETRIEVAL_K: int = 55

# retrieval_k for feature-scoped queries
FEATURE_RETRIEVAL_K: int = 45

# --- Sibling chunk expansion ---

# Max sibling chunks added per file
MAX_SIBLINGS_PER_FILE: int = 2

# Max total expansion chunks across all files
MAX_EXPANSION_TOTAL: int = 8

# Minimum hybrid score for a sibling to be eligible
SIBLING_MIN_SCORE: float = 0.10
