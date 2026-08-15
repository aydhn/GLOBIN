"""What the aggregate requires, and how a job's result is read.

Two jobs, both pure: read the declared configuration out of ``pyproject.toml``,
and turn GitHub's word for what happened to a job into a verdict this repository
already understands.

**The required list is declared, not discovered.** A gate that inferred which
jobs matter from whichever jobs happened to report would be satisfied by a
workflow with every job deleted. The list lives in ``[tool.globin.workflow]``
beside every other project setting, and ``tests/contract`` compares it against
the job names in the workflow file so the two cannot drift.

**Every unfamiliar answer is unmeasured.** GitHub documents four results for a
job — ``success``, ``failure``, ``cancelled`` and ``skipped`` — and a fifth would
be a platform change nobody here had read about. Mapping the unknown to "fine"
is how a green check comes to mean nothing.
"""

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.quality.execution.plan import Verdict

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository root, four levels up from this file."""

CONFIGURATION_FILE: Final[str] = "pyproject.toml"
"""Where the declared configuration lives. One settings file, per REPOSITORY_LAYOUT.md."""

CONFIGURATION_TABLE: Final[tuple[str, ...]] = ("tool", "globin", "workflow")
"""The path to this package's table, mirroring ``[tool.globin.mutation]``."""

NEEDS_VARIABLE: Final[str] = "GLOBIN_WORKFLOW_NEEDS"
"""Where the workflow passes ``toJSON(needs)``.

An environment variable rather than an argument. The value is a JSON document
containing quotes and braces, and threading that through a ``run:`` line intact
on a Windows runner is a quoting problem with no upside.
"""

DIGEST_VARIABLE: Final[str] = "GLOBIN_WORKFLOW_ARTIFACT_DIGEST"
"""Where the workflow passes the uploaded artifact's SHA-256, when it has one."""

CI_VARIABLE: Final[str] = "GITHUB_ACTIONS"
"""How the gate tells a CI run from a developer's machine.

Set by GitHub for every step. It is what makes a missing :data:`NEEDS_VARIABLE`
an error in CI and merely the local case at a desk.
"""

RESULTS: Final[tuple[tuple[str, Verdict], ...]] = (
    ("success", Verdict.PASSED),
    ("failure", Verdict.FAILED),
    ("cancelled", Verdict.UNMEASURED),
    ("skipped", Verdict.UNMEASURED),
)
"""Every job result GitHub documents, and what this repository reads it as.

A tuple of pairs rather than a ``dict`` display, for the reason
``globin.domain.serialization`` gives about ``frozenset``: this module is
imported by the gate, and a literal costs nothing to scan at two entries per
lookup.

``cancelled`` and ``skipped`` are both unmeasured rather than failed, and the
difference matters when reading a report. Neither says a test broke; both say
this run cannot tell you whether one did. ``combine`` then makes that outrank a
genuine failure, which is ``tools/quality/execution/plan.py``'s rule and is right
here for the same reason: doubt about what ran casts doubt on what passed.
"""


class WorkflowError(Exception):
    """The aggregate could not be determined from what it was given."""


@dataclass(frozen=True, slots=True)
class Configuration:
    """What the aggregate gate requires, as declared.

    Args:
        required_jobs: Jobs whose success the aggregate check depends on.
        required_check: The check name a repository administrator marks as
            required on ``master``.
        artifact: The name the evidence bundle is uploaded under.
        retention_days: How long GitHub keeps that bundle.
    """

    required_jobs: tuple[str, ...]
    required_check: str
    artifact: str
    retention_days: int


def read_configuration(document: Mapping[str, object]) -> Configuration:
    """Read ``[tool.globin.workflow]`` out of a parsed ``pyproject.toml``.

    Args:
        document: The parsed settings file.

    Returns:
        The configuration.

    Raises:
        WorkflowError: If the table is missing, or a key is absent or the wrong
            type.

    Strict on purpose, and modelled on
    :func:`tools.quality.mutation.plan.read_configuration`. A gate that defaulted
    a missing ``required_jobs`` to an empty list would pass every run, because
    there would be nothing left to be unhappy about.
    """
    table: Mapping[str, object] = document
    for name in CONFIGURATION_TABLE:
        value = table.get(name)
        if not isinstance(value, Mapping):
            path = ".".join(CONFIGURATION_TABLE)
            msg = f"{CONFIGURATION_FILE} has no [{path}] table"
            raise WorkflowError(msg)
        table = value
    jobs = _strings(table, "required_jobs")
    if not jobs:
        msg = "required_jobs is empty: an aggregate with nothing to require passes everything"
        raise WorkflowError(msg)
    return Configuration(
        required_jobs=jobs,
        required_check=_text(table, "required_check"),
        artifact=_text(table, "artifact"),
        retention_days=_integer(table, "retention_days"),
    )


def load_configuration(root: Path | None = None) -> Configuration:
    """Read the configuration from the repository's settings file.

    Args:
        root: The repository root. Defaults to :data:`REPO_ROOT`.

    Returns:
        The configuration.

    Raises:
        WorkflowError: If the file cannot be read or the table is malformed.
    """
    path = (REPO_ROOT if root is None else root) / CONFIGURATION_FILE
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as fault:
        msg = f"cannot read {CONFIGURATION_FILE}: {type(fault).__name__} ({fault})"
        raise WorkflowError(msg) from fault
    return read_configuration(document)


def classify(result: object) -> Verdict:
    """Read GitHub's word for what happened to a job.

    Args:
        result: The ``result`` field from the ``needs`` context, or whatever was
            found there.

    Returns:
        The verdict. Anything not documented is
        :attr:`~tools.quality.execution.plan.Verdict.UNMEASURED`.

    The default is the decision. A result this code has not been taught is a
    result nobody has reasoned about, and the only safe reading of one is that
    the run cannot say what happened.
    """
    for name, verdict in RESULTS:
        if result == name:
            return verdict
    return Verdict.UNMEASURED


def read_needs(text: str) -> dict[str, str]:
    """Read the ``needs`` context into a job-to-result mapping.

    Args:
        text: What ``toJSON(needs)`` produced.

    Returns:
        Each job name mapped to the ``result`` string it reported. A job whose
        entry carries no readable result is mapped to the empty string, which
        :func:`classify` reads as unmeasured.

    Raises:
        WorkflowError: If the text is not a JSON object.

    Only ``result`` is read. The context also carries each job's outputs, and
    copying those into the evidence would be putting whatever a job chose to emit
    into a published artifact — the sort of thing a secret ends up in.
    """
    try:
        context = json.loads(text)
    except json.JSONDecodeError as fault:
        msg = f"the {NEEDS_VARIABLE} context is not valid JSON: {fault}"
        raise WorkflowError(msg) from fault
    if not isinstance(context, dict):
        msg = f"the {NEEDS_VARIABLE} context must be a JSON object, got {type(context).__name__}"
        raise WorkflowError(msg)
    results: dict[str, str] = {}
    for job, entry in context.items():
        outcome = entry.get("result") if isinstance(entry, dict) else None
        results[str(job)] = outcome if isinstance(outcome, str) else ""
    return results


def job_verdicts(results: Mapping[str, str], *, required: tuple[str, ...]) -> dict[str, Verdict]:
    """Give every required job a verdict, including the ones that never reported.

    Args:
        results: What :func:`read_needs` read.
        required: The declared required jobs.

    Returns:
        One verdict per *required* job, in the declared order.

    A required job absent from the context is unmeasured rather than missing from
    the result. This is the case that motivates the whole package: a job removed
    from the workflow, or one whose ``needs`` chain skipped it, reports nothing at
    all — and a mapping built from what reported would simply not mention it,
    leaving every entry present and passing.

    Jobs in the context that are *not* required are ignored here and recorded
    separately, so that adding a job to the workflow does not silently become a
    requirement nobody declared.
    """
    return {job: classify(results.get(job)) for job in required}


def _strings(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Read a list of strings out of the table.

    Args:
        table: The configuration table.
        key: Which setting.

    Returns:
        The values.

    Raises:
        WorkflowError: If the setting is absent, is not a list, or holds
            anything that is not a string.
    """
    value = table.get(key)
    if not isinstance(value, list):
        msg = f"[tool.globin.workflow] {key} must be a list of strings"
        raise WorkflowError(msg)
    for item in value:
        if not isinstance(item, str):
            msg = f"[tool.globin.workflow] {key} holds {type(item).__name__}, expected a string"
            raise WorkflowError(msg)
    return tuple(value)


def _text(table: Mapping[str, object], key: str) -> str:
    """Read a string out of the table.

    Args:
        table: The configuration table.
        key: Which setting.

    Returns:
        The value.

    Raises:
        WorkflowError: If the setting is absent, is not a string, or is empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value:
        msg = f"[tool.globin.workflow] {key} must be a non-empty string"
        raise WorkflowError(msg)
    return value


def _integer(table: Mapping[str, object], key: str) -> int:
    """Read a positive integer out of the table.

    Args:
        table: The configuration table.
        key: Which setting.

    Returns:
        The value.

    Raises:
        WorkflowError: If the setting is absent, is a :class:`bool`, is not an
            :class:`int`, or is not positive.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"[tool.globin.workflow] {key} must be a positive integer"
        raise WorkflowError(msg)
    return value
