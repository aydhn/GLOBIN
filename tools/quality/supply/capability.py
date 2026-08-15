"""What the hosting platform will and will not do, recorded as a state rather than a verdict.

Half of the controls this phase is asked for are not this repository's to
implement. CodeQL, secret scanning, push protection, dependency review, artifact
attestations and rulesets are GitHub features, governed by a plan and a
visibility setting, in a control plane no file in this tree can reach. A gate
that reported them as passing because it could not check them would be worse than
one that ignored them.

**So each is a state, and ``UNAVAILABLE`` is never ``PASS``.** The distinction
this module exists to preserve is between *we checked and it is on*, *we checked
and it is off*, *this account cannot have it*, *this token may not ask*, and *the
question does not apply*. Collapsing those five into a boolean is exactly the
dishonesty the brief for this phase names.

**The classification is pure; the probing is not.** :func:`classify` maps an HTTP
status and a message to a state and is tested from literals, offline, like
everything else in this repository. :func:`probe` starts ``gh`` and is never
called by the suite — ``tests/conftest.py`` refuses outbound sockets, and a test
that needed the network would be a test that fails on an aeroplane.

**Why the message text matters.** GitHub distinguishes plan from permission in
prose, not in the status code. ``403`` with *"Upgrade to GitHub Pro or make this
repository public"* is a plan ceiling; ``403`` with *"needs the admin:repo_hook
scope"* is a token that was not asked for enough. Both were observed against this
repository on 2026-08-15, which is why both are matched here rather than guessed
at — see ``docs/research/phase_014_sources.md``.
"""

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class State(StrEnum):
    """What is known about one platform control."""

    PASS = "PASS"  # noqa: S105 - a verdict name, not a credential; bandit reads the identifier
    """Checked, and enabled."""

    FAIL = "FAIL"
    """Checked, available, and not enabled. The only state a control can be in
    that is somebody's fault."""

    UNAVAILABLE_BY_PLAN = "UNAVAILABLE_BY_PLAN"
    """The account or the repository's visibility cannot have it. Not a defect,
    and not something a commit can change."""

    UNAVAILABLE_BY_PERMISSION = "UNAVAILABLE_BY_PERMISSION"
    """The credential used may not ask. Distinct from the above because the
    remedy is a scope, not a subscription."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """The question does not arise for this repository."""

    NOT_PROBED = "NOT_PROBED"
    """Nothing asked. Recorded rather than omitted, so that a manifest missing an
    answer says so instead of leaving a reader to infer one."""

    ERROR = "ERROR"
    """The probe itself failed. Never folded into ``UNAVAILABLE``: not knowing
    why is a different fact from knowing why."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
"""How the probe asks. Injected for the reason ``audit.py`` gives: a gate that
can only be tested with a network is a gate the offline suite cannot cover."""

REQUIRED: Final[str] = "required"
"""Policy: if this control is available, it must be on. Off is a gate failure."""

RECORDED: Final[str] = "recorded"
"""Policy: report the state and do not judge it."""

#: The prose GitHub uses when a plan, rather than a permission, is the obstacle.
#: Matched as a substring because the sentence carries a repository name.
PLAN_MARKERS: Final[tuple[str, ...]] = (
    "upgrade to github pro",
    "make this repository public",
    "advanced security",
    "github code security",
    "github secret protection",
    "not available for this repository",
)

#: The prose GitHub uses when the token is the obstacle.
PERMISSION_MARKERS: Final[tuple[str, ...]] = (
    "scope",
    "must have admin",
    "resource not accessible",
)


@dataclass(frozen=True, slots=True)
class Control:
    """One platform control and how to ask about it.

    Args:
        name: How the manifest refers to it.
        endpoint: The REST path, relative to the repository.
        policy: :data:`REQUIRED` or :data:`RECORDED`.
        enabled_when: A JSON path of literal keys whose value must be truthy for
            the control to count as enabled, or ``()`` when a successful response
            is itself the answer.
        expected_value: What that key must equal. ``None`` means "anything truthy".
        unavailable_reason: What was observed when somebody tried to enable this
            and could not. Set only where the API reports success and then does
            not apply the change, which is the one case classification cannot
            detect for itself. When set, a :attr:`State.FAIL` becomes
            :attr:`State.UNAVAILABLE_BY_PLAN` carrying this text — a fact
            established once, by hand, and recorded here rather than rediscovered
            as a permanent failure nobody can fix.
    """

    name: str
    endpoint: str
    policy: str
    enabled_when: tuple[str, ...] = ()
    expected_value: str | None = None
    unavailable_reason: str = ""


CONTROLS: Final[tuple[Control, ...]] = (
    Control("dependency_graph", "dependency-graph/sbom", RECORDED),
    Control("dependabot_alerts", "vulnerability-alerts", REQUIRED),
    Control("dependabot_security_updates", "automated-security-fixes", REQUIRED, ("enabled",)),
    Control(
        "secret_scanning",
        "",
        REQUIRED,
        ("security_and_analysis", "secret_scanning", "status"),
        "enabled",
    ),
    Control(
        "secret_scanning_push_protection",
        "",
        REQUIRED,
        ("security_and_analysis", "secret_scanning_push_protection", "status"),
        "enabled",
    ),
    Control(
        "secret_scanning_non_provider_patterns",
        "",
        RECORDED,
        ("security_and_analysis", "secret_scanning_non_provider_patterns", "status"),
        "enabled",
        unavailable_reason=(
            "PATCH /repos/{owner}/{repo} accepts this field and returns 200 with the "
            "status still 'disabled'. Observed twice on 2026-08-15 against a public "
            "repository owned by a personal account; generic-pattern scanning needs "
            "GitHub Secret Protection. See docs/research/phase_014_sources.md"
        ),
    ),
    Control("code_scanning", "code-scanning/analyses", RECORDED),
    Control("rulesets", "rulesets", REQUIRED),
)
"""Every control this phase asks about.

``code_scanning`` asks for *analyses* rather than for the default-setup
configuration, because the configuration endpoint answers a different question
than the one worth asking. It returns ``200`` with ``"state": "not-configured"``
on a repository where nothing analyses anything — a body that classifies as a
pass while meaning the opposite. An analysis, by contrast, exists only if CodeQL
has actually run.

It is :data:`RECORDED` rather than :data:`REQUIRED` for a sequencing reason: the
commit that *adds* the CodeQL workflow is judged before that workflow has ever
run, so requiring an analysis would fail the commit introducing the analysis.
What CodeQL finds is judged separately, against the severity threshold in
``docs/DEPENDENCY_POLICY.md``.
"""


def classify(control: Control, *, status: int, body: str) -> tuple[State, str]:
    """Turn one HTTP response into a state and the reason for it.

    Args:
        control: The control that was asked about.
        status: The HTTP status code.
        body: The response body, as text.

    Returns:
        The state, and a short reason recording what decided it.

    ``204 No Content`` is a pass: GitHub uses it for the alerts endpoint, where
    the answer is the status rather than a document. ``404`` is ambiguous by
    itself — it means both "off" and "no such thing" — so the message is read,
    and an unrecognised ``404`` is reported as :attr:`State.FAIL` rather than as
    unavailable, because a control that might be off must not be assumed absent.
    """
    lowered = body.lower()

    if status in {401, 403} and any(marker in lowered for marker in PLAN_MARKERS):
        return State.UNAVAILABLE_BY_PLAN, f"HTTP {status}: {_first_sentence(body)}"
    if status in {401, 403} and any(marker in lowered for marker in PERMISSION_MARKERS):
        return State.UNAVAILABLE_BY_PERMISSION, f"HTTP {status}: {_first_sentence(body)}"
    if status in {401, 403}:
        return State.FAIL, f"HTTP {status}: {_first_sentence(body)}"

    if status == 404:
        if any(marker in lowered for marker in PLAN_MARKERS):
            return State.UNAVAILABLE_BY_PLAN, f"HTTP 404: {_first_sentence(body)}"
        return State.FAIL, f"HTTP 404: {_first_sentence(body)}"

    if status == 204:
        return State.PASS, "HTTP 204"

    if status != 200:
        return State.ERROR, f"HTTP {status}: {_first_sentence(body)}"

    if not control.enabled_when:
        return State.PASS, "HTTP 200"

    try:
        document = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as fault:
        return State.ERROR, f"HTTP 200 with a body that is not JSON: {fault}"

    value: object = document
    for key in control.enabled_when:
        if not isinstance(value, dict):
            return State.ERROR, f"HTTP 200, but {'.'.join(control.enabled_when)} is not present"
        value = value.get(key)

    where = ".".join(control.enabled_when)
    enabled = value == control.expected_value if control.expected_value is not None else bool(value)
    if enabled:
        return State.PASS, f"{where} = {value!r}"
    if control.unavailable_reason:
        return State.UNAVAILABLE_BY_PLAN, f"{where} = {value!r}; {control.unavailable_reason}"
    return State.FAIL, f"{where} = {value!r}"


def _first_sentence(body: str) -> str:
    """The message from an error body, short enough to put in a manifest.

    Args:
        body: The response body.

    Returns:
        The ``message`` field if the body is a GitHub error document, otherwise
        the first line, truncated. Truncated because a manifest is read by people
        and a wall of JSON in a reason field is read by nobody.
    """
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return body.strip().splitlines()[0][:160] if body.strip() else "(no body)"
    if isinstance(document, dict):
        message = document.get("message")
        if isinstance(message, str):
            return message[:160]
    return "(no message)"


def judge(states: dict[str, tuple[State, str]]) -> tuple[str, ...]:
    """Which recorded states are policy failures.

    Args:
        states: Each control name mapped to its state and reason.

    Returns:
        One sentence per failure, empty when there is none.

    Only :attr:`State.FAIL` on a :data:`REQUIRED` control counts. An unavailable
    control is not a failure — nobody can fix it from here — and an unprobed one
    is not either, because the alternative is a gate that fails whenever it is
    run without network access.
    """
    policies = {control.name: control.policy for control in CONTROLS}
    return tuple(
        f"{name} is {state.value} ({reason}), and policy requires it to be enabled"
        for name, (state, reason) in sorted(states.items())
        if state is State.FAIL and policies.get(name) == REQUIRED
    )


def available() -> bool:
    """Whether the GitHub CLI is present at all.

    Returns:
        ``True`` when ``gh`` is on the path.

    Checked before probing so that a machine without it records
    :attr:`State.NOT_PROBED` with a reason, rather than an :attr:`State.ERROR`
    that reads like something is broken.
    """
    return shutil.which("gh") is not None


def probe(
    repository: str, *, timeout: int = 30, runner: Runner | None = None
) -> dict[str, tuple[State, str]]:
    """Ask GitHub about every control.

    Args:
        repository: The canonical ``owner/name``.
        timeout: Seconds allowed per request.
        runner: How to start ``gh``. Injected for the reason
            :mod:`tools.quality.supply.audit` gives; the default is the real thing.

    Returns:
        Each control name mapped to its state and the reason recorded for it.

    **Not called by the test suite.** It starts a process and reaches the network,
    and ADR-0024 makes the suite offline by construction. It is called by the gate
    when ``gh`` is present, and by CI in a job that is allowed to have a network.
    """
    if runner is None and not available():
        return {
            control.name: (State.NOT_PROBED, "the GitHub CLI is not installed")
            for control in CONTROLS
        }

    results: dict[str, tuple[State, str]] = {}
    for control in CONTROLS:
        path = f"repos/{repository}"
        if control.endpoint:
            path = f"{path}/{control.endpoint}"
        results[control.name] = _ask(control, path, timeout, runner or subprocess.run)
    return results


def _ask(control: Control, path: str, timeout: int, runner: Runner) -> tuple[State, str]:
    """One request, classified.

    Args:
        control: The control being asked about.
        path: The REST path.
        timeout: Seconds allowed.
        runner: How to start ``gh``.

    Returns:
        The state and its reason.

    ``gh api`` exits non-zero on an error status and prints the body, so the body
    is what is classified rather than the exit code. A timeout or a missing
    binary becomes :attr:`State.ERROR`, never a pass.
    """
    try:
        completed = runner(
            ["gh", "api", "-i", path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as fault:
        return State.ERROR, f"the probe could not run: {fault}"

    head, _, body = completed.stdout.partition("\n\n")
    first = head.splitlines()[0] if head.splitlines() else ""
    parts = first.split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if status == 0:
        return State.ERROR, f"no status line in the response: {completed.stderr.strip()[:160]}"
    return classify(control, status=status, body=body)
