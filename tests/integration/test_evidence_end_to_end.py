"""The evidence gate, composed, with the subprocess replaced.

The gate is the only impure module in its package, so this is where it is
exercised: the suite, the two coverage report commands, the manifest, the
checksums, the step summary and the verdict, all in one call.

No real pytest is started. A hand-written `ProcessRunner` stands in, writing the
files a real child would write and returning the exit code the test wants — which
is what makes "the suite failed" a case that can be tested at all, and what keeps
this from taking half a minute per assertion. That double is a plain object
satisfying the Protocol, which `docs/TESTING_STRATEGY.md` names as the default
over a mock.

Every path is under `tmp_path`. Nothing here writes into the repository.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import pytest

from tools.quality.evidence import checksums, manifest
from tools.quality.evidence.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    EXIT_UNMEASURED,
    REPO_ROOT,
    evidence_files,
    junit_filename,
    run_evidence,
    verify_evidence,
)

PASSING_JUNIT: Final[str] = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="globin" errors="0" failures="0" skipped="0" tests="2" time="1.250">
    <testcase classname="tests.unit.test_a" name="test_one" time="1.000"/>
    <testcase classname="tests.unit.test_a" name="test_two" time="0.250"/>
  </testsuite>
</testsuites>
"""

FAILING_JUNIT: Final[str] = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="globin" errors="0" failures="1" skipped="0" tests="2" time="1.250">
    <testcase classname="tests.unit.test_a" name="test_one" time="1.000"/>
    <testcase classname="tests.unit.test_a" name="test_two" time="0.250">
      <failure message="assert False">trace</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def coverage_json(percent: float) -> str:
    """A coverage report at a chosen percentage.

    Args:
        percent: What `totals.percent_covered` should say.

    Returns:
        The document.
    """
    return json.dumps(
        {
            "totals": {
                "covered_lines": 90,
                "num_statements": 100,
                "percent_covered": percent,
                "num_branches": 20,
                "covered_branches": 18,
            }
        }
    )


class FakeRunner:
    """A `ProcessRunner` that writes what a real child would, and no more.

    Args:
        junit: The report the suite should leave behind, or `None` to leave
            none — which is how "the suite crashed before writing anything" is
            expressed.
        suite_code: What pytest should appear to return.
        coverage_percent: What the coverage reports should say.
        report_code: What the coverage report commands should return.
    """

    def __init__(  # noqa: D107 - the class docstring above documents every argument
        self,
        *,
        junit: str | None = PASSING_JUNIT,
        suite_code: int = 0,
        coverage_percent: float = 99.5,
        report_code: int = 0,
    ) -> None:
        self.junit = junit
        self.suite_code = suite_code
        self.coverage_percent = coverage_percent
        self.report_code = report_code
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> tuple[int, bytes]:
        """Pretend to run one child, writing whatever it would have written."""
        del cwd, env, timeout
        arguments = tuple(argv)
        self.commands.append(arguments)

        for argument in arguments:
            if argument.startswith("--junitxml="):
                if self.junit is not None:
                    Path(argument.removeprefix("--junitxml=")).write_text(
                        self.junit, encoding="utf-8"
                    )
                return self.suite_code, b"suite output"

        # A report command that fails writes nothing. That is what makes
        # `report_code=1` mean "coverage could not be measured" rather than
        # "coverage was measured and the command grumbled", which is a different
        # situation and already covered by `coverage_percent`.
        if "xml" in arguments:
            if self.report_code == 0:
                # What `coverage xml` actually writes, including the absolute
                # `<source>` element. Every test in this file therefore
                # exercises the stripping, rather than one test that could be
                # deleted without the others noticing.
                Path(arguments[-1]).write_text(
                    f"<coverage><sources><source>{REPO_ROOT}</source></sources></coverage>",
                    encoding="utf-8",
                )
            return self.report_code, b""
        if "json" in arguments:
            if self.report_code == 0:
                Path(arguments[-1]).write_text(
                    coverage_json(self.coverage_percent), encoding="utf-8"
                )
            return self.report_code, b""
        return 0, b""


def _verdicts(document: dict[str, object]) -> dict[str, object]:
    """Each gate's verdict, by name, read out of a manifest.

    Args:
        document: A loaded manifest.

    Returns:
        One entry per gate, carrying ``True``, ``False`` or ``None``.

    Since schema version 2 a verdict lives in ``gates`` and nowhere else, so
    every assertion about whether something passed comes through here.
    """
    gates = document["gates"]
    assert isinstance(gates, dict)
    return {
        name: entry.get("passed") if isinstance(entry, dict) else None
        for name, entry in gates.items()
    }


def test_a_passing_run_writes_every_file_and_verifies(tmp_path: Path) -> None:
    """The success path, end to end, including its own verification."""
    assert run_evidence(reports=tmp_path, run_process=FakeRunner()) == EXIT_OK
    for name in (junit_filename(), "coverage.xml", "coverage.json", "evidence-manifest.json"):
        assert (tmp_path / name).is_file(), name
    assert verify_evidence(reports=tmp_path) == EXIT_OK


def test_the_manifest_records_what_the_run_found(tmp_path: Path) -> None:
    """The counts, the coverage and the verdicts come from the files, not from hope."""
    run_evidence(reports=tmp_path, run_process=FakeRunner(coverage_percent=99.5))
    document = manifest.load((tmp_path / "evidence-manifest.json").read_text(encoding="utf-8"))
    run = document["run"]
    assert isinstance(run, dict)
    assert (run["collected"], run["passed"], run["failed"]) == (2, 2, 0)
    assert run["percent_covered"] == pytest.approx(99.5)
    assert manifest.counts_are_consistent(run) == ()
    assert _verdicts(document) == {
        "tests": True,
        "coverage": True,
        "lint": True,
        "format": True,
        "typing": True,
    }


def test_the_manifest_carries_no_absolute_path_and_no_timestamp(tmp_path: Path) -> None:
    """A published file must not leak this machine's layout.

    The user name in the repository path is the concrete risk: it is in every
    absolute path on this host, and an artifact is a thing other people download.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    text = (tmp_path / "evidence-manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert ":\\" not in text
    assert "/home/" not in text
    assert "timestamp" not in text


def test_no_published_file_carries_this_machines_repository_path(tmp_path: Path) -> None:
    """The leak that was found in practice, turned into a gate.

    `coverage xml` writes the absolute repository root into a `<source>`
    element. On this host every absolute path contains the account holder's full
    name, and `.globin/evidence/` is uploaded whole — so the artifact named a
    person until Phase 011 stripped it.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    root = str(REPO_ROOT)
    for name in evidence_files():
        text = (tmp_path / name).read_text(encoding="utf-8", errors="replace")
        assert root not in text, name
        assert root.replace("\\", "/") not in text, name


def test_the_raw_coverage_database_is_not_left_to_be_uploaded(tmp_path: Path) -> None:
    """The one file here that cannot be normalised, so it is removed instead.

    It is a binary store of absolute paths, every number in it is already in
    `coverage.json`, and the upload takes the whole directory.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    assert not (tmp_path / "run.coverage").exists()


def test_a_failing_suite_still_produces_evidence_but_still_fails(tmp_path: Path) -> None:
    """The condition the whole design turns on.

    Producing an artifact must never soften the verdict, and a failing run is
    exactly when its diagnostics are worth most.
    """
    code = run_evidence(reports=tmp_path, run_process=FakeRunner(junit=FAILING_JUNIT, suite_code=1))
    assert code == EXIT_GATE_FAILED

    document = manifest.load((tmp_path / "evidence-manifest.json").read_text(encoding="utf-8"))
    run = document["run"]
    assert isinstance(run, dict)
    assert _verdicts(document)["tests"] is False
    assert run["failed"] == 1
    assert (tmp_path / "checksums.sha256").is_file()
    assert verify_evidence(reports=tmp_path) == EXIT_OK


def test_coverage_below_the_floor_fails_the_gate_and_is_recorded(tmp_path: Path) -> None:
    """A coverage failure is evidence first and a verdict second."""
    code = run_evidence(reports=tmp_path, run_process=FakeRunner(coverage_percent=42.0))
    assert code == EXIT_GATE_FAILED
    document = manifest.load((tmp_path / "evidence-manifest.json").read_text(encoding="utf-8"))
    run = document["run"]
    assert isinstance(run, dict)
    assert _verdicts(document)["coverage"] is False
    assert run["percent_covered"] == pytest.approx(42.0)


def test_a_suite_that_wrote_no_report_is_unmeasured_rather_than_passing(tmp_path: Path) -> None:
    """`QUALITY_GATES.md`: "not run" never reports as "passed"."""
    code = run_evidence(reports=tmp_path, run_process=FakeRunner(junit=None, suite_code=1))
    assert code == EXIT_UNMEASURED
    assert not (tmp_path / "evidence-manifest.json").exists()


def test_unmeasurable_coverage_is_unmeasured_rather_than_zero(tmp_path: Path) -> None:
    """A missing coverage report must not be recorded as nought per cent."""
    code = run_evidence(reports=tmp_path, run_process=FakeRunner(report_code=1))
    assert code == EXIT_UNMEASURED
    document = manifest.load((tmp_path / "evidence-manifest.json").read_text(encoding="utf-8"))
    run = document["run"]
    assert isinstance(run, dict)
    assert run["percent_covered"] is None
    assert _verdicts(document)["coverage"] is None


def test_the_previous_run_is_removed_before_the_next_one_is_written(tmp_path: Path) -> None:
    """The worst failure a tool like this could have.

    A crashed suite that left the previous run's report in place would produce a
    manifest describing a run that did not happen, with a digest saying it was
    intact.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    assert (tmp_path / junit_filename()).is_file()

    code = run_evidence(reports=tmp_path, run_process=FakeRunner(junit=None, suite_code=1))
    assert code == EXIT_UNMEASURED
    assert not (tmp_path / junit_filename()).exists()


def test_a_tampered_artifact_fails_verification(tmp_path: Path) -> None:
    """The checksum manifest doing the one job it exists for."""
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    report = tmp_path / junit_filename()
    report.write_text(report.read_text(encoding="utf-8").replace('tests="2"', 'tests="9"'))
    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED


def test_an_edited_manifest_fails_verification(tmp_path: Path) -> None:
    """Editing a count to make a run look better is caught by the digest."""
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    target = tmp_path / "evidence-manifest.json"
    target.write_text(target.read_text(encoding="utf-8").replace('"passed":2', '"passed":9'))
    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED


def test_a_missing_file_fails_verification_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verification reports what is wrong, not merely that something is."""
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    (tmp_path / "coverage.json").unlink()
    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED
    assert "coverage.json: missing" in capsys.readouterr().out


def test_a_corrupt_report_fails_verification_even_with_matching_checksums(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Integrity and readability are different questions.

    A file can be exactly what was recorded and still be unparseable, so the
    checksums alone would pass it. Re-parsing is what catches a truncated write.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    (tmp_path / "coverage.json").write_text("{ truncated", encoding="utf-8")
    payloads = {
        name: (tmp_path / name).read_bytes()
        for name in ("coverage.json", "coverage.xml", junit_filename(), "evidence-manifest.json")
    }
    (tmp_path / "checksums.sha256").write_text(checksums.render(payloads), encoding="utf-8")

    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED
    assert "coverage.json: the coverage report is not valid JSON" in capsys.readouterr().out


def test_a_secret_in_an_artifact_fails_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The backstop, exercised.

    `junit_logging = "no"` is what keeps captured output out of the XML. This is
    what notices if that ever stops being true.
    """
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    leaked = tmp_path / junit_filename()
    leaked.write_text(
        leaked.read_text(encoding="utf-8").replace(
            "<testcase", "<!-- api_key = NOT-A-REAL-SECRET-0000 -->\n    <testcase", 1
        )
    )
    payloads = {
        name: (tmp_path / name).read_bytes()
        for name in ("coverage.json", "coverage.xml", junit_filename(), "evidence-manifest.json")
    }
    (tmp_path / "checksums.sha256").write_text(checksums.render(payloads), encoding="utf-8")

    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED
    printed = capsys.readouterr().out
    assert "api_key" in printed
    assert "NOT-A-REAL-SECRET-0000" not in printed


def test_verification_of_an_empty_directory_reports_every_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifying evidence that was never produced must fail, not pass vacuously."""
    assert verify_evidence(reports=tmp_path) == EXIT_GATE_FAILED
    assert capsys.readouterr().out.count("missing") == len(evidence_files())


def test_the_step_summary_is_written_only_when_github_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same code runs locally and in CI; only the environment differs.

    `monkeypatch.setenv` rather than assigning to `os.environ`, because the
    autouse isolation fixture fails any test that leaks a variable.
    """
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    run_evidence(reports=tmp_path, run_process=FakeRunner())
    assert "## GLOBIN test evidence" in target.read_text(encoding="utf-8")


def test_an_unwritable_step_summary_does_not_lose_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A summary is a convenience; the exit code is the result.

    Pointing the variable at a directory makes the open fail on every platform
    without needing a permission trick that only works on one.
    """
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    assert run_evidence(reports=tmp_path, run_process=FakeRunner()) == EXIT_OK
    assert "could not write the step summary" in capsys.readouterr().out


def test_the_suite_is_asked_for_junit_coverage_and_durations(tmp_path: Path) -> None:
    """The flags the evidence depends on, asserted rather than assumed.

    If `--junitxml` were dropped the gate would report `EXIT_UNMEASURED` and
    somebody would spend an afternoon on it; this names the cause instead.
    """
    runner = FakeRunner()
    run_evidence(reports=tmp_path, run_process=runner)
    suite = runner.commands[0]
    assert any(argument.startswith("--junitxml=") for argument in suite)
    assert "--cov=globin" in suite
    assert "--cov-branch" in suite
    assert any(argument.startswith("--durations=") for argument in suite)
    # The threshold is applied from the manifest, so pytest must not exit on it.
    assert "--cov-fail-under=0" in suite


def test_the_coverage_reports_do_not_re_apply_the_threshold(tmp_path: Path) -> None:
    """`coverage xml` exiting 2 on a low figure would look like an unmeasured run.

    Those are different states, and conflating them is what `QUALITY_GATES.md`
    forbids.
    """
    runner = FakeRunner()
    run_evidence(reports=tmp_path, run_process=runner)
    coverage_commands = [command for command in runner.commands if "coverage" in command]
    assert coverage_commands, "no coverage command ran, so this asserted nothing"
    for command in coverage_commands:
        assert "--fail-under=0" in command
