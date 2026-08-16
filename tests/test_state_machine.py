import pytest

from proto_virtual_lab.models import CampaignState
from proto_virtual_lab.state_machine import InvalidStateTransitionError, ensure_transition_allowed


def test_expected_transition_is_allowed() -> None:
    ensure_transition_allowed(CampaignState.CREATED, CampaignState.SPEC_DRAFTING)


@pytest.mark.parametrize("terminal_state", [CampaignState.COMPLETED, CampaignState.CANCELLED])
def test_terminal_states_cannot_be_bypassed(terminal_state: CampaignState) -> None:
    with pytest.raises(InvalidStateTransitionError):
        ensure_transition_allowed(terminal_state, CampaignState.SPEC_DRAFTING)


def test_approval_state_cannot_be_skipped() -> None:
    with pytest.raises(InvalidStateTransitionError):
        ensure_transition_allowed(CampaignState.SPEC_DRAFTING, CampaignState.EVIDENCE_RETRIEVAL)


def test_active_run_can_be_cancelled() -> None:
    ensure_transition_allowed(CampaignState.RUNNING, CampaignState.CANCELLED)
