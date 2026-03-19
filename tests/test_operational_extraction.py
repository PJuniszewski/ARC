"""Tests for operational extraction — tools, policies, workflows from agent configs."""

from pathlib import Path

import pytest

from arc.builder import build_archive
from arc.extractor import extract_policies, extract_tools, extract_workflow
from arc.loader import load
from arc.models import Resource, TextUnit, _generate_id

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CREWAI_DIR = FIXTURES_DIR / "crewai"
AIDER_DIR = FIXTURES_DIR / "aider"


def _make_resources(source_dir: Path) -> list[Resource]:
    """Build Resource objects for a fixture directory."""
    resources = []
    for fpath in sorted(source_dir.rglob("*")):
        if not fpath.is_file():
            continue
        locator = str(fpath.relative_to(source_dir))
        resources.append(Resource(
            id=_generate_id(f"resource:{locator}"),
            kind="file",
            locator=locator,
            metadata={"extension": fpath.suffix},
        ))
    return resources


def _make_text_units(source_dir: Path, resources: list[Resource]) -> list[TextUnit]:
    """Build TextUnit objects from resources."""
    units = []
    for r in resources:
        fpath = source_dir / r.locator
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            units.append(TextUnit(
                resource_id=r.id,
                kind="section",
                content=content,
                span=(1, content.count("\n") + 1),
            ))
    return units


class TestToolExtraction:
    def test_crewai_tools_extracted(self):
        """CrewAI agents.yaml yields tool declarations."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        tools = extract_tools(text_units, resources, CREWAI_DIR)

        tool_names = {t.name for t in tools}
        assert "web_search" in tool_names
        assert "document_reader" in tool_names
        assert "text_editor" in tool_names

    def test_tools_are_deduplicated(self):
        """Same tool used by multiple agents appears only once."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        tools = extract_tools(text_units, resources, CREWAI_DIR)

        names = [t.name for t in tools]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_tool_has_source_ref(self):
        """Extracted tools reference their source resource."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        tools = extract_tools(text_units, resources, CREWAI_DIR)

        for tool in tools:
            assert tool.source_ref, f"Tool {tool.name} missing source_ref"


class TestPolicyExtraction:
    def test_crewai_conventions_extracted(self):
        """README Conventions section yields policy rules."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        policies = extract_policies(text_units, resources, CREWAI_DIR)

        assert len(policies) > 0
        descriptions = [p.description for p in policies]
        # Check known conventions from README
        assert any("cite sources" in d.lower() for d in descriptions), \
            f"Expected 'cite sources' policy, got: {descriptions}"

    def test_aider_security_conventions(self):
        """Aider CONVENTIONS.md security section yields policies."""
        resources = _make_resources(AIDER_DIR)
        text_units = _make_text_units(AIDER_DIR, resources)
        policies = extract_policies(text_units, resources, AIDER_DIR)

        assert len(policies) > 0
        descriptions = [p.description.lower() for p in policies]
        assert any("secret" in d or "credential" in d for d in descriptions), \
            f"Expected security-related policy, got: {descriptions}"

    def test_policy_effects_are_valid(self):
        """All extracted policies have valid effects."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        policies = extract_policies(text_units, resources, CREWAI_DIR)

        for policy in policies:
            assert policy.effect in {"allow", "deny", "require_approval"}, \
                f"Invalid effect {policy.effect} on policy: {policy.description}"


class TestWorkflowExtraction:
    def test_crewai_agents_as_workflow(self):
        """Agent definitions produce workflow steps with kind='agent'."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        steps = extract_workflow(text_units, resources, CREWAI_DIR)

        agent_steps = [s for s in steps if s.kind == "agent"]
        agent_names = {s.name for s in agent_steps}
        assert "researcher" in agent_names
        assert "writer" in agent_names
        assert "reviewer" in agent_names

    def test_crewai_tasks_as_workflow(self):
        """Task definitions produce workflow steps with kind='task'."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        steps = extract_workflow(text_units, resources, CREWAI_DIR)

        task_steps = [s for s in steps if s.kind == "task"]
        task_names = {s.name for s in task_steps}
        assert "research_task" in task_names
        assert "writing_task" in task_names
        assert "review_task" in task_names

    def test_task_dependencies(self):
        """Tasks preserve depends_on chains."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        steps = extract_workflow(text_units, resources, CREWAI_DIR)

        by_name = {s.name: s for s in steps}
        assert by_name["writing_task"].depends_on == ["research_task"]
        assert by_name["review_task"].depends_on == ["writing_task"]

    def test_task_agent_refs(self):
        """Tasks reference their assigned agents."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        steps = extract_workflow(text_units, resources, CREWAI_DIR)

        by_name = {s.name: s for s in steps}
        assert by_name["research_task"].agent_ref == "researcher"
        assert by_name["writing_task"].agent_ref == "writer"
        assert by_name["review_task"].agent_ref == "reviewer"

    def test_aider_config_step(self):
        """Aider config file produces a config workflow step."""
        resources = _make_resources(AIDER_DIR)
        text_units = _make_text_units(AIDER_DIR, resources)
        steps = extract_workflow(text_units, resources, AIDER_DIR)

        config_steps = [s for s in steps if s.kind == "config"]
        assert len(config_steps) >= 1
        config = config_steps[0]
        assert "model" in config.config

    def test_agent_tools_captured(self):
        """Agent workflow steps capture tool names."""
        resources = _make_resources(CREWAI_DIR)
        text_units = _make_text_units(CREWAI_DIR, resources)
        steps = extract_workflow(text_units, resources, CREWAI_DIR)

        by_name = {s.name: s for s in steps}
        assert "web_search" in by_name["researcher"].tools
        assert "document_reader" in by_name["researcher"].tools


class TestBuilderIntegration:
    def test_crewai_build_has_operational_layers(self, tmp_path):
        """Building crewai fixture produces tools, policy, workflow layers."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid, f"Build failed: {result.errors}"

        layer_names = {l.name for l in result.manifest.layers}
        assert "tools" in layer_names
        assert "policy" in layer_names
        assert "workflow" in layer_names

    def test_crewai_build_result_fields(self, tmp_path):
        """BuildResult has populated operational fields."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        assert len(result.tools) > 0
        assert len(result.policies) > 0
        assert len(result.workflow_steps) > 0

    def test_operational_blobs_exist_in_cas(self, tmp_path):
        """All operational layer blobs exist in CAS."""
        from arc.cas import ContentAddressedStore

        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        cas = ContentAddressedStore(out)
        for layer in result.manifest.layers:
            if layer.type.startswith("operational."):
                assert cas.has_blob(layer.digest), f"Missing blob for {layer.name}"

    def test_operational_layers_are_optional(self, tmp_path):
        """Operational layers have required=False."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        for layer in result.manifest.layers:
            if layer.type.startswith("operational."):
                assert not layer.required, f"Layer {layer.name} should not be required"

    def test_corpus_build_no_operational_layers(self, corpus_dir, tmp_path):
        """Building standard corpus (no YAML agent configs) produces no operational layers."""
        out = tmp_path / "corpus.arc"
        result = build_archive(corpus_dir, out)
        assert result.valid

        layer_types = {l.type for l in result.manifest.layers}
        assert "operational.tools" not in layer_types
        assert "operational.workflow" not in layer_types


class TestLoaderIntegration:
    def test_load_crewai_archive(self, tmp_path):
        """Loading crewai archive populates operational fields."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        loaded = load(out)
        assert not loaded.rejected
        assert len(loaded.tools) > 0
        assert len(loaded.policies) > 0
        assert len(loaded.workflow) > 0

    def test_selective_load_tools_only(self, tmp_path):
        """Loading only the tools layer works."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        loaded = load(out, layers=["tools"])
        assert not loaded.rejected
        assert len(loaded.tools) > 0
        assert len(loaded.policies) == 0
        assert len(loaded.workflow) == 0

    def test_roundtrip_counts_match(self, tmp_path):
        """Build → load round-trip preserves operational counts."""
        out = tmp_path / "crewai.arc"
        result = build_archive(CREWAI_DIR, out)
        assert result.valid

        loaded = load(out)
        assert len(loaded.tools) == len(result.tools)
        assert len(loaded.policies) == len(result.policies)
        assert len(loaded.workflow) == len(result.workflow_steps)


class TestDiffIntegration:
    def test_diff_detects_tool_changes(self, tmp_path):
        """Diff detects added/removed tools between archives."""
        import shutil

        from arc.diff import diff_archives

        # Build archive A from crewai
        out_a = tmp_path / "a.arc"
        result_a = build_archive(CREWAI_DIR, out_a)
        assert result_a.valid

        # Create modified crewai with extra tool
        modified = tmp_path / "crewai_modified"
        shutil.copytree(CREWAI_DIR, modified)
        agents_yaml = modified / "agents.yaml"
        content = agents_yaml.read_text()
        content = content.replace(
            "tools:\n    - web_search\n    - document_reader",
            "tools:\n    - web_search\n    - document_reader\n    - code_executor",
        )
        agents_yaml.write_text(content)

        out_b = tmp_path / "b.arc"
        result_b = build_archive(modified, out_b)
        assert result_b.valid

        diff = diff_archives(out_a, out_b)
        new_tool_names = {t.name for t in diff.new_tools}
        assert "code_executor" in new_tool_names
