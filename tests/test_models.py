"""Unit tests for ARC data models — serialization, validation, round-trips."""

import json

import pytest

from arc.models import (
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


class TestEvidencePointer:
    def test_to_dict_and_back(self):
        ep = EvidencePointer(source_unit_id="su-1", span=(10, 20), weight=0.9)
        d = ep.to_dict()
        restored = EvidencePointer.from_dict(d)
        assert restored.source_unit_id == "su-1"
        assert restored.span == (10, 20)
        assert restored.weight == 0.9

    def test_no_span(self):
        ep = EvidencePointer(source_unit_id="su-2")
        d = ep.to_dict()
        assert "span" not in d
        restored = EvidencePointer.from_dict(d)
        assert restored.span is None


class TestResource:
    def test_round_trip(self):
        r = Resource(id="r1", kind="file", locator="src/main.py", content_digest="abc123", metadata={"size": 100})
        d = r.to_dict()
        restored = Resource.from_dict(d)
        assert restored.id == "r1"
        assert restored.locator == "src/main.py"
        assert restored.metadata["size"] == 100


class TestTextUnit:
    def test_auto_digest(self):
        tu = TextUnit(id="tu1", resource_id="r1", content="Hello world")
        assert tu.content_digest != ""

    def test_round_trip(self):
        tu = TextUnit(id="tu1", resource_id="r1", kind="section", content="Test content", span=(1, 5))
        d = tu.to_dict()
        restored = TextUnit.from_dict(d)
        # ID is deterministic based on content+resource, so it changes from "tu1"
        assert restored.id == tu.id
        assert restored.span == (1, 5)
        assert restored.content == "Test content"


class TestClaim:
    def test_valid_statuses(self):
        for status in ["observed", "derived", "verified", "deprecated", "contested"]:
            c = Claim(text="test", status=status)
            assert c.status == status

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid claim status"):
            Claim(text="test", status="invalid")

    def test_round_trip_with_evidence(self):
        c = Claim(
            id="c1",
            text="ARC uses SHA-256",
            kind="fact",
            evidence=[EvidencePointer(source_unit_id="su-1", span=(1, 3))],
            confidence=0.95,
            status="verified",
        )
        d = c.to_dict()
        restored = Claim.from_dict(d)
        assert restored.text == "ARC uses SHA-256"
        assert len(restored.evidence) == 1
        assert restored.evidence[0].source_unit_id == "su-1"
        assert restored.confidence == 0.95


class TestDecision:
    def test_valid_statuses(self):
        for status in ["proposed", "accepted", "superseded", "rejected"]:
            d = Decision(title="test", status=status)
            assert d.status == status

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid decision status"):
            Decision(title="test", status="invalid")

    def test_round_trip(self):
        d = Decision(
            id="d1",
            title="Use SHA-256",
            context="Need hash algorithm",
            options=["MD5", "SHA-256", "SHA-512"],
            decision="SHA-256",
            consequences=["Good security", "Widely supported"],
            evidence=[EvidencePointer(source_unit_id="su-1")],
            status="accepted",
        )
        serialized = d.to_dict()
        restored = Decision.from_dict(serialized)
        assert restored.title == "Use SHA-256"
        assert len(restored.options) == 3
        assert restored.decision == "SHA-256"


class TestToolDeclaration:
    def test_valid_statuses(self):
        for status in ["active", "deprecated", "experimental"]:
            t = ToolDeclaration(name="test", status=status)
            assert t.status == status

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid tool status"):
            ToolDeclaration(name="test", status="invalid")

    def test_round_trip(self):
        t = ToolDeclaration(
            name="web_search",
            description="Search the web",
            parameters=[{"name": "query", "type": "string", "required": True}],
            returns="list of results",
            constraints=["read-only"],
            source_ref="r1",
            status="active",
        )
        d = t.to_dict()
        restored = ToolDeclaration.from_dict(d)
        assert restored.name == "web_search"
        assert restored.description == "Search the web"
        assert len(restored.parameters) == 1
        assert restored.constraints == ["read-only"]

    def test_deterministic_id(self):
        t1 = ToolDeclaration(name="web_search")
        t2 = ToolDeclaration(name="web_search")
        assert t1.id == t2.id

    def test_different_names_different_ids(self):
        t1 = ToolDeclaration(name="web_search")
        t2 = ToolDeclaration(name="text_editor")
        assert t1.id != t2.id


class TestPolicyRule:
    def test_valid_effects(self):
        for effect in ["allow", "deny", "require_approval"]:
            p = PolicyRule(effect=effect)
            assert p.effect == effect

    def test_invalid_effect(self):
        with pytest.raises(ValueError, match="Invalid policy effect"):
            PolicyRule(effect="invalid")

    def test_round_trip(self):
        p = PolicyRule(
            scope="tool:web_search",
            effect="deny",
            conditions=["after-hours"],
            priority=10,
            description="Block web search after hours",
            source_ref="r1",
        )
        d = p.to_dict()
        restored = PolicyRule.from_dict(d)
        assert restored.scope == "tool:web_search"
        assert restored.effect == "deny"
        assert restored.priority == 10
        assert restored.conditions == ["after-hours"]

    def test_deterministic_id(self):
        p1 = PolicyRule(scope="*", description="no secrets")
        p2 = PolicyRule(scope="*", description="no secrets")
        assert p1.id == p2.id


class TestWorkflowStep:
    def test_round_trip(self):
        w = WorkflowStep(
            name="research_task",
            kind="task",
            description="Research the topic",
            agent_ref="researcher",
            depends_on=["init"],
            tools=["web_search"],
            config={"timeout": 300},
            expected_output="Research brief",
            source_ref="r1",
        )
        d = w.to_dict()
        restored = WorkflowStep.from_dict(d)
        assert restored.name == "research_task"
        assert restored.kind == "task"
        assert restored.agent_ref == "researcher"
        assert restored.depends_on == ["init"]
        assert restored.tools == ["web_search"]
        assert restored.config == {"timeout": 300}

    def test_deterministic_id(self):
        w1 = WorkflowStep(name="step1")
        w2 = WorkflowStep(name="step1")
        assert w1.id == w2.id

    def test_agent_kind(self):
        w = WorkflowStep(name="researcher", kind="agent", description="Senior Research Analyst")
        assert w.kind == "agent"
        d = w.to_dict()
        assert d["kind"] == "agent"


class TestLayer:
    def test_round_trip(self):
        l = Layer(name="claims", type="semantic.claims", digest="abc123", depends_on=["source-units"])
        d = l.to_dict()
        restored = Layer.from_dict(d)
        assert restored.name == "claims"
        assert restored.depends_on == ["source-units"]


class TestManifest:
    def test_round_trip_json(self):
        m = Manifest(
            archive_id="arc://test",
            archive_version="1.0.0",
            layers=[
                Layer(name="claims", type="semantic.claims", digest="abc123"),
            ],
        )
        m.root_digest = m.compute_root_digest()
        json_str = m.to_json()
        restored = Manifest.from_json(json_str)
        assert restored.archive_id == "arc://test"
        assert len(restored.layers) == 1
        assert restored.root_digest == m.root_digest

    def test_root_digest_changes_with_content(self):
        m1 = Manifest(archive_id="arc://test", archive_version="1.0.0")
        m2 = Manifest(archive_id="arc://test", archive_version="2.0.0")
        assert m1.compute_root_digest() != m2.compute_root_digest()

    def test_root_digest_deterministic(self):
        m = Manifest(archive_id="arc://test", archive_version="1.0.0")
        d1 = m.compute_root_digest()
        d2 = m.compute_root_digest()
        assert d1 == d2
