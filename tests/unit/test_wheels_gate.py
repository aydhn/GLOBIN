"""The wheel-survey gate against trees built for the purpose.

``tests/contract/test_wheels_contract.py`` asserts facts about *this* repository's
survey. This asserts that the gate reaches the right verdict about a tree, which
means most of these trees are deliberately wrong in one way each.

**Offline, including the probe.** The fetcher is injected, so the network path is
exercised by a function that returns a string. That is not a convenience: ADR-0024
enforces the offline guarantee by refusing sockets in the test process, so a gate
that opened one here would be caught as a failing *test* rather than as a gate
reaching the network. A substitutable seam is what lets the path be tested at all.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tools.quality.execution.plan import Verdict
from tools.quality.wheels import gate, manifest
from tools.quality.wheels.gate import _finding, _report, _verdict_of
from tools.quality.wheels.manifest import build as build_manifest

CONTRACT = """
schema = 1

[interpreter]
implementation = "CPython"
minor_line = "3.14"
minimum_patch = "3.14.5"
architecture = "AMD64"
pointer_bits = 64
free_threaded = false
allow_prerelease = false

[host]
system = "Windows"
minimum_release = "10"

[environment]
directory = ".venv"
system_site_packages = false
"""

SURVEY = """
schema = 1

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"
platform_tag = "win_amd64"
free_threaded = false
index = "https://pypi.org/pypi/"
surveyed = 2026-08-16

[[library]]
name = "optuna"
phase = 211
version = "4.9.0"
requires_python = ">=3.9"
wheels = ["optuna-4.9.0-py3-none-any.whl"]
verdict = "available"
source = "https://pypi.org/pypi/optuna/json"
reason = "The study infrastructure Phase 211 establishes."

[[library]]
name = "ta-lib"
phase = 25
version = "0.7.1"
requires_python = ">=3.9"
wheels = ["ta_lib-0.7.1-cp314-cp314-win_amd64.whl"]
verdict = "available"
source = "https://pypi.org/pypi/ta-lib/json"
reason = "The wrapper Phases 025 and 114 name."
"""


def build_tree(root: Path, *, survey: str = SURVEY, contract: str = CONTRACT) -> Path:
    """Write the two files the gate reads, and a Git head for it to record."""
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True)
    (engineering / "wheel-survey.toml").write_text(survey, encoding="utf-8")
    (engineering / "runtime-contract.toml").write_text(contract, encoding="utf-8")
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("a" * 40, encoding="utf-8")
    return root


def read_manifest(reports: Path) -> dict[str, object]:
    """Read back what the gate wrote, verifying its digest on the way."""
    return manifest.load((reports / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def findings_of(document: Mapping[str, object]) -> Mapping[str, object]:
    """The findings section, typed for the assertions below."""
    section = document["findings"]
    assert isinstance(section, Mapping)
    return section


def reasons_of(document: Mapping[str, object]) -> list[str]:
    """The reason codes the run recorded."""
    verdict = document["verdict"]
    assert isinstance(verdict, Mapping)
    recorded = verdict["reasons"]
    assert isinstance(recorded, list)
    return [str(reason) for reason in recorded]


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    """Where a run writes, kept out of the tree it reads."""
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_consistent_survey_passes_and_writes_a_manifest(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_OK
    document = read_manifest(reports)
    assert document["phase"] == manifest.PHASE
    assert reasons_of(document) == []


def test_the_manifest_records_what_was_checked_and_against_what(
    tmp_path: Path, reports: Path
) -> None:
    root = build_tree(tmp_path / "tree")
    gate.run_wheels(root=root, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, Mapping)
    assert run["mode"] == "check"
    assert run["declaration"] == "docs/engineering/wheel-survey.toml"
    assert run["contract"] == "docs/engineering/runtime-contract.toml"
    assert run["libraries"] == 2


def test_the_manifest_carries_no_wall_clock_and_no_absolute_path(
    tmp_path: Path, reports: Path
) -> None:
    """It is uploaded as a public-repository artifact.

    Every absolute path on the development host carries the account holder's name,
    and a timestamp would make two runs of the same commit disagree.
    """
    root = build_tree(tmp_path / "tree")
    gate.run_wheels(root=root, reports=reports)
    rendered = (reports / gate.MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in rendered
    assert str(tmp_path).replace("\\", "/") not in rendered
    assert "timestamp" not in rendered


def test_two_runs_of_the_same_tree_write_the_same_bytes(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree")
    gate.run_wheels(root=root, reports=reports)
    first = (reports / gate.MANIFEST_NAME).read_bytes()
    gate.run_wheels(root=root, reports=reports)
    assert (reports / gate.MANIFEST_NAME).read_bytes() == first


def test_the_reports_directory_is_created_when_it_does_not_exist(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    directory = tmp_path / "absent" / "deeper"
    assert gate.run_wheels(root=root, reports=directory) == gate.EXIT_OK
    assert (directory / gate.MANIFEST_NAME).is_file()


# ---------------------------------------------------------------------------
# Reading its own inputs
# ---------------------------------------------------------------------------


def test_an_absent_declaration_fails_and_still_writes_a_manifest(
    tmp_path: Path, reports: Path
) -> None:
    """A gate that left no artefact would be indistinguishable from one that never ran."""
    root = tmp_path / "empty"
    root.mkdir()
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert reasons_of(read_manifest(reports)) == [manifest.REASON_DECLARATION_UNREADABLE]


def test_a_malformed_declaration_fails_by_name(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree", survey="schema = 99")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert reasons_of(read_manifest(reports)) == [manifest.REASON_DECLARATION_UNREADABLE]


def test_an_absent_runtime_contract_fails(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree")
    (root / "docs" / "engineering" / "runtime-contract.toml").unlink()
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert reasons_of(read_manifest(reports)) == [manifest.REASON_TARGET_DIVERGED]


def test_a_malformed_runtime_contract_fails(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree", contract="schema = 99")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert reasons_of(read_manifest(reports)) == [manifest.REASON_TARGET_DIVERGED]


def test_a_commit_that_cannot_be_read_is_recorded_as_unknown_rather_than_invented(
    tmp_path: Path, reports: Path
) -> None:
    root = build_tree(tmp_path / "tree")
    (root / ".git" / "HEAD").unlink()
    gate.run_wheels(root=root, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, Mapping)
    assert run["commit"] == "unknown"


# ---------------------------------------------------------------------------
# What each check catches
# ---------------------------------------------------------------------------


def test_a_survey_against_another_interpreter_is_reported(tmp_path: Path, reports: Path) -> None:
    root = build_tree(
        tmp_path / "tree", survey=SURVEY.replace('minor_line = "3.14"', 'minor_line = "3.13"')
    )
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_TARGET_DIVERGED in reasons_of(read_manifest(reports))


def test_a_verdict_its_own_evidence_contradicts_is_reported(tmp_path: Path, reports: Path) -> None:
    root = build_tree(
        tmp_path / "tree",
        survey=SURVEY.replace(
            '"ta_lib-0.7.1-cp314-cp314-win_amd64.whl"', '"ta_lib-0.7.1-cp313-cp313-win_amd64.whl"'
        ),
    )
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    recorded = reasons_of(read_manifest(reports))
    assert manifest.REASON_RECORD_INCONSISTENT in recorded


TA_LIB_WHEEL = '"ta_lib-0.7.1-cp314-cp314-win_amd64.whl"'
TA_LIB_VERDICT = 'verdict = "available"\nsource = "https://pypi.org/pypi/ta-lib/json"'


def survey_with_a_gap(*, owner: int | None) -> str:
    """The survey with TA-Lib's wheel moved off the pinned line, owned or not.

    One helper rather than two nearly identical chains of replacements, because
    the difference between the two tests is exactly the ``resolved_by`` line and
    that is what a reader should be able to see.
    """
    ownership = "" if owner is None else f"resolved_by = {owner}\n"
    return SURVEY.replace(TA_LIB_WHEEL, '"ta_lib-0.7.1-cp313-cp313-win_amd64.whl"').replace(
        TA_LIB_VERDICT,
        f'verdict = "source-only"\n{ownership}source = "https://pypi.org/pypi/ta-lib/json"',
    )


def test_a_gap_belonging_to_nobody_fails(tmp_path: Path, reports: Path) -> None:
    """The one availability failure that is this gate's business.

    A library with no wheel is a fact about the world. A library with no wheel and
    nobody answering for it is a fact about this repository.
    """
    root = build_tree(tmp_path / "tree", survey=survey_with_a_gap(owner=None))
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    recorded = reasons_of(read_manifest(reports))
    assert manifest.REASON_WHEEL_UNAVAILABLE in recorded
    assert manifest.REASON_PHASE_MISPLACED in recorded


def test_a_gap_owned_by_a_future_phase_passes_and_is_recorded(
    tmp_path: Path, reports: Path
) -> None:
    root = build_tree(tmp_path / "tree", survey=survey_with_a_gap(owner=25))
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_OK


def test_one_distribution_surveyed_twice_is_reported(tmp_path: Path, reports: Path) -> None:
    doubled = SURVEY + SURVEY[SURVEY.index("[[library]]") :]
    root = build_tree(tmp_path / "tree", survey=doubled)
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_LIBRARY_DUPLICATED in reasons_of(read_manifest(reports))


def test_an_entry_scheduled_by_a_delivered_phase_is_reported(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree", survey=SURVEY.replace("phase = 211", "phase = 4"))
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_PHASE_MISPLACED in reasons_of(read_manifest(reports))


# ---------------------------------------------------------------------------
# The free-threaded second verdict
# ---------------------------------------------------------------------------


def test_the_free_threaded_cost_is_reported_without_failing(tmp_path: Path, reports: Path) -> None:
    """ADR-0050 refused the free-threaded build.

    A gap there is that refusal being correct, not something going wrong, so the
    gate names the blockers and passes. Failing would make the gate red for
    holding the position the project deliberately holds.
    """
    root = build_tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_OK
    entry = findings_of(read_manifest(reports))["free_threaded"]
    assert isinstance(entry, Mapping)
    assert entry["verdict"] == "passed"
    assert entry["blocked"] == ["ta-lib"]


def test_a_survey_already_targeting_a_free_threaded_build_has_no_twin(
    tmp_path: Path, reports: Path
) -> None:
    """The comparison has nothing to say, and says so rather than inventing an answer."""
    survey = SURVEY.replace("free_threaded = false", "free_threaded = true")
    contract = CONTRACT.replace("free_threaded = false", "free_threaded = true")
    root = build_tree(tmp_path / "tree", survey=survey, contract=contract)
    gate.run_wheels(root=root, reports=reports)
    entry = findings_of(read_manifest(reports))["free_threaded"]
    assert isinstance(entry, Mapping)
    assert entry["verdict"] == "passed"
    assert "detail" in entry


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


def index_document(*, version: str, requires: str, filenames: tuple[str, ...]) -> str:
    """What the index returns for one distribution."""
    return json.dumps(
        {
            "info": {"version": version, "requires_python": requires},
            "urls": [{"filename": name} for name in filenames],
        }
    )


def agreeing_fetcher(url: str, *, timeout: float = 0.0) -> str:
    """An index that still says what the record says."""
    del timeout
    if "optuna" in url:
        return index_document(
            version="4.9.0", requires=">=3.9", filenames=("optuna-4.9.0-py3-none-any.whl",)
        )
    return index_document(
        version="0.7.1", requires=">=3.9", filenames=("ta_lib-0.7.1-cp314-cp314-win_amd64.whl",)
    )


def test_a_probe_that_agrees_with_the_record_passes(tmp_path: Path, reports: Path) -> None:
    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=agreeing_fetcher)
    assert result == gate.EXIT_OK
    document = read_manifest(reports)
    run = document["run"]
    assert isinstance(run, Mapping)
    assert run["mode"] == "probe"
    entry = findings_of(document)["index"]
    assert isinstance(entry, Mapping)
    assert entry["verdict"] == "passed"


def test_a_check_run_asks_the_index_nothing(tmp_path: Path, reports: Path) -> None:
    """The offline gate must not acquire a network dependency by accident."""

    def refuse(url: str, *, timeout: float = 0.0) -> str:
        del timeout
        message = f"the offline gate reached {url}"
        raise AssertionError(message)

    root = build_tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports, fetcher=refuse) == gate.EXIT_OK
    assert "index" not in findings_of(read_manifest(reports))


def test_a_newer_version_on_the_index_is_drift(tmp_path: Path, reports: Path) -> None:
    def moved(url: str, *, timeout: float = 0.0) -> str:
        del timeout
        if "optuna" in url:
            return index_document(
                version="5.0.0", requires=">=3.9", filenames=("optuna-5.0.0-py3-none-any.whl",)
            )
        return agreeing_fetcher(url)

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=moved)
    assert result == gate.EXIT_GATE_FAILED
    assert manifest.REASON_INDEX_DIVERGED in reasons_of(read_manifest(reports))


def test_a_changed_requires_python_is_drift(tmp_path: Path, reports: Path) -> None:
    """The bound that matters most here is an upper one.

    Every ``binance-sdk-*`` distribution caps at ``<3.15``, so a cap tightening to
    exclude the pinned line is exactly what this check exists to notice.
    """

    def tightened(url: str, *, timeout: float = 0.0) -> str:
        del timeout
        if "optuna" in url:
            return index_document(
                version="4.9.0",
                requires="<3.14,>=3.9",
                filenames=("optuna-4.9.0-py3-none-any.whl",),
            )
        return agreeing_fetcher(url)

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=tightened)
    assert result == gate.EXIT_GATE_FAILED
    assert manifest.REASON_INDEX_DIVERGED in reasons_of(read_manifest(reports))


def test_a_recorded_wheel_the_index_no_longer_publishes_is_drift(
    tmp_path: Path, reports: Path
) -> None:
    def withdrawn(url: str, *, timeout: float = 0.0) -> str:
        del timeout
        if "optuna" in url:
            return index_document(version="4.9.0", requires=">=3.9", filenames=())
        return agreeing_fetcher(url)

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=withdrawn)
    assert result == gate.EXIT_GATE_FAILED
    assert manifest.REASON_INDEX_DIVERGED in reasons_of(read_manifest(reports))


def test_an_index_that_cannot_be_reached_is_unmeasured_rather_than_passed(
    tmp_path: Path, reports: Path
) -> None:
    """Having looked and found nothing is not the same as not having looked.

    The two outcomes are indistinguishable from a distance, which is why
    ``docs/DEPENDENCY_POLICY.md`` gives each its own name. An unmeasured run exits
    3, which is never a pass.
    """

    def unreachable(url: str, *, timeout: float = 0.0) -> str:
        del timeout, url
        message = "no route to host"
        raise OSError(message)

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=unreachable)
    assert result == gate.EXIT_UNMEASURED
    assert manifest.REASON_INDEX_UNREACHABLE in reasons_of(read_manifest(reports))


def test_an_index_returning_something_that_is_not_the_expected_json_is_unmeasured(
    tmp_path: Path, reports: Path
) -> None:
    def nonsense(url: str, *, timeout: float = 0.0) -> str:
        del timeout, url
        return "<html>maintenance</html>"

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=nonsense)
    assert result == gate.EXIT_UNMEASURED
    assert manifest.REASON_INDEX_UNREACHABLE in reasons_of(read_manifest(reports))


def test_json_missing_the_keys_the_probe_needs_is_unmeasured(tmp_path: Path, reports: Path) -> None:
    def partial(url: str, *, timeout: float = 0.0) -> str:
        del timeout, url
        return json.dumps({"info": {"version": "4.9.0"}})

    root = build_tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=partial)
    assert result == gate.EXIT_UNMEASURED


# ---------------------------------------------------------------------------
# The fetcher itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["http://pypi.org/pypi/optuna/json", "file:///etc/passwd", "ftp://example.invalid/x"]
)
def test_the_fetcher_opens_https_and_nothing_else(url: str) -> None:
    """The URLs come from a file in this repository, which makes them ours.

    But a survey that could be pointed at the local disk by editing a TOML string
    is a survey whose evidence means less than it appears to. Refusing the scheme
    is also what keeps this test offline: nothing reaches a socket.
    """
    with pytest.raises(Exception, match="https"):
        gate.fetch(url)


# ---------------------------------------------------------------------------
# Reading this repository's own declaration
# ---------------------------------------------------------------------------


def test_the_declaration_helper_reads_a_tree(tmp_path: Path) -> None:
    root = build_tree(tmp_path / "tree")
    declaration = gate.declaration_of(root)
    assert [entry.name for entry in declaration.libraries] == ["optuna", "ta-lib"]


def test_the_declaration_helper_refuses_a_tree_without_one(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Exception, match="could not be read"):
        gate.declaration_of(empty)


# ---------------------------------------------------------------------------
# The observation and failure paths a passing run never reaches
# ---------------------------------------------------------------------------


def test_a_commit_is_read_through_a_symbolic_reference(tmp_path: Path, reports: Path) -> None:
    """The shape a real checkout has, and the one the other tests do not use.

    ``.git/HEAD`` normally holds ``ref: refs/heads/master`` rather than a SHA, so
    the branch that follows the reference is the branch that runs everywhere
    except in these tests.
    """
    root = build_tree(tmp_path / "tree")
    head = root / ".git" / "HEAD"
    head.write_text("ref: refs/heads/master\n", encoding="utf-8")
    branch = root / ".git" / "refs" / "heads"
    branch.mkdir(parents=True)
    (branch / "master").write_text("c" * 40, encoding="utf-8")

    gate.run_wheels(root=root, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, Mapping)
    assert run["commit"] == "c" * 40


def test_a_reference_pointing_at_nothing_is_recorded_as_unknown(
    tmp_path: Path, reports: Path
) -> None:
    root = build_tree(tmp_path / "tree")
    (root / ".git" / "HEAD").write_text("ref: refs/heads/gone\n", encoding="utf-8")
    gate.run_wheels(root=root, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, Mapping)
    assert run["commit"] == "unknown"


def test_a_head_holding_something_that_is_not_a_sha_is_recorded_as_unknown(
    tmp_path: Path, reports: Path
) -> None:
    root = build_tree(tmp_path / "tree")
    (root / ".git" / "HEAD").write_text("half-a-sha\n", encoding="utf-8")
    gate.run_wheels(root=root, reports=reports)
    run = read_manifest(reports)["run"]
    assert isinstance(run, Mapping)
    assert run["commit"] == "unknown"


def test_an_unparseable_filename_is_reported_by_the_availability_check(
    tmp_path: Path, reports: Path
) -> None:
    """A judgement returns findings; it does not blow up the run."""
    survey = SURVEY.replace('"optuna-4.9.0-py3-none-any.whl"', '"not-a-wheel-filename"')
    root = build_tree(tmp_path / "tree", survey=survey)
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED


def test_a_manifest_that_renders_differently_twice_fails_rather_than_being_written(
    tmp_path: Path, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism is checked rather than asserted, so the check itself is checked.

    A guard nothing ever exercises is a guard nobody knows is inverted.
    """
    calls = {"n": 0}

    def drifting(**keywords: object) -> dict[str, object]:
        calls["n"] += 1
        document = build_manifest(**keywords)  # type: ignore[arg-type]
        if calls["n"] == 2:
            document["phase"] = 999
        return document

    monkeypatch.setattr(gate, "build_manifest", drifting)
    root = build_tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_MANIFEST_NONDETERMINISTIC in reasons_of(read_manifest(reports))


def test_a_manifest_carrying_a_home_directory_path_is_refused_rather_than_written(
    tmp_path: Path, reports: Path
) -> None:
    """The manifest is uploaded as a public-repository artifact.

    Every absolute path on the development host carries the account holder's name,
    so a value that reaches the document from the declaration is scanned rather
    than trusted.
    """
    survey = SURVEY.replace(
        'index = "https://pypi.org/pypi/"', 'index = "https://pypi.org/C:/Users/someone/"'
    )
    root = build_tree(tmp_path / "tree", survey=survey)
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_MANIFEST_LEAKAGE in reasons_of(read_manifest(reports))


def test_an_entry_that_is_not_a_finding_is_unmeasured_rather_than_assumed() -> None:
    assert _verdict_of("not a finding") is Verdict.UNMEASURED
    assert _verdict_of({"verdict": "invented"}) is Verdict.UNMEASURED
    assert _verdict_of(_finding(())) is Verdict.PASSED
    assert _verdict_of(_finding(("wrong",))) is Verdict.FAILED
    assert _verdict_of(_finding((), measured=False)) is Verdict.UNMEASURED


def test_the_report_skips_a_section_that_is_not_a_finding(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Printing must not raise on a section shaped differently from the rest.

    A gate that crashed while explaining itself would turn a finding into a
    traceback.
    """
    _report({"real": _finding(("wrong",)), "odd": "not a mapping"}, Verdict.FAILED, ["R"])
    printed = capsys.readouterr().out
    assert "wheels: real: failed" in printed
    assert "odd" not in printed
    assert "wheels: reasons R" in printed
