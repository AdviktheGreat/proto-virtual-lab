# Seeded campaign

The canonical, strictly validated promoter-repressor `DesignSpec` is packaged at:

`src/proto_virtual_lab/seeds/promoter_repressor_design_spec.json`

Create a campaign from it with `POST /campaigns/seeded`. The workflow persists a campaign-specific
copy and stops at `SPEC_AWAITING_APPROVAL`.
