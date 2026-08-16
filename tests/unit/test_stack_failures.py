"""The stack gate's paths a healthy tree never reaches.

Error handling nobody exercises is error handling nobody has checked, and these
branches fire exactly when somebody is already having a bad day: a tree with no
Git, an unparsable runtime contract, a library that will not import, a manifest
that cannot be written. Each must produce a sentence rather than a traceback.

Kept apart from `test_stack_gate.py` for the reason the runtime-state failure
tests are kept apart from theirs: mixing them would make the failure paths read
as the normal ones.
"""

import json
from pathlib import Path

import pytest

from tests.support import REPO_ROOT
from tests.unit.test_stack_gate import DECLARATION, LOCK, MANIFEST, measurer, prober
from tools.quality.execution.plan import Verdict
from tools.quality.stack import cli
from tools.quality.stack.gate import (
    EXIT_GATE_FAILED,
    EXIT_UNMEASURED,
    MANIFEST_NAME,
    OUTPUT_DIRECTORY,
    _sha,
    _verdict_of,
    declaration_of,
    run_stack,
)
from tools.quality.stack.manifest import REASON_MANIFEST_LEAKAGE, REASON_REGISTRY_INCONSISTENT
from tools.quality.stack.plan import Library, StackError, missing_value_problems
from tools.quality.stack.probes import ProbeError, measure, run


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository whose four registers agree about both libraries."""
    (tmp_path / "docs" / "engineering").mkdir(parents=True)
    (tmp_path / "docs" / "engineering" / "stack-contract.toml").write_text(
        DECLARATION, encoding="utf-8"
    )
    (tmp_path / "docs" / "engineering" / "runtime-contract.toml").write_text(
        (REPO_ROOT / "docs" / "engineering" / "runtime-contract.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "pylock.toml").write_text(LOCK, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(MANIFEST, encoding="utf-8")
    return tmp_path


def reasons_of(tree: Path) -> list[str]:
    """The reason codes the manifest recorded."""
    document = json.loads((tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_text(encoding="utf-8"))
    return list(document["verdict"]["reasons"])


# ---------------------------------------------------------------------------
# Reading the commit
# ---------------------------------------------------------------------------


def test_a_tree_with_no_git_records_the_commit_as_unknown(tmp_path: Path) -> None:
    """A manifest can be produced where Git is not on the path, and says so."""
    assert _sha(tmp_path) == "unknown"


def test_a_detached_head_is_read_directly(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("a" * 40, encoding="utf-8")
    assert _sha(tmp_path) == "a" * 40


def test_a_head_that_is_neither_a_ref_nor_an_object_name_is_unknown(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("not an object name", encoding="utf-8")
    assert _sha(tmp_path) == "unknown"


def test_a_dangling_reference_is_unknown_rather_than_an_exception(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/gone", encoding="utf-8")
    assert _sha(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# Declarations and contracts that cannot be read
# ---------------------------------------------------------------------------


def test_an_unparsable_runtime_contract_is_a_target_failure(tree: Path) -> None:
    """Distinct from a missing one, and from a target that merely diverges."""
    (tree / "docs" / "engineering" / "runtime-contract.toml").write_text(
        "schema = 1\n", encoding="utf-8"
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert "could not be parsed" in (tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_text(
        encoding="utf-8"
    )


def test_reading_a_declaration_from_a_tree_without_one_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(StackError, match="could not be read"):
        declaration_of(tmp_path)


def test_a_registry_that_does_not_agree_is_refused(tree: Path) -> None:
    """A probe declared with nothing implementing it is a claim nobody checks."""
    declaration = tree / "docs" / "engineering" / "stack-contract.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + '\n[[probe]]\nid = "numpy.invented"\nbecause = "nothing implements this"\n',
        encoding="utf-8",
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_REGISTRY_INCONSISTENT in reasons_of(tree)


# ---------------------------------------------------------------------------
# The leak gate
# ---------------------------------------------------------------------------


def test_a_manifest_carrying_something_secret_shaped_is_refused_rather_than_written(
    tree: Path,
) -> None:
    """The last check before anything is published.

    It is also the only one that can fail on content the gate itself assembled.
    Reached by measuring a wheel tag carrying a URL with credentials in it, which
    is a shape the scanner recognises and a shape a real leak takes: a value from
    the environment reaching the evidence unnoticed.
    """
    leaky = {
        "numpy": ("2.5.2", "https://someone:hunter2@internal.example/simple"),
        "pandas": ("3.0.5", "cp314-cp314-win_amd64"),
    }
    assert run_stack(root=tree, measurer=measurer(leaky), prober=prober()) == EXIT_GATE_FAILED
    assert reasons_of(tree) == [REASON_MANIFEST_LEAKAGE]
    assert "hunter2" not in (tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reducing findings to a verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param({"verdict": "passed"}, Verdict.PASSED, id="a passing finding"),
        pytest.param({"verdict": "failed"}, Verdict.FAILED, id="a failing finding"),
        pytest.param({"verdict": "invented"}, Verdict.UNMEASURED, id="a verdict nobody declared"),
        pytest.param("not a mapping", Verdict.UNMEASURED, id="not a finding at all"),
        pytest.param({"a": {"verdict": "failed"}}, Verdict.FAILED, id="nested findings"),
        pytest.param({"numpy": {"installed": "2.5.2"}}, Verdict.PASSED, id="the observed section"),
    ],
)
def test_a_finding_is_reduced_to_the_verdict_it_carries(entry: object, expected: Verdict) -> None:
    """The observed section is data rather than a check.

    It carries no verdict of its own, and reading it as unmeasured would make
    every run unmeasured — which is why it reduces to passed rather than to the
    default.
    """
    assert _verdict_of(entry) is expected


# ---------------------------------------------------------------------------
# Measuring a library that will not cooperate
# ---------------------------------------------------------------------------


def test_a_distribution_whose_wheel_record_cannot_be_read_still_measures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source install legitimately has no `WHEEL` file.

    Reported as absent provenance rather than as a failure to measure anything.
    """
    from importlib.metadata import PathDistribution

    real = PathDistribution.read_text

    def refuse(self: PathDistribution, name: str) -> str | None:
        # Only the WHEEL read fails. Failing every read would break the version
        # lookup too, and then this would be testing something else.
        if name == "WHEEL":
            msg = "the metadata could not be read"
            raise OSError(msg)
        return real(self, name)

    monkeypatch.setattr(PathDistribution, "read_text", refuse)
    facts = measure(
        Library(
            name="pytest",
            import_name="pytest",
            version="0.0.0",
            wheel_tag="none",
            role="a distribution that is certainly installed",
            probes=(),
        )
    )
    assert facts.wheel_tag is None
    assert facts.installed is not None


def test_a_module_name_that_cannot_be_looked_up_reads_as_absent() -> None:
    """`find_spec` raises rather than returning `None` for some malformed names."""
    facts = measure(
        Library(
            name="pytest",
            import_name="not..a..module",
            version="0.0.0",
            wheel_tag="none",
            role="a name the import machinery refuses",
            probes=(),
        )
    )
    assert facts.module_location is None


def test_a_probe_whose_library_will_not_import_is_a_probe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turned into an unmeasured finding by the gate, never into a failed one."""

    def refuse() -> tuple[str, ...]:
        msg = "No module named 'numpy'"
        raise ImportError(msg)

    monkeypatch.setattr(
        "tools.quality.stack.probes.registry",
        lambda: {"numpy.float64_is_binary64": refuse},
    )
    with pytest.raises(ProbeError, match="could not run"):
        run("numpy.float64_is_binary64")


# ---------------------------------------------------------------------------
# The command line's own failure path
# ---------------------------------------------------------------------------


def test_a_manifest_that_cannot_be_written_is_unmeasured_rather_than_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not knowing is a different answer from knowing something is broken.

    The gate could not report on the stack at all, which ADR-0045 makes
    unmeasured rather than a failure.
    """

    def refuse() -> int:
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr("tools.quality.stack.cli.run_stack", refuse)
    assert cli.main([]) == EXIT_UNMEASURED
    assert "could not be written" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Two judgements a healthy stack never reaches
# ---------------------------------------------------------------------------


def test_a_missing_value_that_survived_in_the_wrong_dtype_is_still_refused() -> None:
    """Both halves of the probe matter: where it is, and what type it came back as."""
    problems = missing_value_problems(missing_positions=[1], dtype="object")
    assert len(problems) == 1
    assert "object" in problems[0]


def test_a_version_with_a_non_numeric_component_compares_on_what_precedes_it() -> None:
    """A release candidate is ordered by its release part and no further.

    Deliberately not a PEP 440 implementation — that needs `packaging`, and what
    this reads are versions GLOBIN itself pinned.
    """
    from tools.quality.stack.plan import _version_key

    assert _version_key("2.5.2rc1") == (2, 5)
    assert _version_key("2.5.2") > _version_key("2.5.1")
