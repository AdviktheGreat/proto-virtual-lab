"""Loader for the reviewable seeded promoter-repressor campaign."""

from __future__ import annotations

import json
from importlib.resources import files

from proto_virtual_lab.models import DesignSpec

SEED_RESOURCE = files("proto_virtual_lab").joinpath("seeds/promoter_repressor_design_spec.json")


def load_seeded_design_spec(campaign_id: str, design_spec_id: str) -> DesignSpec:
    """Load, retarget, and strictly validate the seeded DesignSpec."""

    data = json.loads(SEED_RESOURCE.read_text(encoding="utf-8"))
    data["campaign_id"] = campaign_id
    data["id"] = design_spec_id
    return DesignSpec.model_validate_json(json.dumps(data))
