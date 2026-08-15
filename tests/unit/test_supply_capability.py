"""Classifying what the platform said, from literals.

:func:`~tools.quality.supply.capability.probe` starts ``gh`` and reaches the
network, so it is never called here — ADR-0024 makes the suite offline. What is
tested is :func:`~tools.quality.supply.capability.classify`, which carries every
decision, and :func:`~tools.quality.supply.capability.judge`, which turns states
into policy failures.

The bodies below are the responses actually observed against this repository on
2026-08-15, recorded in ``docs/research/phase_014_sources.md``. Using the real
prose matters: GitHub distinguishes a plan ceiling from a missing scope in the
message text and not in the status code, so a test written against invented
wording would prove nothing about the strings that will really arrive.
"""

import json

import pytest

from tools.quality.supply import capability
from tools.quality.supply.capability import State

PLAN_403 = json.dumps(
    {"message": "Upgrade to GitHub Pro or make this repository public to enable this feature."}
)
SCOPE_403 = json.dumps({"message": 'This API operation needs the "admin:repo_hook" scope.'})
DISABLED_404 = json.dumps({"message": "Secret scanning is disabled on this repository."})
NO_ANALYSIS_404 = json.dumps({"message": "no analysis found"})

RULESETS = next(control for control in capability.CONTROLS if control.name == "rulesets")
SECRET_SCANNING = next(
    control for control in capability.CONTROLS if control.name == "secret_scanning"
)
NON_PROVIDER = next(
    control
    for control in capability.CONTROLS
    if control.name == "secret_scanning_non_provider_patterns"
)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        pytest.param(403, PLAN_403, State.UNAVAILABLE_BY_PLAN, id="plan ceiling"),
        pytest.param(403, SCOPE_403, State.UNAVAILABLE_BY_PERMISSION, id="missing scope"),
        pytest.param(404, DISABLED_404, State.FAIL, id="switched off"),
        pytest.param(404, NO_ANALYSIS_404, State.FAIL, id="nothing analysed yet"),
        pytest.param(204, "", State.PASS, id="no content is an answer"),
        pytest.param(200, "[]", State.PASS, id="readable"),
        pytest.param(500, '{"message":"boom"}', State.ERROR, id="server error"),
        pytest.param(0, "", State.ERROR, id="no status"),
    ],
)
def test_each_response_shape_maps_to_its_own_state(status: int, body: str, expected: State) -> None:
    """Two ``403``s with opposite remedies must not collapse into one state.

    One names a plan and no commit changes it; the other names a scope and one
    ``gh auth refresh`` fixes it. Reporting both as "unavailable" would send
    somebody to buy a subscription they did not need.
    """
    state, reason = capability.classify(RULESETS, status=status, body=body)
    assert state is expected
    assert reason, "every state carries the evidence that established it"


def test_an_unrecognised_404_is_a_failure_rather_than_an_absence() -> None:
    """``404`` means both "off" and "no such thing".

    Assuming absence would let a control that is merely switched off pass as one
    nobody could have had.
    """
    state, _ = capability.classify(RULESETS, status=404, body='{"message":"Not Found"}')
    assert state is State.FAIL


def test_a_setting_read_from_a_json_path_is_compared_to_its_expected_value() -> None:
    """Some controls answer with a document rather than with a status."""
    body = json.dumps({"security_and_analysis": {"secret_scanning": {"status": "enabled"}}})
    state, reason = capability.classify(SECRET_SCANNING, status=200, body=body)
    assert state is State.PASS
    assert "enabled" in reason

    off = json.dumps({"security_and_analysis": {"secret_scanning": {"status": "disabled"}}})
    assert capability.classify(SECRET_SCANNING, status=200, body=off)[0] is State.FAIL


def test_a_control_known_to_be_unenableable_is_not_reported_as_a_failure() -> None:
    """The API accepts the change, returns 200, and does not apply it.

    Nothing in the response says so, so no classification rule could detect it.
    The fact was established by hand and is recorded on the control itself —
    otherwise the manifest would carry a permanent ``FAIL`` nobody can fix, which
    trains people to ignore the manifest.
    """
    body = json.dumps(
        {"security_and_analysis": {"secret_scanning_non_provider_patterns": {"status": "disabled"}}}
    )
    state, reason = capability.classify(NON_PROVIDER, status=200, body=body)
    assert state is State.UNAVAILABLE_BY_PLAN
    assert "Secret Protection" in reason


def test_a_body_that_is_not_json_is_an_error_rather_than_a_verdict() -> None:
    """Guessing between "enabled" and "disabled" with no evidence is not an option."""
    state, _ = capability.classify(SECRET_SCANNING, status=200, body="<html>")
    assert state is State.ERROR


def test_a_missing_key_is_an_error_rather_than_a_failure() -> None:
    """A response whose shape changed is not a repository with a setting switched off."""
    state, _ = capability.classify(SECRET_SCANNING, status=200, body="{}")
    assert state is State.ERROR


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_only_a_required_control_being_off_is_a_policy_failure() -> None:
    """An unavailable control is nobody's to fix from a commit.

    A gate that failed for something no commit can change is a gate people learn
    to ignore.
    """
    assert capability.judge({"rulesets": (State.FAIL, "off")})
    assert not capability.judge({"rulesets": (State.UNAVAILABLE_BY_PLAN, "plan")})
    assert not capability.judge({"rulesets": (State.NOT_PROBED, "no network")})
    assert not capability.judge({"code_scanning": (State.FAIL, "no analysis found")})


@pytest.mark.parametrize("state", [State.UNAVAILABLE_BY_PLAN, State.UNAVAILABLE_BY_PERMISSION])
def test_unavailable_is_never_masked_as_a_pass(state: State) -> None:
    """The distinction the whole module exists to preserve.

    ``UNAVAILABLE`` is a different fact from ``PASS`` and from ``FAIL``, and the
    enum keeps them apart by construction — there is no value that means both.
    """
    assert state is not State.PASS
    assert not capability.judge({"rulesets": (state, "recorded")})


def test_not_probed_is_not_a_pass() -> None:
    """A manifest missing an answer says so rather than leaving one to be inferred."""
    states = {control.name: (State.NOT_PROBED, "offline") for control in capability.CONTROLS}
    assert not capability.judge(states), "unprobed is not a failure either"
    assert all(state is not State.PASS for state, _ in states.values())


def test_every_control_declares_a_policy() -> None:
    """A control with no policy would be recorded and never judged, silently."""
    for control in capability.CONTROLS:
        assert control.policy in {capability.REQUIRED, capability.RECORDED}
        assert control.name


def test_a_control_with_a_recorded_unavailability_states_its_evidence() -> None:
    """An exception with no argument is an exception nobody can review."""
    for control in capability.CONTROLS:
        if control.unavailable_reason:
            assert "20" in control.unavailable_reason, "the observation carries its date"
            assert len(control.unavailable_reason) > 80
