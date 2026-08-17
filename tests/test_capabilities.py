from __future__ import annotations

import pytest

from proto_virtual_lab.capabilities import CapabilityIntrospector, ProtoComponentNotFoundError
from proto_virtual_lab.models import ComponentType, ComputeClass, ProtoInputSlot, SequenceType


def test_live_catalog_is_complete_normalized_and_serializable() -> None:
    introspector = CapabilityIntrospector()
    catalog = introspector.discover()

    assert catalog.counts == {
        ComponentType.CONSTRAINT: 81,
        ComponentType.GENERATOR: 16,
        ComponentType.OPTIMIZER: 6,
    }
    assert len(catalog.components) == 103
    assert catalog.manifest.revisions_verified is True
    assert len(catalog.model_dump_json()) > 1_000
    assert introspector.discover() is catalog

    gc_content = next(item for item in catalog.components if item.registry_key == "gc-content")
    assert gc_content.component_type is ComponentType.CONSTRAINT
    assert gc_content.compute_class is ComputeClass.DETERMINISTIC
    assert gc_content.source_module == "proto_language.constraint.sequence_composition.gc_content_constraint"
    assert gc_content.config_schema["additionalProperties"] is False
    assert gc_content.config_schema["required"] == ["min_gc", "max_gc"]
    assert gc_content.supported_sequence_types == [SequenceType.DNA, SequenceType.RNA]
    assert gc_content.constraint_mode == "discrete"

    protein_domain = next(item for item in catalog.components if item.registry_key == "protein-domain")
    assert protein_domain.required_assets == ["hmm_db"]
    assert {tool.key for tool in protein_domain.tool_dependencies} == {
        "prodigal-prediction",
        "pyhmmer-hmmscan",
    }

    af3_interface = next(item for item in catalog.components if item.registry_key == "af3-chain-pair-prot-dna-iptm")
    assert "alphafold3-prediction:request" in af3_interface.credential_requirements
    assert {tool.key for tool in af3_interface.tool_dependencies} == {
        "alphafold3-prediction",
        "boltz2-prediction",
        "protenix-prediction",
    }

    inline_reference = next(item for item in catalog.components if item.registry_key == "dinucleotide-composition")
    assert inline_reference.required_assets == []

    pyrosetta = next(item for item in catalog.components if item.registry_key == "pyrosetta-interface")
    assert pyrosetta.input_slots == [
        ProtoInputSlot(
            label="Complex Carrier",
            requires_logits=False,
            requires_structure=True,
        )
    ]

    structure_plddt = next(item for item in catalog.components if item.registry_key == "structure-plddt")
    assert structure_plddt.outputs == [
        "score",
        "metadata",
        "structures",
        "logits",
        "metadata_recipient",
    ]
    assert any(">>> from proto_language.core import Segment" in example for example in structure_plddt.examples)

    puffin = next(item for item in catalog.components if item.registry_key == "puffin-promoter-activity")
    assert "puffin-prediction prohibits commercial use." in puffin.limitations


def test_exact_capability_lookup_and_invalid_key_rejection() -> None:
    introspector = CapabilityIntrospector()

    optimizer = introspector.get(ComponentType.OPTIMIZER, "rejection-sampling")
    assert optimizer.component_type is ComponentType.OPTIMIZER
    assert optimizer.required_inputs == [
        "constructs",
        "generators",
        "constraints",
        "config:num_samples",
    ]

    gradient = introspector.get(ComponentType.OPTIMIZER, "gradient")
    assert gradient.compatible_generators == ["position-weight"]
    assert gradient.required_constraint_mode == "gradient"
    assert gradient.targets_single_segment is True

    generator = introspector.get(ComponentType.GENERATOR, "random-nucleotide")
    assert generator.input_type == "starting_sequence"
    assert generator.allows_empty_starting_sequence is True
    assert generator.supported_sequence_types == [SequenceType.DNA, SequenceType.RNA]

    with pytest.raises(ProtoComponentNotFoundError, match="unknown Proto generator"):
        introspector.get(ComponentType.GENERATOR, "not-a-real-generator")
