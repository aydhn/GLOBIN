"""The short, readable version, for GitHub's step summary.

Pure: takes a manifest, returns markdown.

**Short by construction.** A step summary is read on a phone by somebody who
wants to know whether to care. It carries the verdict, the counts, the coverage
against its threshold and the slowest few tests. It carries no stack traces, no
raw log, and no list of a thousand test names — those are in the artifact, which
is where somebody who has decided to care will go.

Everything printed is ASCII, for the reason ``tools/quality/execution/gate.py``
gives: a console codepage that cannot render a character turns a report into a
traceback, and this one runs on Windows.
"""

from typing import Final

#: How many slow tests a summary names. Enough to see a pattern, few enough that
#: the table does not become the page.
SLOW_TEST_LIMIT: Final[int] = 5


def render(document: dict[str, object]) -> str:
    """Render a manifest as a step summary.

    Args:
        document: A manifest, as :func:`~tools.quality.evidence.manifest.build`
            produced it.

    Returns:
        Markdown, newline-terminated.
    """
    run = _section(document, "run")
    gates = _section(document, "gates")
    timing = _section(document, "timing")
    verdicts = {name: _passed(entry) for name, entry in gates.items()}
    overall = "PASSED" if verdicts and all(verdicts.values()) else "FAILED"

    lines = [
        "## GLOBIN test evidence",
        "",
        f"**{overall}** - profile `{run.get('profile', '?')}` "
        f"on {run.get('platform', '?')}, Python {run.get('python_version', '?')}",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Commit | `{run.get('git_sha', 'unknown')}` |",
        f"| Collected | {run.get('collected', 0)} |",
        f"| Passed | {run.get('passed', 0)} |",
        f"| Failed | {run.get('failed', 0)} |",
        f"| Errors | {run.get('errors', 0)} |",
        f"| Skipped | {run.get('skipped', 0)} |",
        f"| Duration | {_seconds(timing.get('duration_seconds'))} |",
        f"| Coverage | {_coverage(run)} |",
    ]

    if gates:
        lines.extend(["", "| Gate | Result | Findings |", "|---|---|---|"])
        lines.extend(
            f"| {name} | {_verdict(verdicts[name])} | {_findings(gates[name])} |"
            for name in sorted(gates)
        )

    slow = timing.get("slow_tests")
    if isinstance(slow, list) and slow:
        lines.extend(["", f"### Slowest {min(len(slow), SLOW_TEST_LIMIT)} tests", ""])
        lines.extend(
            f"- `{_text(entry.get('node_id'))}` - {_seconds(entry.get('seconds'))}"
            for entry in slow[:SLOW_TEST_LIMIT]
            if isinstance(entry, dict)
        )

    artifacts = run.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        lines.extend(["", f"Evidence files: {len(artifacts)}, listed in `checksums.sha256`."])

    return "\n".join(lines) + "\n"


def _section(document: dict[str, object], name: str) -> dict[str, object]:
    """One section of a manifest, or an empty one.

    Args:
        document: The manifest.
        name: The section's key.

    Returns:
        The section. A missing or malformed section renders as blanks rather than
        raising: a summary that crashed would take the diagnostics with it, and
        the manifest itself is already validated where it is loaded.
    """
    section = document.get(name)
    return section if isinstance(section, dict) else {}


def _coverage(run: dict[str, object]) -> str:
    """The coverage figure against its threshold.

    Args:
        run: The ``run`` section.

    Returns:
        Something like ``99.47% (floor 95.0%)``, or ``not measured``.
    """
    percent = run.get("percent_covered")
    if not isinstance(percent, int | float):
        return "not measured"
    threshold = run.get("coverage_threshold")
    floor = f" (floor {threshold}%)" if isinstance(threshold, int | float) else ""
    return f"{percent:.2f}%{floor}"


def _passed(entry: object) -> bool | None:
    """Read one gate's verdict out of its manifest entry.

    Args:
        entry: The recorded gate.

    Returns:
        Whether it passed, or ``None`` when it did not say.
    """
    if not isinstance(entry, dict):
        return None
    passed = entry.get("passed")
    return passed if isinstance(passed, bool) else None


def _findings(entry: object) -> str:
    """How many things a gate found.

    Args:
        entry: The recorded gate.

    Returns:
        The count, or ``-`` where the gate does not count anything. Coverage has
        no findings; a blank there would read as zero of them.
    """
    if not isinstance(entry, dict):
        return "-"
    findings = entry.get("findings")
    return str(findings) if isinstance(findings, int) and not isinstance(findings, bool) else "-"


def _verdict(value: object) -> str:
    """A gate's result, in the three states ``QUALITY_GATES.md`` allows.

    Args:
        value: The recorded verdict.

    Returns:
        ``passed``, ``FAILED``, or ``not run`` — never a blank, because "not
        run" reporting as anything else is the failure that document forbids.
    """
    if value is True:
        return "passed"
    if value is False:
        return "FAILED"
    return "not run"


def _seconds(value: object) -> str:
    """A duration, to two decimal places.

    Args:
        value: The recorded number.

    Returns:
        Something like ``32.16s``, or ``?`` when it is missing.
    """
    return f"{float(value):.2f}s" if isinstance(value, int | float) else "?"


def _text(value: object) -> str:
    """A field as text, without letting ``None`` render as ``None``.

    Args:
        value: The recorded value.

    Returns:
        The text, or ``?``.
    """
    return str(value) if isinstance(value, str) and value else "?"
