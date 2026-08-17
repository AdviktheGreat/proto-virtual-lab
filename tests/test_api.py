from fastapi.testclient import TestClient

from proto_virtual_lab.seed import load_seeded_design_spec


def test_seeded_campaign_reaches_approval_gate(client: TestClient) -> None:
    response = client.post("/campaigns/seeded", headers={"X-Actor": "scientist@example.test"})

    assert response.status_code == 201
    body = response.json()
    assert body["campaign"]["state"] == "SPEC_AWAITING_APPROVAL"
    assert body["design_spec"]["status"] == "draft"
    assert body["design_spec"]["campaign_id"] == body["campaign"]["id"]
    assert [event["next_state"] for event in body["state_transitions"]] == [
        "CREATED",
        "SPEC_DRAFTING",
        "SPEC_AWAITING_APPROVAL",
    ]


def test_seeded_campaign_can_be_approved_and_reloaded(client: TestClient) -> None:
    created = client.post("/campaigns/seeded").json()
    campaign_id = created["campaign"]["id"]

    approval = client.post(
        f"/campaigns/{campaign_id}/spec/approve",
        headers={"X-Actor": "human:reviewer"},
    )
    reloaded = client.get(f"/campaigns/{campaign_id}")

    assert approval.status_code == 200
    assert approval.json()["campaign"]["state"] == "EVIDENCE_RETRIEVAL"
    assert approval.json()["design_spec"]["status"] == "approved"
    assert reloaded.json() == approval.json()


def test_missing_campaign_returns_typed_error(client: TestClient) -> None:
    response = client.get("/campaigns/campaign_missing")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_workflow_bypass_returns_conflict(client: TestClient) -> None:
    created = client.post(
        "/campaigns",
        json={"title": "New campaign", "user_goal": "Design a benign regulatory sequence."},
    ).json()

    response = client.post(f"/campaigns/{created['campaign']['id']}/spec/approve")

    assert response.status_code == 409
    assert response.json()["error"] == "campaign_conflict"


def test_invalid_campaign_payload_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/campaigns",
        json={"title": "", "user_goal": "Goal", "unexpected": True},
    )

    assert response.status_code == 422


def test_design_spec_accepts_its_json_representation(client: TestClient) -> None:
    created = client.post(
        "/campaigns",
        json={"title": "New campaign", "user_goal": "Design a benign regulatory sequence."},
    ).json()
    campaign_id = created["campaign"]["id"]
    client.post(f"/campaigns/{campaign_id}/spec/start")
    design_spec = load_seeded_design_spec(campaign_id, "design_spec_transport_test")

    response = client.put(
        f"/campaigns/{campaign_id}/spec",
        json=design_spec.model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["design_spec"]["id"] == "design_spec_transport_test"


def test_campaign_listing_is_paginated(client: TestClient) -> None:
    for number in range(3):
        client.post(
            "/campaigns",
            json={"title": f"Campaign {number}", "user_goal": "Design a benign regulatory sequence."},
        )

    first_page = client.get("/campaigns", params={"limit": 2, "offset": 0})
    second_page = client.get("/campaigns", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert len(first_page.json()) == 2
    assert len(second_page.json()) == 1


def test_proto_capabilities_and_manifest_are_exposed(client: TestClient) -> None:
    manifest = client.get("/proto/manifest")
    catalog = client.get("/proto/capabilities")
    capability = client.get("/proto/capabilities/constraint/gc-content")
    missing = client.get("/proto/capabilities/generator/not-a-real-generator")

    assert manifest.status_code == 200
    assert manifest.json()["revisions_verified"] is True
    assert manifest.json()["lock_verified"] is True
    assert catalog.status_code == 200
    assert catalog.json()["counts"] == {"constraint": 81, "generator": 16, "optimizer": 6}
    assert capability.status_code == 200
    assert capability.json()["config_schema"]["required"] == ["min_gc", "max_gc"]
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"


def test_proto_smoke_can_execute_and_replay_through_api(client: TestClient) -> None:
    executed = client.post(
        "/proto/smoke",
        json={"sequence_length": 18, "num_samples": 2, "num_results": 1, "seed": 7, "timeout_seconds": 60},
    )

    assert executed.status_code == 201
    assert executed.json()["status"] == "succeeded"
    assert len(executed.json()["sequences"]) == 1
    replayed = client.get(f"/proto/smoke/{executed.json()['id']}")
    assert replayed.status_code == 200
    assert replayed.json() == executed.json()
