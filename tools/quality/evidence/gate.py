"""Producing the evidence, and verifying it afterwards.

The only module in this package that starts a process or touches disk. Everything
it decides is decided by the pure modules beside it, which is what lets those be
tested from literals and this one be tested with an injected runner.

**The rule that shapes the whole file.** Evidence is produced whatever the suite
did, and the suite's verdict is never softened by having produced it. A run whose
tests failed writes its JUnit XML, its coverage, its manifest and its checksums —
and then returns non-zero. Swallowing a failure in order to publish an artifact
would make the artifact worthless and the gate a decoration.

**Every gate runs, and then the verdict is given.** ``tools/quality/runner.py``
stops at the first failing step, and ``QUALITY_GATES.md`` makes that normative
for the commands it describes. This gate is deliberately the opposite: a run that
stopped at Ruff would produce no test evidence at all, which is the one thing it
exists to produce. Collecting every result and *then* returning non-zero is not a
softer rule — it is the same rule applied to five gates instead of one, and the
manifest records each separately so that "the suite failed" and "the types
failed" are never one undifferentiated failure.

**Three of the five are read into evidence, and one is only rendered.** JUnit XML,
coverage and the two tools' diagnostics are machine-readable and digested. The
HTML coverage tree is not: it is a rendering of ``coverage.json``, which *is*
digested, so checksumming forty generated pages would add forty lines that prove
nothing the one digest does not already prove.

**Why the suite is run here rather than reused from another gate.** So that one
command produces evidence, locally and in CI, from the same code. The sharded
gate already proves that coverage survives being measured in several processes
and combined; this one does not re-prove it, and says so rather than implying it.

Writes only under ``.globin/evidence``, which ``.gitignore`` already covers and
``tests/contract/test_execution_contract.py`` already asserts is uncommittable —
so this changes nothing about what the working tree may contain.
"""

import os
import platform
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from tools.quality.evidence import (
    checksums,
    coverage_report,
    diagnostics,
    junit,
    manifest,
    redaction,
    summary,
)
from tools.quality.evidence.junit import EvidenceError
from tools.quality.execution.plan import child_environment, interpreter
from tools.quality.execution.workspace import ProcessRunner, prepare, run_child, spawn

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""The repository root, four levels up from this file."""

REPORTS: Final[Path] = REPO_ROOT / ".globin" / "evidence"
"""Where evidence is written. Ignored by Git, like the sharded gate's directory."""

EXIT_OK: Final[int] = 0
EXIT_GATE_FAILED: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNMEASURED: Final[int] = 3
"""The same four codes ``tools/quality/execution`` uses, meaning the same things.
``EXIT_UNMEASURED`` is "the result could not be determined", which
``QUALITY_GATES.md`` insists is never reported as a pass."""

SELECTION: Final[str] = "not external"
"""The marker expression the evidence run collects under, matching the sharded
gate so that the two describe the same suite."""

PROFILE: Final[str] = "full"
"""Names which run this evidence describes, so a later phase adding a second
profile does not have to rename the first."""

SUITE_TIMEOUT_SECONDS: Final[float] = 1800.0
COMMAND_TIMEOUT_SECONDS: Final[float] = 300.0

COVERAGE_THRESHOLD_KEY: Final[str] = "fail_under"
DEFAULT_COVERAGE_THRESHOLD: Final[float] = 95.0
"""Read from ``pyproject.toml`` at run time; this is only the fallback used when
the key is absent, and it matches what ``QUALITY_GATES.md`` documents."""

SLOW_TEST_LIMIT: Final[int] = 10

SHA_LENGTH: Final[int] = 40
"""How long a Git object name is, named so the comparison below reads."""

HTML_DIRECTORY: Final[str] = "htmlcov"
"""Where the human-readable coverage rendering goes.

A directory rather than a file, and deliberately outside :func:`evidence_files`.
See the module docstring for why it is rendered rather than digested.
"""

COVERAGE_SUMMARY_FILE: Final[str] = "coverage-summary.txt"
"""The per-file coverage table, as ``coverage report`` prints it.

``show_missing`` is on in ``pyproject.toml``, so this carries the missing line
numbers as well as the percentages — which is most of what somebody opens the
HTML tree to find, in one small file that *is* digested.
"""

TOOL_TIMEOUT_SECONDS: Final[float] = 900.0
"""How long Ruff or mypy may take.

Longer than :data:`COMMAND_TIMEOUT_SECONDS` because mypy on a cold cache is
minutes rather than seconds, and shorter than the suite's because neither tool
runs a test.
"""


def junit_filename() -> str:
    """The JUnit report's name, built from what identifies the run.

    Returns:
        Something like ``junit-full-Windows-py314.xml``.

    Deterministic: no timestamp and no run number. The identity of a run lives
    inside the manifest, where it can be digested; a filename carrying it would
    make every artifact a different artifact and defeat comparison.
    """
    version = f"py{sys.version_info.major}{sys.version_info.minor}"
    return f"junit-{PROFILE}-{platform.system()}-{version}.xml"


def evidence_files() -> tuple[str, ...]:
    """Every file the gate writes, in a fixed order.

    Returns:
        The relative names, checksum manifest last because it describes the
        others and cannot describe itself.
    """
    return (
        junit_filename(),
        "coverage.xml",
        "coverage.json",
        COVERAGE_SUMMARY_FILE,
        "lint-ruff.json",
        "format-ruff.json",
        "typing-mypy.json",
        "evidence-manifest.json",
        "checksums.sha256",
    )


def tool_commands() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """The three tool gates, as a name, an evidence filename and an argv.

    Returns:
        One entry per gate, in the order they run.

    The argv are the ones ``tools/quality/commands.py`` already defines for
    ``lint``, ``format`` and ``typecheck``, plus a machine-readable output flag.
    Ruff is run **without** ``--fix`` and ``ruff format`` **with** ``--check``,
    which is ADR-0032's fifth condition and what
    ``tests/unit/test_quality_runner.py`` already refuses to let slip.
    """
    return (
        ("lint", "lint-ruff.json", ("-m", "ruff", "check", ".", "--output-format=json")),
        ("format", "format-ruff.json", ("-m", "ruff", "format", "--check", ".")),
        (
            "typing",
            "typing-mypy.json",
            ("-m", "mypy", "src/globin", "tests", "tools", "--output=json"),
        ),
    )


def run_evidence(*, reports: Path | None = None, run_process: ProcessRunner = spawn) -> int:
    """Run the suite, write the evidence, and report the verdict.

    Args:
        reports: Where to write. Defaults to :data:`REPORTS`; tests point it at a
            temporary directory.
        run_process: How to start a child. Injected so tests never spawn a real
            pytest.

    Returns:
        One of the four exit codes.
    """
    directory = REPORTS if reports is None else reports
    directory.mkdir(parents=True, exist_ok=True)
    prepare(directory)
    _prune(directory)

    junit_path = directory / junit_filename()
    coverage_data = directory / "run.coverage"
    environment = child_environment(os.environ, seed=0, coverage_file=str(coverage_data))

    print(f"evidence: running the suite under profile {PROFILE!r}")
    suite_code, suite_output = run_child(
        (interpreter(), *_suite_argv(junit_path)),
        cwd=REPO_ROOT,
        env=environment,
        timeout=SUITE_TIMEOUT_SECONDS,
        run_process=run_process,
    )
    test_gate_passed = suite_code == 0
    if suite_code is None:
        print("evidence: the suite did not finish; evidence will be partial")
    elif not test_gate_passed:
        print(f"evidence: the suite FAILED (exit {suite_code}); collecting evidence anyway")

    # Deliberately after the suite, and deliberately not conditional on it. A
    # failing run's coverage and timings are exactly what somebody needs.
    # `--fail-under=0` on both: the threshold is applied here, from the manifest,
    # so that a coverage failure is recorded as evidence before it is reported as
    # a verdict. Letting the report command exit non-zero on it would make an
    # under-covered run look like a run that could not be measured, and
    # `QUALITY_GATES.md` is explicit that those are different states.
    for argv, label in (
        (
            ("-m", "coverage", "xml", "--fail-under=0", "-o", str(directory / "coverage.xml")),
            "coverage.xml",
        ),
        (
            ("-m", "coverage", "json", "--fail-under=0", "-o", str(directory / "coverage.json")),
            "coverage.json",
        ),
    ):
        code, output = run_child(
            (interpreter(), *argv),
            cwd=REPO_ROOT,
            env=environment,
            timeout=COMMAND_TIMEOUT_SECONDS,
            run_process=run_process,
        )
        if code != 0:
            print(f"evidence: could not write {label} (exit {code})\n{output.strip()}")

    _write_coverage_summary(directory, environment=environment, run_process=run_process)
    _write_coverage_html(directory, environment=environment, run_process=run_process)
    _strip_repository_path(directory / "coverage.xml")
    # The raw coverage database is not evidence: every number in it is already in
    # `coverage.json`, and being a binary store of absolute paths it is the one
    # file here that cannot be normalised. It is removed once the reports that
    # need it have been written, because `.globin/evidence/` is uploaded whole.
    coverage_data.unlink(missing_ok=True)

    tool_gates = _run_tools(directory, environment=environment, run_process=run_process)

    try:
        document = _assemble(
            directory,
            junit_path,
            suite_code=suite_code,
            test_gate_passed=test_gate_passed,
            tool_gates=tool_gates,
        )
    except EvidenceError as fault:
        print(f"evidence: the evidence could not be assembled: {fault}")
        print(suite_output.strip()[-2000:])
        return EXIT_UNMEASURED

    _write_summary(document)
    run = document["run"]
    gates = document["gates"]
    assert isinstance(run, dict)  # noqa: S101 — built above, narrowing for mypy
    assert isinstance(gates, dict)  # noqa: S101 — built above, narrowing for mypy

    if not test_gate_passed:
        print(suite_output.strip()[-2000:])
    return _verdict(run, gates, suite_code=suite_code)


def verify_evidence(*, reports: Path | None = None) -> int:
    """Re-read what was written and check that it can still be trusted.

    Args:
        reports: Where the evidence is.

    Returns:
        :data:`EXIT_OK` when every check passes, :data:`EXIT_GATE_FAILED`
        otherwise.

    Checks, in order: every expected file is present; the JUnit XML parses; the
    coverage JSON parses; the manifest's schema version is supported and its
    digest describes its contents; its counts add up; every checksum matches; and
    nothing secret-shaped is in any of it.
    """
    directory = REPORTS if reports is None else reports
    problems: list[str] = []

    contents: dict[str, bytes] = {}
    for name in evidence_files():
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        contents[name] = path.read_bytes()

    if problems:
        _report(problems)
        return EXIT_GATE_FAILED

    problems.extend(_verify_readable(contents))
    problems.extend(f"checksums.sha256: {line}" for line in _verify_checksums(contents))
    problems.extend(
        f"{finding.source}:{finding.line}: {finding.description}"
        for name, payload in sorted(contents.items())
        for finding in redaction.scan(name, payload.decode("utf-8", errors="replace"))
    )

    if problems:
        _report(problems)
        return EXIT_GATE_FAILED
    print(f"evidence: {len(contents)} files verified in {directory.name}/")
    return EXIT_OK


def _prune(directory: Path) -> None:
    """Remove the previous run's evidence before writing this one's.

    Args:
        directory: Where the evidence lives.

    Without this, a run whose suite crashed before writing a JUnit report would
    be described by the *previous* run's report — the worst possible failure for
    a tool whose whole purpose is that the evidence matches the run. `prepare`
    handles the sharded gate's files and knows nothing about these.
    """
    for name in (*evidence_files(), "run.coverage"):
        (directory / name).unlink(missing_ok=True)
    shutil.rmtree(directory / HTML_DIRECTORY, ignore_errors=True)


def _suite_argv(junit_path: Path) -> tuple[str, ...]:
    """What the evidence run passes to pytest.

    Args:
        junit_path: Where the JUnit report goes.

    Returns:
        The arguments after the interpreter.

    ``--cov-fail-under=0`` because the threshold is applied here, from the
    manifest, so that a coverage failure is recorded as evidence before it is
    reported as a verdict. pytest exiting on it would leave nothing to record.
    """
    return (
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "-m",
        SELECTION,
        "--hypothesis-profile=ci",
        f"--junitxml={junit_path}",
        "--cov=globin",
        "--cov=tools",
        "--cov-branch",
        "--cov-report=",
        "--cov-fail-under=0",
        f"--durations={SLOW_TEST_LIMIT}",
    )


def _write_coverage_summary(
    directory: Path, *, environment: Mapping[str, str], run_process: ProcessRunner
) -> None:
    """Write the per-file coverage table a person reads.

    Args:
        directory: Where the evidence lives.
        environment: The child environment, carrying the coverage data file.
        run_process: How to start a child.

    ``coverage report`` prints to standard output and has no output flag, so the
    text is captured and written here. ``--fail-under=0`` for the reason the XML
    and JSON commands give: the threshold is applied from the manifest, so that a
    coverage failure is recorded before it is reported.
    """
    code, output = run_child(
        (interpreter(), "-m", "coverage", "report", "--fail-under=0"),
        cwd=REPO_ROOT,
        env=environment,
        timeout=COMMAND_TIMEOUT_SECONDS,
        run_process=run_process,
    )
    if code != 0:
        print(f"evidence: could not write {COVERAGE_SUMMARY_FILE} (exit {code})")
    (directory / COVERAGE_SUMMARY_FILE).write_text(output, encoding="utf-8", newline="\n")


def _write_coverage_html(
    directory: Path, *, environment: Mapping[str, str], run_process: ProcessRunner
) -> None:
    """Render the browsable coverage tree.

    Args:
        directory: Where the evidence lives.
        environment: The child environment, carrying the coverage data file.
        run_process: How to start a child.

    Failure is reported and not fatal. This is the one output nothing else
    depends on: the manifest reads ``coverage.json``, and a missing rendering
    costs a reader convenience rather than evidence.
    """
    code, output = run_child(
        (
            interpreter(),
            "-m",
            "coverage",
            "html",
            "--fail-under=0",
            "-d",
            str(directory / HTML_DIRECTORY),
        ),
        cwd=REPO_ROOT,
        env=environment,
        timeout=COMMAND_TIMEOUT_SECONDS,
        run_process=run_process,
    )
    if code != 0:
        print(f"evidence: could not render {HTML_DIRECTORY}/ (exit {code})\n{output.strip()}")


def _strip_repository_path(path: Path) -> None:
    """Replace this machine's repository path with a relative one, in place.

    Args:
        path: The generated report. A file that was never written is skipped.

    ``coverage xml`` writes the absolute repository root into a ``<source>``
    element, and on this host every absolute path contains the account holder's
    full name — so the file names a person and the artifact is published.

    Rewriting afterwards rather than configuring ``relative_files`` in
    ``pyproject.toml`` is deliberate: ADR-0036 decision 6 refuses that key
    because it would change what the existing ``coverage`` and ``full`` gates
    do, and this gate must not reach into theirs. Both spellings of the root are
    replaced, because a tool may report either separator.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    root = str(REPO_ROOT)
    stripped = text.replace(root, ".").replace(root.replace("\\", "/"), ".")
    if stripped != text:
        path.write_text(stripped, encoding="utf-8", newline="\n")


def _run_tools(
    directory: Path, *, environment: Mapping[str, str], run_process: ProcessRunner
) -> dict[str, object]:
    """Run Ruff and mypy, record what they found, and report how each fared.

    Args:
        directory: Where the evidence lives.
        environment: The child environment.
        run_process: How to start a child.

    Returns:
        One entry per gate: its exit code, whether it passed, and how many
        findings were recorded.

    Every gate runs. A tool that fails does not stop the next, because the point
    of collecting evidence is that one failure does not hide four other results.
    """
    readers: dict[str, Callable[[str], tuple[diagnostics.Diagnostic, ...]]] = {
        "lint": lambda text: diagnostics.from_ruff(text, repo_root=str(REPO_ROOT)),
        "format": lambda text: diagnostics.from_ruff_format(text, repo_root=str(REPO_ROOT)),
        "typing": lambda text: diagnostics.from_mypy(text, repo_root=str(REPO_ROOT)),
    }
    gates: dict[str, object] = {}
    for name, filename, argv in tool_commands():
        code, output = run_child(
            (interpreter(), *argv),
            cwd=REPO_ROOT,
            env=environment,
            timeout=TOOL_TIMEOUT_SECONDS,
            run_process=run_process,
        )
        try:
            found = readers[name](output)
        except EvidenceError as fault:
            print(f"evidence: {name} output could not be read: {fault}")
            found = ()
            readable = False
        else:
            readable = True
        document = diagnostics.build(
            tool=name,
            command=" ".join(argv),
            exit_code=code,
            diagnostics=found,
        )
        (directory / filename).write_text(
            diagnostics.render(document), encoding="utf-8", newline="\n"
        )
        if code is None:
            print(f"evidence: {name} did not finish; its result is unmeasured")
        elif code != 0:
            print(f"evidence: {name} FAILED (exit {code}), {len(found)} finding(s) recorded")
        gates[name] = {
            "exit_code": code,
            "passed": None if code is None else code == 0,
            "findings": len(found) if readable else None,
        }
    return gates


def _assemble(
    directory: Path,
    junit_path: Path,
    *,
    suite_code: int | None,
    test_gate_passed: bool,
    tool_gates: dict[str, object],
) -> dict[str, object]:
    """Build the manifest and write it, then the checksums beside it.

    Args:
        directory: Where the evidence lives.
        junit_path: The JUnit report.
        suite_code: What pytest returned, or ``None`` if it never did.
        test_gate_passed: Whether the suite itself passed.
        tool_gates: What Ruff and mypy did, already recorded.

    Returns:
        The manifest document.

    Raises:
        EvidenceError: If the JUnit report is missing or unreadable. That is
            fatal because without it there are no counts, and a manifest with no
            counts is not evidence about a test run.
    """
    if not junit_path.is_file():
        msg = f"no JUnit report at {junit_path.name}; the suite wrote nothing to read"
        raise EvidenceError(msg)

    outcome, durations = junit.parse(junit_path.read_text(encoding="utf-8"))
    coverage_path = directory / "coverage.json"
    measured = (
        coverage_report.parse(coverage_path.read_text(encoding="utf-8"))
        if coverage_path.is_file()
        else None
    )
    threshold = _coverage_threshold()
    coverage_gate_passed = None if measured is None else bool(measured.percent_covered >= threshold)

    run: dict[str, object] = {
        "project": "globin",
        "profile": PROFILE,
        "selection": SELECTION,
        "git_sha": _git_sha(),
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "collected": outcome.collected,
        "passed": outcome.passed,
        "failed": outcome.failed,
        "errors": outcome.errors,
        "skipped": outcome.skipped,
        "percent_covered": None if measured is None else round(measured.percent_covered, 2),
        "covered_lines": None if measured is None else measured.covered_lines,
        "num_statements": None if measured is None else measured.num_statements,
        "num_branches": None if measured is None else measured.num_branches,
        "covered_branches": None if measured is None else measured.covered_branches,
        "branch_coverage_enabled": None if measured is None else measured.branch_enabled,
        "coverage_threshold": threshold,
        "artifacts": list(evidence_files()),
        "renderings": [f"{HTML_DIRECTORY}/"],
    }
    timing: dict[str, object] = {
        "duration_seconds": round(outcome.duration_seconds, 3),
        "slow_tests": [
            {"node_id": entry.node_id, "seconds": round(entry.seconds, 3)}
            for entry in junit.slowest(durations, limit=SLOW_TEST_LIMIT)
        ],
    }

    gates: dict[str, object] = {
        "tests": {
            "exit_code": suite_code,
            "passed": test_gate_passed,
            "findings": outcome.failed + outcome.errors,
        },
        # Coverage has no exit code of its own: the report commands run with
        # `--fail-under=0` so that a low figure is recorded before it is judged,
        # and the judgement is made here against the threshold in the manifest.
        "coverage": {
            "exit_code": None,
            "passed": coverage_gate_passed,
            "findings": None,
        },
        **tool_gates,
    }

    document = manifest.build(run=run, timing=timing, gates=gates)
    (directory / "evidence-manifest.json").write_text(
        manifest.render(document), encoding="utf-8", newline="\n"
    )

    present = {
        name: (directory / name).read_bytes()
        for name in evidence_files()
        if name != "checksums.sha256" and (directory / name).is_file()
    }
    (directory / "checksums.sha256").write_text(
        checksums.render(present), encoding="utf-8", newline="\n"
    )
    return document


def _verify_readable(contents: dict[str, bytes]) -> list[str]:
    """Check that every machine-readable evidence file still parses.

    Args:
        contents: Each file's bytes.

    Returns:
        One line per problem.
    """
    problems: list[str] = []
    checks = (
        (junit_filename(), lambda text: junit.parse(text)),
        ("coverage.json", lambda text: coverage_report.parse(text)),
        ("evidence-manifest.json", lambda text: manifest.load(text)),
    )
    for name, read in checks:
        try:
            read(contents[name].decode("utf-8"))
        except (EvidenceError, UnicodeDecodeError) as fault:
            problems.append(f"{name}: {fault}")

    try:
        document = manifest.load(contents["evidence-manifest.json"].decode("utf-8"))
    except (EvidenceError, UnicodeDecodeError):
        return problems
    run = document.get("run")
    if isinstance(run, dict):
        problems.extend(
            f"evidence-manifest.json: {line}" for line in manifest.counts_are_consistent(run)
        )
    return problems


def _verify_checksums(contents: dict[str, bytes]) -> tuple[str, ...]:
    """Compare the recorded digests against the files present.

    Args:
        contents: Each file's bytes, including the checksum manifest itself.

    Returns:
        One line per disagreement.
    """
    try:
        recorded = checksums.load(contents["checksums.sha256"].decode("utf-8"))
    except (EvidenceError, UnicodeDecodeError) as fault:
        return (str(fault),)
    described = {name: payload for name, payload in contents.items() if name != "checksums.sha256"}
    return checksums.verify(recorded, described)


def _verdict(run: dict[str, object], gates: dict[str, object], *, suite_code: int | None) -> int:
    """Turn the recorded gates into one exit code.

    Args:
        run: The manifest's ``run`` section.
        gates: The manifest's ``gates`` section, one entry per gate.
        suite_code: What pytest returned, or ``None`` if it never did.

    Returns:
        The exit code.

    Unmeasured outranks failed, as it does in ``tools/quality/execution/plan.py``
    and for the same reason: ``QUALITY_GATES.md`` is explicit that a gate which
    did not run never reports as one that passed, and a run reported as merely
    failed invites somebody to fix the failure and believe the rest was checked.

    Every failing gate is named. One line saying "the gate failed" after five
    gates ran is a message that sends a reader to the wrong file half the time.
    """
    verdicts = {name: _gate_passed(entry) for name, entry in gates.items()}
    unmeasured = sorted(name for name, passed in verdicts.items() if passed is None)
    failed = sorted(name for name, passed in verdicts.items() if passed is False)

    if suite_code is None or unmeasured:
        named = ", ".join(unmeasured) or "the suite"
        print(f"evidence: UNMEASURED - {named} did not report, which is not a pass")
        return EXIT_UNMEASURED
    if failed:
        print(f"evidence: FAILED - {', '.join(failed)}. Evidence was written anyway.")
        if "coverage" in failed:
            print(
                f"evidence:   coverage {run.get('percent_covered')}% is below "
                f"{run.get('coverage_threshold')}%"
            )
        return EXIT_GATE_FAILED
    print(
        f"evidence: passed - {len(verdicts)} gates, {run.get('collected')} tests, "
        f"{run.get('percent_covered')}% coverage, {len(evidence_files())} files written."
    )
    return EXIT_OK


def _gate_passed(entry: object) -> bool | None:
    """Read one gate's verdict out of its manifest entry.

    Args:
        entry: The recorded gate.

    Returns:
        Whether it passed, or ``None`` when it did not say — which includes an
        entry that is not the shape this module writes, because a manifest that
        cannot be read is not one reporting success.
    """
    if not isinstance(entry, dict):
        return None
    passed = entry.get("passed")
    return passed if isinstance(passed, bool) else None


def _write_summary(document: dict[str, object]) -> None:
    """Append the step summary, when GitHub asked for one.

    Args:
        document: The manifest.

    Does nothing when ``GITHUB_STEP_SUMMARY`` is unset, which is what makes the
    local and CI paths the same code rather than two implementations.
    """
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        with Path(target).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(summary.render(document))
    except OSError as fault:
        print(f"evidence: could not write the step summary: {fault}")


def _coverage_threshold() -> float:
    """The coverage floor, read from the one place that defines it.

    Returns:
        ``fail_under`` from ``pyproject.toml``, or the documented default when
        the file cannot be read.

    Read rather than restated. A threshold copied into this module would be a
    second source of truth for a number ``QUALITY_GATES.md`` says lives in
    ``pyproject.toml``, and the copies would drift the first time one moved.
    """
    import tomllib

    try:
        document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_COVERAGE_THRESHOLD
    tool = document.get("tool", {})
    report = tool.get("coverage", {}).get("report", {}) if isinstance(tool, dict) else {}
    value = report.get(COVERAGE_THRESHOLD_KEY) if isinstance(report, dict) else None
    return float(value) if isinstance(value, int | float) else DEFAULT_COVERAGE_THRESHOLD


def _git_sha() -> str:
    """The commit under test, read without starting a process.

    Returns:
        The forty-character SHA, or ``"unknown"`` when it cannot be determined.

    Read from ``.git`` directly rather than by running ``git rev-parse``, so that
    evidence can be produced in a tree without Git on the path. ``unknown`` is a
    legitimate answer and is recorded as one, because a manifest that invented a
    commit would be worse than one admitting it does not know.
    """
    head = REPO_ROOT / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not text.startswith("ref:"):
        return text if len(text) == SHA_LENGTH else "unknown"
    reference = REPO_ROOT / ".git" / text.removeprefix("ref:").strip()
    try:
        return reference.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _report(problems: list[str]) -> None:
    """Print what verification found.

    Args:
        problems: The lines, printed sorted so two runs report identically.
    """
    print(f"evidence: verification FAILED, {len(problems)} problem(s):")
    for line in sorted(problems):
        print(f"  {line}")
