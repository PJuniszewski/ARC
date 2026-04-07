# ARC MCP Server

ARC exposes its operations as MCP tools so any compatible agent (Claude Code, Cursor, Windsurf, Codex) can build, query, and merge context artifacts without shelling out to the CLI.

## Install

```bash
pip install arc-context mcp
```

## Start

```bash
arc mcp-serve                    # via CLI
python -m arc.mcp_server         # directly
```

## Connect from Claude Code

Add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "arc": {
      "command": "python",
      "args": ["-m", "arc.mcp_server"]
    }
  }
}
```

Restart Claude Code. ARC tools appear automatically.

## Connect from Cursor / generic MCP client

Use stdio transport with command `python -m arc.mcp_server`. The server speaks JSON-RPC over stdin/stdout per the MCP spec.

## Tools

### arc_build

Build a .arc archive from a source directory.

```
Input:  source_dir, output_path, extract_with_llm (optional)
Output: artifact path, files scanned, claims extracted, artifact size
```

Call once per repo. Expensive — scans all files, extracts claims, builds embeddings.

### arc_load

Query an archive with a natural language question. Returns typed claims with evidence.

```
Input:  arc_path, task (question), claim_type (optional), source (optional), full (optional)
Output: list of claims, each with: text, type, source, confidence, source_file, line_span
```

This is the primary tool. Ask a question, get structured answers pointing to exact code locations.

### arc_snapshot

Package your findings as a .arc artifact for handoff.

```
Input:  output_path, claims (list of {text, claim_type, confidence}), source (your agent ID)
Output: artifact path, claims packaged
```

Another agent can load this with arc_load.

### arc_merge

Combine two artifacts from parallel agents.

```
Input:  arc_a, arc_b, output_path
Output: merged artifact path, claims merged, conflicts detected, conflict details
```

Observations coexist. Conflicting decisions are flagged.

### arc_verify

Check integrity before trusting an artifact.

```
Input:  arc_path
Output: valid (bool), errors, failed digests count, missing blobs count
```

### arc_diff

Compare two archive versions.

```
Input:  arc_a, arc_b
Output: new/removed claims, new/removed decisions, blob reuse ratio
```

### arc_inspect

Quick overview of an archive.

```
Input:  arc_path
Output: archive ID, version, layers, layer count
```

## Example: two-agent handoff

```
Agent A: "Build an ARC archive for this repo"
→ calls arc_build(source_dir=".", output_path="project.arc")

Agent A: "How does authentication work?"
→ calls arc_load(arc_path="project.arc", task="how does authentication work")
→ gets claims with evidence

Agent A: "Save my findings"
→ calls arc_snapshot(output_path="review.arc", source="agent-a", claims=[
    {text: "auth uses JWT with RS256", claim_type: "observation"},
    {text: "should add token refresh", claim_type: "decision"},
  ])

Agent B: "Load the review and suggest improvements"
→ calls arc_load(arc_path="review.arc", task="what decisions were made")
→ sees agent-a's decisions

Agent B: "Save my suggestions"
→ calls arc_snapshot(output_path="fixes.arc", source="agent-b", claims=[...])

Merge:
→ calls arc_merge(arc_a="review.arc", arc_b="fixes.arc", output_path="combined.arc")
→ conflicts flagged if agents disagree
```

No CLI commands. No file parsing. Pure tool calls.
