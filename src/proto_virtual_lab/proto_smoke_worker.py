"""Trusted subprocess entry point for the minimal authentic Proto campaign."""

from __future__ import annotations

import argparse
from pathlib import Path

from proto_virtual_lab.artifacts import write_json
from proto_virtual_lab.models import ProtoSmokeRequest, ProtoSmokeWorkerResult


def run_smoke_program(request: ProtoSmokeRequest, output_directory: Path) -> ProtoSmokeWorkerResult:
    """Run a bounded CPU-only Proto program and export its authentic results."""

    from proto_language.constraint import ConstraintRegistry
    from proto_language.core import Construct, Program, Segment
    from proto_language.generator import GeneratorRegistry
    from proto_language.optimizer import OptimizerRegistry

    segment = Segment(length=request.sequence_length, sequence_type="dna", label="smoke_dna")
    construct = Construct([segment])
    generator = GeneratorRegistry.create("random-nucleotide", {})
    generator.assign(segment)
    constraints = [
        ConstraintRegistry.create(
            "gc-content",
            [segment],
            {"min_gc": 35.0, "max_gc": 65.0},
            label="gc_content",
        ),
        ConstraintRegistry.create(
            "max-homopolymer",
            [segment],
            {"max_length": 4},
            label="max_homopolymer",
        ),
    ]
    optimizer_spec = OptimizerRegistry.get("rejection-sampling")
    optimizer = optimizer_spec.optimizer_class(  # type: ignore[call-arg]
        constructs=[construct],
        generators=[generator],
        constraints=constraints,
        config=optimizer_spec.config_model(
            num_samples=request.num_samples,
            num_results=request.num_results,
        ),
    )
    program = Program(
        optimizers=[optimizer],
        num_results=request.num_results,
        seed=request.seed,
    )
    program.run()
    program.export(output_directory, format="json")
    return ProtoSmokeWorkerResult(
        sequences=[sequence.sequence for sequence in segment.result_sequences],
        energy_scores=[float(score) for score in program.energy_scores],
    )


def main() -> None:
    """Validate worker inputs, run the program, and write a machine-readable result."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    request = ProtoSmokeRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    result = run_smoke_program(request, args.output_directory)
    write_json(args.result, result.model_dump(mode="json"))


if __name__ == "__main__":
    main()
