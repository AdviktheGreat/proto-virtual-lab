"""Live Proto registry discovery normalized into application contracts."""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from functools import cache
from typing import Any

from proto_virtual_lab.models import (
    CapabilityCatalog,
    ComponentType,
    ComputeClass,
    ProtoComponentCandidate,
    ToolDependency,
)
from proto_virtual_lab.proto_revisions import require_pinned_proto

_ASSET_TOKENS = {
    "checkpoint",
    "database",
    "db",
    "directory",
    "fasta",
    "file",
    "hmm",
    "model",
    "path",
    "repository",
    "structure",
    "weights",
}


class ProtoComponentNotFoundError(LookupError):
    """Raised when a requested key is absent from the live Proto registry."""


class CapabilityIntrospector:
    """Read current Proto registries and normalize their authoritative metadata."""

    def __init__(self) -> None:
        self._catalog: CapabilityCatalog | None = None
        self._catalog_lock = threading.Lock()

    def discover(self) -> CapabilityCatalog:
        """Return the live catalog, normalized once for this application lifecycle."""

        with self._catalog_lock:
            if self._catalog is None:
                manifest = require_pinned_proto()
                registries = self._registries()
                components = [
                    self._normalize(kind, spec, registry, manifest.proto_language_commit)
                    for kind, registry in registries.items()
                    for spec in registry.list_all()
                ]
                components.sort(key=lambda component: (component.component_type.value, component.registry_key))
                counts = {
                    kind: sum(component.component_type is kind for component in components) for kind in ComponentType
                }
                self._catalog = CapabilityCatalog(
                    generated_at=datetime.now(UTC),
                    manifest=manifest,
                    components=components,
                    counts=counts,
                )
            return self._catalog

    def get(self, component_type: ComponentType, registry_key: str) -> ProtoComponentCandidate:
        """Resolve an exact key from its live registry and return normalized metadata."""

        registry = self._registries()[component_type]
        try:
            spec = registry.get(registry_key)
        except ValueError as error:
            raise ProtoComponentNotFoundError(f"unknown Proto {component_type.value} {registry_key!r}") from error
        manifest = require_pinned_proto()
        return self._normalize(
            component_type,
            spec,
            registry,
            manifest.proto_language_commit,
        )

    @staticmethod
    def _registries() -> dict[ComponentType, Any]:
        from proto_language.constraint import ConstraintRegistry
        from proto_language.generator import GeneratorRegistry
        from proto_language.optimizer import OptimizerRegistry

        return {
            ComponentType.CONSTRAINT: ConstraintRegistry,
            ComponentType.GENERATOR: GeneratorRegistry,
            ComponentType.OPTIMIZER: OptimizerRegistry,
        }

    def _normalize(
        self,
        component_type: ComponentType,
        spec: Any,
        registry: Any,
        proto_language_commit: str,
    ) -> ProtoComponentCandidate:
        config_schema = registry.get_schema(spec.key)
        tools_called = list(getattr(spec, "tools_called", []) or [])
        tool_dependencies, missing_tools = self._tool_dependencies(tools_called)
        uses_gpu = bool(spec.uses_gpu or any(tool.uses_gpu for tool in tool_dependencies))
        required_assets = self._required_assets(config_schema)
        limitations = self._limitations(tool_dependencies, missing_tools)
        return ProtoComponentCandidate(
            registry_key=spec.key,
            component_type=component_type,
            label=spec.label,
            description=spec.description,
            category=getattr(spec, "category", None),
            source_module=self._source_module(component_type, spec),
            version_or_commit=proto_language_commit,
            config_schema=config_schema,
            required_inputs=self._required_inputs(component_type, spec, config_schema),
            required_assets=required_assets,
            outputs=self._outputs(component_type, tool_dependencies),
            examples=self._examples(component_type, spec.key),
            compute_class=self._compute_class(component_type, uses_gpu, tools_called),
            gradient_capable=self._gradient_capable(component_type, spec),
            uses_gpu=uses_gpu,
            tools_called=tools_called,
            tool_dependencies=tool_dependencies,
            credential_requirements=self._credential_requirements(tool_dependencies),
            mapped_requirement_ids=[],
            rationale="Live-discovered from the pinned Proto registry.",
            evidence_record_ids=[],
            limitations=limitations,
        )

    @staticmethod
    def _source_module(component_type: ComponentType, spec: Any) -> str:
        if component_type is ComponentType.CONSTRAINT:
            implementation = spec.function or spec.backward
        elif component_type is ComponentType.GENERATOR:
            implementation = spec.generator_class
        else:
            implementation = spec.optimizer_class
        return str(implementation.__module__)

    @staticmethod
    def _required_inputs(component_type: ComponentType, spec: Any, schema: dict[str, Any]) -> list[str]:
        config_fields = [f"config:{field}" for field in schema.get("required", [])]
        if component_type is ComponentType.CONSTRAINT:
            labels = getattr(spec, "input_labels", None)
            component_inputs = (
                ["segment:any"] if labels is None else [f"segment:{getattr(label, 'label', label)}" for label in labels]
            )
        elif component_type is ComponentType.GENERATOR:
            component_inputs = [f"input:{spec.input_type.value}"]
        else:
            component_inputs = ["constructs", "generators", "constraints"]
        return component_inputs + config_fields

    @staticmethod
    def _required_assets(schema: dict[str, Any]) -> list[str]:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        assets = []
        for field, details in properties.items():
            tokens = set(re.findall(r"[a-z0-9]+", field.lower()))
            schema_types = {details.get("type")}
            schema_types.update(option.get("type") for option in details.get("anyOf", []))
            if field in required and "string" in schema_types and tokens & _ASSET_TOKENS:
                assets.append(field)
        return assets

    @staticmethod
    def _outputs(component_type: ComponentType, tools: list[ToolDependency]) -> list[str]:
        if component_type is ComponentType.CONSTRAINT:
            generic = ["score", "energy", "metadata"]
        elif component_type is ComponentType.GENERATOR:
            generic = ["sequences"]
        else:
            generic = ["ranked_candidates", "energy_scores", "optimization_history"]
        return list(dict.fromkeys(generic + [metric for tool in tools for metric in tool.output_metrics]))

    @staticmethod
    def _examples(component_type: ComponentType, key: str) -> list[str]:
        return [
            f"proto-language registry: {component_type.value}/{key}",
            f"configuration schema available from {component_type.value}/{key}",
        ]

    @staticmethod
    def _compute_class(
        component_type: ComponentType,
        uses_gpu: bool,
        tools_called: list[str],
    ) -> ComputeClass:
        if uses_gpu:
            return ComputeClass.EXPENSIVE
        if tools_called:
            return ComputeClass.MODERATE
        if component_type is ComponentType.CONSTRAINT:
            return ComputeClass.DETERMINISTIC
        return ComputeClass.CHEAP

    @staticmethod
    def _gradient_capable(component_type: ComponentType, spec: Any) -> bool:
        if component_type is ComponentType.CONSTRAINT:
            return bool(spec.mode in {"gradient", "dual"})
        if component_type is ComponentType.GENERATOR:
            return bool(spec.category == "gradient")
        return bool(spec.required_constraint_mode == "gradient")

    @staticmethod
    def _tool_dependencies(keys: list[str]) -> tuple[list[ToolDependency], list[str]]:
        dependencies = []
        missing = []
        for key in keys:
            dependency = CapabilityIntrospector._tool_dependency(key)
            if dependency is None:
                missing.append(key)
            else:
                dependencies.append(dependency)
        return dependencies, missing

    @staticmethod
    @cache
    def _tool_dependency(key: str) -> ToolDependency | None:
        from proto_tools.tools import ToolRegistry

        try:
            spec = ToolRegistry.get(key)
        except ValueError:
            return None
        metric_spec = spec.metrics_model.metric_spec if spec.metrics_model is not None else {}
        primary_metric = (
            spec.metrics_model.model_fields["primary_metric"].default if spec.metrics_model is not None else None
        )
        return ToolDependency(
            key=key,
            category=spec.category,
            uses_gpu=spec.uses_gpu,
            gpu_only=spec.gpu_only,
            device_count=spec.device_count,
            local_only_reason=spec.local_only,
            weights_access=ToolRegistry.get_weights_access(key),
            output_metrics=sorted(metric_spec),
            primary_metric=primary_metric if isinstance(primary_metric, str) else None,
            license=ToolRegistry.get_license(key),
            has_example_input=spec.example_input is not None,
        )

    @staticmethod
    def _credential_requirements(tools: list[ToolDependency]) -> list[str]:
        return [f"{tool.key}:{tool.weights_access}" for tool in tools if tool.weights_access != "open"]

    @staticmethod
    def _limitations(tools: list[ToolDependency], missing_tools: list[str]) -> list[str]:
        limitations = [f"Proto tool metadata unavailable for {key}." for key in missing_tools]
        limitations.extend(
            f"{tool.key} is local-only: {tool.local_only_reason}"
            for tool in tools
            if tool.local_only_reason is not None
        )
        limitations.extend(
            f"{tool.key} has restricted commercial use."
            for tool in tools
            if tool.license is not None and tool.license.get("commercial_use") == "restricted"
        )
        return limitations


__all__ = ["CapabilityIntrospector", "ProtoComponentNotFoundError"]
