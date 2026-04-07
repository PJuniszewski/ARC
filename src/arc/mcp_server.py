"""ARC MCP Server — expose ARC operations as tools for any MCP-compatible agent.

Usage:
    python -m arc.mcp_server          # stdio transport
    arc mcp-serve                      # via CLI entry point

Connect from Claude Code (.claude/mcp.json):
    {
      "mcpServers": {
        "arc": {
          "command": "python",
          "args": ["-m", "arc.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    raise ImportError(
        "MCP support requires the mcp package. Install with: pip install arc-context[mcp]"
    )

logger = logging.getLogger(__name__)

server = Server("arc")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="arc_build",
        description=(
            "Build a .arc context archive from a source directory. "
            "Scans code and docs, extracts typed claims with evidence, "
            "produces a single SQLite file. Call once per repo, not per query. "
            "Use --extract-with-llm for richer claims (requires API key)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_dir": {"type": "string", "description": "Path to source directory"},
                "output_path": {"type": "string", "description": "Where to write the .arc file"},
                "extract_with_llm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Use LLM for richer claims (optional, needs API key)",
                },
            },
            "required": ["source_dir", "output_path"],
        },
    ),
    Tool(
        name="arc_load",
        description=(
            "Query an ARC archive with a natural language question. "
            "Returns typed claims (observation/decision/uncertainty/dependency) "
            "with evidence pointing to exact source file and line range. "
            "This is the primary tool — ask a question, get structured answers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "arc_path": {"type": "string", "description": "Path to .arc file"},
                "task": {"type": "string", "description": "Natural language query (omit to return all claims)"},
                "claim_type": {
                    "type": "string",
                    "enum": ["observation", "decision", "uncertainty", "dependency", "conflict"],
                    "description": "Filter by claim type (optional)",
                },
                "source": {"type": "string", "description": "Filter by source agent (optional)"},
                "full": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return all claims above minimum threshold (maximum recall)",
                },
            },
            "required": ["arc_path"],
        },
    ),
    Tool(
        name="arc_snapshot",
        description=(
            "Package claims as a lightweight .arc artifact for handoff to another agent. "
            "Takes a list of typed claims you've produced and creates a verifiable artifact. "
            "The receiving agent can load it with arc_load."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Where to write the snapshot .arc"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "claim_type": {
                                "type": "string",
                                "enum": ["observation", "decision", "uncertainty", "dependency"],
                            },
                            "confidence": {"type": "number", "default": 0.8},
                        },
                        "required": ["text", "claim_type"],
                    },
                    "description": "Claims to package",
                },
                "source": {"type": "string", "description": "Your agent identifier"},
            },
            "required": ["output_path", "claims", "source"],
        },
    ),
    Tool(
        name="arc_merge",
        description=(
            "Merge two .arc artifacts from parallel agents into one. "
            "Observations coexist, conflicting decisions are flagged. "
            "Returns the merged artifact path and any detected conflicts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "arc_a": {"type": "string", "description": "Path to first .arc"},
                "arc_b": {"type": "string", "description": "Path to second .arc"},
                "output_path": {"type": "string", "description": "Where to write merged .arc"},
            },
            "required": ["arc_a", "arc_b", "output_path"],
        },
    ),
    Tool(
        name="arc_verify",
        description=(
            "Verify the integrity of an .arc artifact. "
            "Checks Merkle seals, blob digests, manifest consistency. "
            "Use before trusting an artifact from an external source."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "arc_path": {"type": "string", "description": "Path to .arc file"},
            },
            "required": ["arc_path"],
        },
    ),
    Tool(
        name="arc_diff",
        description=(
            "Compare two .arc artifacts. Shows added/removed/changed claims, "
            "blob reuse ratio, and structural differences between versions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "arc_a": {"type": "string", "description": "Path to first .arc"},
                "arc_b": {"type": "string", "description": "Path to second .arc"},
            },
            "required": ["arc_a", "arc_b"],
        },
    ),
    Tool(
        name="arc_inspect",
        description=(
            "Get a quick overview of an .arc artifact: layers, claim counts by type, "
            "sources, blob count, archive size. No claims loaded."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "arc_path": {"type": "string", "description": "Path to .arc file"},
            },
            "required": ["arc_path"],
        },
    ),
]


@server.list_tools()
async def handle_list_tools():
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    try:
        result = _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        error = {"error": str(e), "tool": name, "traceback": traceback.format_exc()[-500:]}
        return [TextContent(type="text", text=json.dumps(error, indent=2))]


# ---------------------------------------------------------------------------
# Tool implementations — thin wrappers around existing API
# ---------------------------------------------------------------------------

def _dispatch(name: str, args: dict) -> dict:
    handlers = {
        "arc_build": _tool_build,
        "arc_load": _tool_load,
        "arc_snapshot": _tool_snapshot,
        "arc_merge": _tool_merge,
        "arc_verify": _tool_verify,
        "arc_diff": _tool_diff,
        "arc_inspect": _tool_inspect,
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(args)


def _tool_build(args: dict) -> dict:
    from .builder import build_archive

    source_dir = args["source_dir"]
    output_path = args["output_path"]
    extract_with_llm = args.get("extract_with_llm", False)

    if not Path(source_dir).is_dir():
        return {"error": f"Source directory not found: {source_dir}"}

    result = build_archive(
        source_dir=source_dir,
        output_dir=output_path,
        force_tfidf=not extract_with_llm,
        output_format="sqlite",
        extract_with_llm=extract_with_llm,
    )

    if not result.valid:
        return {"error": f"Build failed: {result.errors}"}

    return {
        "artifact": str(result.archive_path),
        "files_scanned": len(result.resources),
        "claims_extracted": len(result.claims),
        "decisions_extracted": len(result.decisions),
        "artifact_size_kb": round(Path(output_path).stat().st_size / 1024),
        "valid": True,
    }


def _tool_load(args: dict) -> dict:
    from .loader import load

    arc_path = args["arc_path"]
    task = args.get("task")
    claim_type = args.get("claim_type")
    source = args.get("source")
    full = args.get("full", False)

    loaded = load(
        arc_path,
        task=task,
        claim_type=claim_type,
        source=source,
        full=full,
    )

    if loaded.rejected:
        return {"error": loaded.reason, "path": arc_path}

    # Build evidence lookup
    su_by_id = {s.id: s for s in loaded.source_units}
    res_by_id = {r.id: r for r in loaded.resources}

    claims = []
    for c in loaded.claims:
        source_file = ""
        line_span = None
        if c.evidence:
            su = su_by_id.get(c.evidence[0].source_unit_id)
            if su:
                res = res_by_id.get(su.resource_id)
                source_file = res.locator if res else ""
                line_span = list(su.span)

        claims.append({
            "text": c.text,
            "type": c.claim_type,
            "source": c.source,
            "confidence": c.confidence,
            "source_file": source_file,
            "line_span": line_span,
        })

    return {
        "query": task,
        "claims_returned": len(claims),
        "claims": claims,
    }


def _tool_snapshot(args: dict) -> dict:
    from .create import create_archive
    from .models import Claim

    output_path = args["output_path"]
    source = args["source"]
    raw_claims = args["claims"]

    claims = []
    for rc in raw_claims:
        claims.append(Claim(
            text=rc["text"],
            claim_type=rc["claim_type"],
            source=source,
            confidence=rc.get("confidence", 0.8),
        ))

    manifest = create_archive(output_path, claims, source=source)

    return {
        "artifact": output_path,
        "claims_packaged": len(claims),
        "archive_id": manifest.archive_id,
    }


def _tool_merge(args: dict) -> dict:
    from .merge import merge

    result, manifest = merge(args["arc_a"], args["arc_b"], args["output_path"])

    conflicts = []
    for c in result.conflict_claims:
        conflicts.append({
            "text": c.text,
            "references": c.references,
        })

    return {
        "artifact": args["output_path"],
        "claims_merged": result.merged_claims,
        "duplicates_removed": result.duplicates_removed,
        "conflicts_detected": result.conflicts_detected,
        "conflicts": conflicts,
    }


def _tool_verify(args: dict) -> dict:
    from .loader import verify

    result = verify(args["arc_path"])

    return {
        "valid": result.valid,
        "errors": result.errors,
        "failed_digests": len(result.failed_digests),
        "missing_blobs": len(result.missing_blobs),
    }


def _tool_diff(args: dict) -> dict:
    from .diff import diff_archives

    result = diff_archives(args["arc_a"], args["arc_b"])

    return {
        "new_claims": len(result.new_claims),
        "removed_claims": len(result.removed_claims),
        "new_decisions": len(result.new_decisions),
        "removed_decisions": len(result.removed_decisions),
        "new_blobs": len(result.new_blobs),
        "removed_blobs": len(result.removed_blobs),
        "blob_reuse_ratio": round(result.blob_reuse_ratio, 3),
    }


def _tool_inspect(args: dict) -> dict:
    from .cas import open_cas
    from .manifest import read_manifest_from_cas

    try:
        cas = open_cas(Path(args["arc_path"]))
    except FileNotFoundError:
        return {"error": f"Archive not found: {args['arc_path']}"}

    manifest = read_manifest_from_cas(cas)
    if manifest is None:
        return {"error": "No manifest found"}

    layers = []
    for layer in manifest.layers:
        layers.append({
            "name": layer.name,
            "type": layer.type,
            "required": layer.required,
        })

    return {
        "archive_id": manifest.archive_id,
        "version": manifest.archive_version,
        "schema_version": manifest.schema_version,
        "created_at": manifest.created_at,
        "layers": layers,
        "layer_count": len(layers),
        "parent_archive": manifest.parent_archive,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
