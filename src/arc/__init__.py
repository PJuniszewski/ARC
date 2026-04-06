"""ARC (Agent Reasoning Context) — portable, verifiable context packaging for AI agents."""

import logging

__version__ = "1.0.0"

# Configure library logging — NullHandler by default so applications
# can attach their own handlers without seeing unexpected output.
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Public API
from .builder import BuildResult, build_archive
from .cas import ContentAddressedStore, SqliteCAS, VerificationResult, create_cas, open_cas, sha256_digest
from .create import create_archive
from .diff import diff_archives
from .merge import merge
from .loader import LoadedArchive, load, restore_sources, verify
from .snapshot import snapshot
from .models import (
    CLAIM_TYPES,
    Claim,
    Decision,
    EvidencePointer,
    Layer,
    Manifest,
    PolicyRule,
    Resource,
    TextUnit,
    ToolDeclaration,
    WorkflowStep,
)

__all__ = [
    # Builder
    "build_archive",
    "BuildResult",
    # CAS
    "ContentAddressedStore",
    "SqliteCAS",
    "VerificationResult",
    "create_cas",
    "open_cas",
    "sha256_digest",
    # Create
    "create_archive",
    # Diff
    "diff_archives",
    # Merge
    "merge",
    # Loader
    "load",
    "verify",
    "restore_sources",
    "LoadedArchive",
    # Snapshot
    "snapshot",
    # Models
    "CLAIM_TYPES",
    "Claim",
    "Decision",
    "EvidencePointer",
    "Layer",
    "Manifest",
    "PolicyRule",
    "Resource",
    "TextUnit",
    "ToolDeclaration",
    "WorkflowStep",
]
