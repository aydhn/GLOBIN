"""Producing the evidence, and verifying it afterwards.

The only module in this package that starts a process or touches disk. Everything
it decides is decided by the pure modules beside it, which is what lets those be
tested from literals and this one be tested with an injected runner.

**The rule that shapes the whole file.** Evidence is produced whatever the suite
did, and the suite's verdict is never softened by having produced it. A run whose
tests failed writes its JUnit XML, its coverage, its manifest and its checksums —
and then returns non-zero. Swallowing a failure in order to publish an artifact
would make the artifact worthless and the gate a decoration.

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
import sys
from pathlib import Path
from typing import Final

from tools.quality.evidence import checksums, coverage_report, junit, manifest, redaction, summary
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
        "evidence-manifest.json",
        "checksums.sha256",
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

    try:
        document = _assemble(directory, junit_path, test_gate_passed=test_gate_passed)
    except EvidenceError as fault:
        print(f"evidence: the evidence could not be assembled: {fault}")
        print(suite_output.strip()[-2000:])
        return EXIT_UNMEASURED

    _write_summary(document)
    run = document["run"]
    assert isinstance(run, dict)  # noqa: S101 — built above, narrowing for mypy

    if not test_gate_passed:
        print(suite_output.strip()[-2000:])
    return _verdict(run, suite_code=suite_code)


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


def _assemble(directory: Path, junit_path: Path, *, test_gate_passed: bool) -> dict[str, object]:
    """Build the manifest and write it, then the checksums beside it.

    Args:
        directory: Where the evidence lives.
        junit_path: The JUnit report.
        test_gate_passed: Whether the suite itself passed.

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
        "coverage_gate_passed": coverage_gate_passed,
        "test_gate_passed": test_gate_passed,
        "artifacts": list(evidence_files()),
    }
    timing: dict[str, object] = {
        "duration_seconds": round(outcome.duration_seconds, 3),
        "slow_tests": [
            {"node_id": entry.node_id, "seconds": round(entry.seconds, 3)}
            for entry in junit.slowest(durations, limit=SLOW_TEST_LIMIT)
        ],
    }

    document = manifest.build(run=run, timing=timing)
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


def _verdict(run: dict[str, object], *, suite_code: int | None) -> int:
    """Turn the recorded gates into an exit code.

    Args:
        run: The manifest's ``run`` section.
        suite_code: What pytest returned, or ``None`` if it never did.

    Returns:
        The exit code.
    """
    if suite_code is None or run.get("coverage_gate_passed") is None:
        print("evidence: the result could not be determined, which is not a pass")
        return EXIT_UNMEASURED
    if not run.get("test_gate_passed"):
        print("evidence: FAILED - the suite did not pass. Evidence was written anyway.")
        return EXIT_GATE_FAILED
    if not run.get("coverage_gate_passed"):
        print(
            f"evidence: FAILED - coverage {run.get('percent_covered')}% is below "
            f"{run.get('coverage_threshold')}%. Evidence was written anyway."
        )
        return EXIT_GATE_FAILED
    print(
        f"evidence: passed - {run.get('collected')} tests, "
        f"{run.get('percent_covered')}% coverage, {len(evidence_files())} files written."
    )
    return EXIT_OK


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
