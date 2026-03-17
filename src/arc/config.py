"""Configuration constants for ARC Archive loader and builder."""

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
