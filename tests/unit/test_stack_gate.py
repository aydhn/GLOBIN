"""The stack gate's sequencing, against synthetic trees.

Every test here builds a repository in `tmp_path` and points the gate at it, so
nothing depends on the state of the real checkout and nothing writes into it.

**The measurer and the prober are injected, and that is the design being
tested.** Proving that a wrong `numpy` is refused would otherwise require owning a
wrong `numpy`. Substituting the measurement is what lets every failing branch be
reached on a host where everything is fine — the same seam
`tools/quality/wheels/gate.py` uses for its index fetcher, and for the same
reason.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support import REPO_ROOT
from tools.quality.stack.gate import (
    EXIT_GATE_FAILED,
    EXIT_OK,
    MANIFEST_NAME,
    OUTPUT_DIRECTORY,
    declared_bounds,
    locked_versions,
    run_stack,
)
from tools.quality.stack.manifest import (
    REASON_DECLARATION_UNREADABLE,
    REASON_DEFERRAL_MISPLACED,
    REASON_LIBRARY_DUPLICATED,
    REASON_LIBRARY_UNCHECKED,
    REASON_LIBRARY_UNIMPORTABLE,
    REASON_PROBE_FAILED,
    REASON_PROVENANCE_DIVERGED,
    REASON_REGISTRY_INCONSISTENT,
    REASON_TARGET_DIVERGED,
    REASON_VERSION_DIVERGED,
)
from tools.quality.stack.plan import Library
from tools.quality.stack.probes import LibraryFacts, ProbeError

DECLARATION = """
schema = 1

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"

[[library]]
name = "numpy"
import_name = "numpy"
version = "2.5.2"
wheel_tag = "cp314-cp314-win_amd64"
role = "the numerical half"
probes = [
    "numpy.float64_is_binary64",
    "numpy.nan_and_infinity_propagate",
    "numpy.integer_overflow_wraps_observably",
]

[[library]]
name = "pandas"
import_name = "pandas"
version = "3.0.5"
wheel_tag = "cp314-cp314-win_amd64"
role = "the dataframe half"
probes = [
    "pandas.float64_round_trip_is_bit_exact",
    "pandas.missing_value_survives_a_round_trip",
    "pandas.utc_timestamp_round_trip_preserves_the_instant",
    "pandas.copy_on_write_is_active",
]

[[library]]
name = "ta-lib"
import_name = "talib"
version = "0.7.1"
wheel_tag = "cp314-cp314-win_amd64"
role = "the indicator half"
probes = [
    "talib.native_library_is_carried_by_the_wheel",
    "talib.indicator_table_is_complete",
    "talib.moving_average_warmup_is_the_documented_length",
]

[[probe]]
id = "numpy.float64_is_binary64"
because = "PRECISION_POLICY.md defines the approximate regime in these terms"

[[probe]]
id = "numpy.nan_and_infinity_propagate"
because = "a substituted finite value is a plausible number"

[[probe]]
id = "numpy.integer_overflow_wraps_observably"
because = "a silent wrap cannot be told from a correct result"

[[probe]]
id = "pandas.float64_round_trip_is_bit_exact"
because = "a frame that altered a float would break reproducibility"

[[probe]]
id = "pandas.missing_value_survives_a_round_trip"
because = "a missing value becoming zero is a quiet corruption"

[[probe]]
id = "pandas.utc_timestamp_round_trip_preserves_the_instant"
because = "TIME_POLICY.md makes internal time UTC and aware"

[[probe]]
id = "pandas.copy_on_write_is_active"
because = "without it a slice can mutate its caller's data"

[[probe]]
id = "talib.native_library_is_carried_by_the_wheel"
because = "a wheel filename cannot say whether the native C library is inside it"

[[probe]]
id = "talib.indicator_table_is_complete"
because = "a partially linked library still answers with its version"

[[probe]]
id = "talib.moving_average_warmup_is_the_documented_length"
because = "an indicator seeded one bar short is look-ahead arriving as a number"

[[deferral]]
question = "the indicator numeric type"
phase = 113
"""

LOCK = """
lock-version = "1.0"
created-by = "pip"

[[packages]]
name = "numpy"
version = "2.5.2"

[[packages.wheels]]
name = "numpy-2.5.2-cp314-cp314-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/aa/numpy-2.5.2-cp314-cp314-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "7587f53dfbd5edc0f7b87c6217b4c6d2d1f2ef9c3da70bc1315e7db5f8d7ec9d"

[[packages]]
name = "pandas"
version = "3.0.5"

[[packages.wheels]]
name = "pandas-3.0.5-cp314-cp314-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/bb/pandas-3.0.5-cp314-cp314-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "cd8f7c6dc98527058ee6264219343f5392240a6f1bfa654fc5d79023020d0c92"

[[packages]]
name = "ta-lib"
version = "0.7.1"

[[packages.wheels]]
name = "ta_lib-0.7.1-cp314-cp314-win_amd64.whl"
url = "https://files.pythonhosted.org/packages/cc/ta_lib-0.7.1-cp314-cp314-win_amd64.whl"

[packages.wheels.hashes]
sha256 = "3b1f9a6c2e4d7085a1c3f6e2b9d4708c5f2a1e6b3d8c407f9a2e5b1d6c3f8074"
"""

MANIFEST = """
[project]
name = "globin"
dependencies = [
    "numpy>=2.5.2",
    "pandas>=3.0.5",
    "ta-lib>=0.7.1",
]
"""

INSTALLED: dict[str, tuple[str, str]] = {
    "numpy": ("2.5.2", "cp314-cp314-win_amd64"),
    "pandas": ("3.0.5", "cp314-cp314-win_amd64"),
    "ta-lib": ("0.7.1", "cp314-cp314-win_amd64"),
}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repository whose four registers agree about all three libraries."""
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


def measurer(
    installed: dict[str, tuple[str, str]] | None = None,
) -> Callable[[Library], LibraryFacts]:
    """A measurer reporting whatever the caller says is installed."""
    present = INSTALLED if installed is None else installed

    def measure(library: Library) -> LibraryFacts:
        found = present.get(library.name)
        if found is None:
            return LibraryFacts(installed=None, wheel_tag=None, module_location=None)
        version, tag = found
        return LibraryFacts(
            installed=version,
            wheel_tag=tag,
            module_location=f"C:/environment/{library.import_name}/__init__.py",
        )

    return measure


def prober(
    failing: set[str] | None = None, unknown: set[str] | None = None
) -> Callable[[str], tuple[str, ...]]:
    """A prober that passes everything except the identifiers named."""
    broken = failing or set()
    missing = unknown or set()

    def probe(identifier: str) -> tuple[str, ...]:
        if identifier in missing:
            msg = f"{identifier} could not run: no module named its library"
            raise ProbeError(msg)
        return (f"{identifier} observed something else",) if identifier in broken else ()

    return probe


def manifest_of(tree: Path) -> dict[str, object]:
    """Read back the manifest the gate wrote."""
    document = json.loads((tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def reasons_of(tree: Path) -> list[str]:
    """The reason codes the manifest recorded."""
    verdict = manifest_of(tree)["verdict"]
    assert isinstance(verdict, dict)
    return list(verdict["reasons"])


# ---------------------------------------------------------------------------
# The passing run
# ---------------------------------------------------------------------------


def test_a_coherent_tree_passes_and_writes_its_evidence(tree: Path) -> None:
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_OK
    document = manifest_of(tree)
    assert document["phase"] == 22
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "passed"
    assert verdict["reasons"] == []


def test_the_manifest_records_every_probe_separately(tree: Path) -> None:
    """A bare `probes failed` would answer a question nobody has.

    A reader opens this file to learn *which* assumption stopped holding.
    """
    run_stack(root=tree, measurer=measurer(), prober=prober())
    findings = manifest_of(tree)["findings"]
    assert isinstance(findings, dict)
    probes = findings["probes"]
    assert isinstance(probes, dict)
    assert len(probes) == 10
    assert probes["pandas.copy_on_write_is_active"]["verdict"] == "passed"


def test_the_manifest_records_no_absolute_path_and_no_clock_reading(tree: Path) -> None:
    """This file is published as a public-repository artifact.

    Every absolute path on a development host carries the account holder's name,
    and a wall-clock reading would make two renderings of one run disagree.
    """
    run_stack(root=tree, measurer=measurer(), prober=prober())
    rendered = (tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tree) not in rendered
    assert "C:/environment" not in rendered


def test_two_runs_of_one_tree_produce_identical_bytes(tree: Path) -> None:
    """Determinism is checked by the gate; this checks the check is worth having."""
    run_stack(root=tree, measurer=measurer(), prober=prober())
    first = (tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_bytes()
    run_stack(root=tree, measurer=measurer(), prober=prober())
    assert (tree / OUTPUT_DIRECTORY / MANIFEST_NAME).read_bytes() == first


# ---------------------------------------------------------------------------
# The failing runs, one cause at a time
# ---------------------------------------------------------------------------


def test_an_unreadable_declaration_still_writes_a_manifest(tmp_path: Path) -> None:
    """A gate that leaves no artefact cannot be told from one that never ran.

    So a run that could not even read its own declaration still writes evidence
    saying exactly that.
    """
    assert run_stack(root=tmp_path, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert reasons_of(tmp_path) == [REASON_DECLARATION_UNREADABLE]


def test_a_malformed_declaration_is_refused_by_name(tree: Path) -> None:
    (tree / "docs" / "engineering" / "stack-contract.toml").write_text(
        "[unterminated", encoding="utf-8"
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert reasons_of(tree) == [REASON_DECLARATION_UNREADABLE]


def test_a_missing_runtime_contract_is_a_target_failure(tree: Path) -> None:
    (tree / "docs" / "engineering" / "runtime-contract.toml").unlink()
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert reasons_of(tree) == [REASON_TARGET_DIVERGED]


def test_a_target_the_runtime_contract_does_not_declare_is_refused(tree: Path) -> None:
    declaration = (tree / "docs" / "engineering" / "stack-contract.toml").read_text(
        encoding="utf-8"
    )
    (tree / "docs" / "engineering" / "stack-contract.toml").write_text(
        declaration.replace('minor_line = "3.14"', 'minor_line = "3.13"'), encoding="utf-8"
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_TARGET_DIVERGED in reasons_of(tree)


def test_a_library_that_is_not_installed_is_refused(tree: Path) -> None:
    installed = {"numpy": INSTALLED["numpy"]}
    assert run_stack(root=tree, measurer=measurer(installed), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_VERSION_DIVERGED in reasons_of(tree)
    assert REASON_LIBRARY_UNIMPORTABLE in reasons_of(tree)


def test_an_installed_version_the_lock_does_not_pin_is_refused(tree: Path) -> None:
    installed = dict(INSTALLED)
    installed["numpy"] = ("2.5.1", "cp314-cp314-win_amd64")
    assert run_stack(root=tree, measurer=measurer(installed), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_VERSION_DIVERGED in reasons_of(tree)


def test_a_wheel_built_for_another_abi_is_refused(tree: Path) -> None:
    """The free-threaded build installs cleanly and the lock says nothing about it."""
    installed = dict(INSTALLED)
    installed["pandas"] = ("3.0.5", "cp314-cp314t-win_amd64")
    assert run_stack(root=tree, measurer=measurer(installed), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_PROVENANCE_DIVERGED in reasons_of(tree)


def test_a_failing_probe_is_refused_and_named(tree: Path) -> None:
    failing = {"pandas.copy_on_write_is_active"}
    assert run_stack(root=tree, measurer=measurer(), prober=prober(failing)) == EXIT_GATE_FAILED
    assert REASON_PROBE_FAILED in reasons_of(tree)
    findings = manifest_of(tree)["findings"]
    assert isinstance(findings, dict)
    probes = findings["probes"]
    assert isinstance(probes, dict)
    assert probes["pandas.copy_on_write_is_active"]["verdict"] == "failed"
    assert probes["numpy.float64_is_binary64"]["verdict"] == "passed"


def test_a_probe_that_could_not_run_is_unmeasured_rather_than_failed(tree: Path) -> None:
    """Not knowing is a different answer from knowing something is broken.

    ADR-0045's rule, applied to a probe whose library would not import.
    """
    unknown = {"numpy.float64_is_binary64"}
    run_stack(root=tree, measurer=measurer(), prober=prober(unknown=unknown))
    findings = manifest_of(tree)["findings"]
    assert isinstance(findings, dict)
    probes = findings["probes"]
    assert isinstance(probes, dict)
    assert probes["numpy.float64_is_binary64"]["verdict"] == "unmeasured"
    assert REASON_LIBRARY_UNIMPORTABLE in reasons_of(tree)


def test_a_library_declared_twice_is_refused(tree: Path) -> None:
    declaration = (tree / "docs" / "engineering" / "stack-contract.toml").read_text(
        encoding="utf-8"
    )
    duplicate = declaration.split("[[probe]]", maxsplit=1)[0]
    extra = duplicate.split("[[library]]", maxsplit=2)[1]
    (tree / "docs" / "engineering" / "stack-contract.toml").write_text(
        declaration.replace("[[probe]]", "[[library]]" + extra + "[[probe]]", 1), encoding="utf-8"
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_LIBRARY_DUPLICATED in reasons_of(tree)


def test_a_library_with_no_probe_is_refused(tree: Path) -> None:
    declaration = (tree / "docs" / "engineering" / "stack-contract.toml").read_text(
        encoding="utf-8"
    )
    (tree / "docs" / "engineering" / "stack-contract.toml").write_text(
        declaration.replace(
            """probes = [
    "numpy.float64_is_binary64",
    "numpy.nan_and_infinity_propagate",
    "numpy.integer_overflow_wraps_observably",
]""",
            "probes = []",
        ),
        encoding="utf-8",
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    reasons = reasons_of(tree)
    assert REASON_LIBRARY_UNCHECKED in reasons
    # And ONLY that. The three numpy probes are still declared in the probe table
    # and still implemented, so the registry genuinely does agree with itself --
    # the two checks answer different questions and must not collapse into one.
    assert REASON_REGISTRY_INCONSISTENT not in reasons


def test_a_deferral_naming_a_delivered_phase_is_refused(tree: Path) -> None:
    declaration = (tree / "docs" / "engineering" / "stack-contract.toml").read_text(
        encoding="utf-8"
    )
    (tree / "docs" / "engineering" / "stack-contract.toml").write_text(
        declaration.replace("phase = 113", "phase = 18"), encoding="utf-8"
    )
    assert run_stack(root=tree, measurer=measurer(), prober=prober()) == EXIT_GATE_FAILED
    assert REASON_DEFERRAL_MISPLACED in reasons_of(tree)


# ---------------------------------------------------------------------------
# The two register readers
# ---------------------------------------------------------------------------


def test_the_lock_reader_returns_every_pinned_version(tree: Path) -> None:
    assert locked_versions(tree) == {"numpy": "2.5.2", "pandas": "3.0.5", "ta-lib": "0.7.1"}


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        pytest.param(None, "no lock at all", id="absent"),
        pytest.param("[unterminated", "a lock that is not TOML", id="malformed"),
        pytest.param(
            'lock-version = "9.0"\ncreated-by = "pip"\n', "an unknown format", id="future"
        ),
    ],
)
def test_an_unusable_lock_reads_as_empty_rather_than_raising(
    tree: Path, content: str | None, reason: str
) -> None:
    """Reported per library by `version_problems`, rather than as one opaque failure.

    "pylock.toml pins no version for numpy" tells an operator what to do;
    "the lock could not be read" makes them guess which library was affected.
    """
    if content is None:
        (tree / "pylock.toml").unlink()
    else:
        (tree / "pylock.toml").write_text(content, encoding="utf-8")
    assert locked_versions(tree) == {}, reason


def test_the_manifest_reader_returns_every_declared_bound(tree: Path) -> None:
    assert declared_bounds(tree) == {
        "numpy": ">=2.5.2",
        "pandas": ">=3.0.5",
        "ta-lib": ">=0.7.1",
    }


def test_a_dependency_with_no_specifier_maps_to_an_empty_bound(tree: Path) -> None:
    """Reported as a form the gate cannot read, not as a satisfied bound."""
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "globin"\ndependencies = ["numpy"]\n', encoding="utf-8"
    )
    assert declared_bounds(tree) == {"numpy": ""}


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        pytest.param(None, "no manifest", id="absent"),
        pytest.param("[unterminated", "not TOML", id="malformed"),
        pytest.param("tool = {}\n", "no project table", id="no project"),
        pytest.param('[project]\nname = "globin"\n', "no dependencies key", id="no dependencies"),
        pytest.param('[project]\ndependencies = "numpy"\n', "dependencies not a list", id="scalar"),
        pytest.param("[project]\ndependencies = [1]\n", "a non-string entry", id="non-string"),
    ],
)
def test_an_unusable_manifest_reads_as_empty(tree: Path, content: str | None, reason: str) -> None:
    if content is None:
        (tree / "pyproject.toml").unlink()
    else:
        (tree / "pyproject.toml").write_text(content, encoding="utf-8")
    assert declared_bounds(tree) == {}, reason


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        pytest.param("numpy>=2.5.2", {"numpy": ">=2.5.2"}, id="a lower bound"),
        pytest.param("numpy [extra] >=2", {"numpy": "[extra] >=2"}, id="an extra"),
        pytest.param(
            "numpy; python_version>='3.12'", {"numpy": "; python_version>='3.12'"}, id="a marker"
        ),
        pytest.param("NumPy_Core", {"numpy-core": ""}, id="a name needing normalisation"),
    ],
)
def test_a_requirement_is_split_into_a_normalised_name_and_the_rest(
    tree: Path, requirement: str, expected: dict[str, str]
) -> None:
    """Deliberately shallow, for the reason the bootstrap's own reader gives.

    The moment this needs to be right about markers it needs `packaging`, and
    what it reads are requirements GLOBIN itself wrote.
    """
    (tree / "pyproject.toml").write_text(
        f'[project]\ndependencies = ["{requirement}"]\n', encoding="utf-8"
    )
    assert declared_bounds(tree) == expected
