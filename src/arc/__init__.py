"""ARC (Agent Reasoning Context) — portable, verifiable context packaging for AI agents."""

import logging

__version__ = "1.0.0"

# Configure library logging — NullHandler by default so applications
# can attach their own handlers without seeing unexpected output.
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Public API
from .builder import BuildResult, build_archive
from .cas import ContentAddressedStore, VerificationResult, sha256_digest
from .diff import diff_archives
from .loader import LoadedArchive, load, restore_sources, verify
from .models import (
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
    "VerificationResult",
    "sha256_digest",
    # Diff
    "diff_archives",
    # Loader
    "load",
    "verify",
    "restore_sources",
    "LoadedArchive",
    # Models
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
