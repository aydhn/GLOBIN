"""The wheel survey against a whole tree, correct and then deliberately broken.

The unit tests establish that each judgement reaches the right answer from values.
This establishes the things a pure test cannot see: that the gate reads the
*runtime contract* as well as its own declaration, that the two moving together is
what keeps the survey meaningful, and that the manifest it writes reads back
through its own loader with its digest intact.

**Two components, which is what makes this an integration test.** The survey
declares a target and Phase 017's contract declares an interpreter. Either can
change without the other, and the failure that matters is the one where a survey
quietly describes a line the project no longer runs.

**Every tree here is a temporary one**, and the index is a function returning a
string. A test that could only run against this repository would be a test unable
to describe a broken survey, which is most of what is worth asserting.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tools.quality.wheels import gate, manifest

CONTRACT = """\
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

TARGET = """\
schema = 1

[target]
implementation = "CPython"
minor_line = "3.14"
architecture = "AMD64"
platform_tag = "win_amd64"
free_threaded = false
index = "https://pypi.org/pypi/"
surveyed = 2026-08-16
"""

#: One entry of each wheel shape the real survey meets: a pure-Python wheel, an
#: ABI-bound extension that also publishes free-threaded, an ABI-bound extension
#: that does not, and a platform-specific interpreter-agnostic wheel.
LIBRARIES = """
[[library]]
name = "optuna"
phase = 211
version = "4.9.0"
requires_python = ">=3.9"
wheels = ["optuna-4.9.0-py3-none-any.whl"]
verdict = "available"
source = "https://pypi.org/pypi/optuna/json"
reason = "Pure Python; the study infrastructure Phase 211 establishes."

[[library]]
name = "numpy"
phase = 22
version = "2.5.2"
requires_python = ">=3.12"
wheels = [
    "numpy-2.5.2-cp314-cp314-win_amd64.whl",
    "numpy-2.5.2-cp314-cp314t-win_amd64.whl",
]
verdict = "available"
source = "https://pypi.org/pypi/numpy/json"
reason = "An extension publishing for both builds of the pinned line."

[[library]]
name = "ta-lib"
phase = 25
version = "0.7.1"
requires_python = ">=3.9"
wheels = ["ta_lib-0.7.1-cp314-cp314-win_amd64.whl"]
verdict = "available"
source = "https://pypi.org/pypi/ta-lib/json"
reason = "An extension publishing for the default build only."

[[library]]
name = "xgboost"
phase = 182
version = "3.4.1"
requires_python = ">=3.12"
wheels = ["xgboost-3.4.1-py3-none-win_amd64.whl"]
verdict = "available"
source = "https://pypi.org/pypi/xgboost/json"
reason = "Platform-specific and interpreter-agnostic; native code behind ctypes."

[[library]]
name = "binance-sdk-spot"
phase = 66
version = "11.1.0"
requires_python = "<3.15,>=3.10"
wheels = ["binance_sdk_spot-11.1.0-py3-none-any.whl"]
verdict = "available"
source = "https://pypi.org/pypi/binance-sdk-spot/json"
reason = "Pure Python, and the family that caps at an upper bound."
"""

SURVEY = TARGET + LIBRARIES

PUBLISHED: Mapping[str, tuple[str, str, tuple[str, ...]]] = {
    "optuna": ("4.9.0", ">=3.9", ("optuna-4.9.0-py3-none-any.whl",)),
    "numpy": (
        "2.5.2",
        ">=3.12",
        ("numpy-2.5.2-cp314-cp314-win_amd64.whl", "numpy-2.5.2-cp314-cp314t-win_amd64.whl"),
    ),
    "ta-lib": ("0.7.1", ">=3.9", ("ta_lib-0.7.1-cp314-cp314-win_amd64.whl",)),
    "xgboost": ("3.4.1", ">=3.12", ("xgboost-3.4.1-py3-none-win_amd64.whl",)),
    "binance-sdk-spot": (
        "11.1.0",
        "<3.15,>=3.10",
        ("binance_sdk_spot-11.1.0-py3-none-any.whl",),
    ),
}


def tree(root: Path, *, survey: str = SURVEY, contract: str = CONTRACT) -> Path:
    """A tree carrying both declarations the gate reads."""
    engineering = root / "docs" / "engineering"
    engineering.mkdir(parents=True)
    (engineering / "wheel-survey.toml").write_text(survey, encoding="utf-8")
    (engineering / "runtime-contract.toml").write_text(contract, encoding="utf-8")
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("b" * 40, encoding="utf-8")
    return root


def index(
    *, overrides: Mapping[str, tuple[str, str, tuple[str, ...]]] | None = None
) -> gate.Fetcher:
    """An index that publishes :data:`PUBLISHED`, with any entry replaced."""
    catalogue = dict(PUBLISHED)
    catalogue.update(overrides or {})

    def fetcher(url: str, *, timeout: float = 0.0) -> str:
        del timeout
        name = url.removeprefix("https://pypi.org/pypi/").removesuffix("/json")
        version, requires, filenames = catalogue[name]
        return json.dumps(
            {
                "info": {"version": version, "requires_python": requires},
                "urls": [{"filename": filename} for filename in filenames],
            }
        )

    return fetcher


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    """Where a run writes."""
    directory = tmp_path / "reports"
    directory.mkdir()
    return directory


def manifest_of(reports: Path) -> dict[str, object]:
    """What the gate wrote, read back through its own loader."""
    return manifest.load((reports / gate.MANIFEST_NAME).read_text(encoding="utf-8"))


def reasons(document: Mapping[str, object]) -> list[str]:
    """The reason codes recorded for a run."""
    verdict = document["verdict"]
    assert isinstance(verdict, Mapping)
    recorded = verdict["reasons"]
    assert isinstance(recorded, list)
    return [str(reason) for reason in recorded]


# ---------------------------------------------------------------------------
# A whole survey, offline and then against the index
# ---------------------------------------------------------------------------


def test_a_complete_survey_passes_offline(tmp_path: Path, reports: Path) -> None:
    root = tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_OK
    document = manifest_of(reports)
    assert reasons(document) == []
    run = document["run"]
    assert isinstance(run, Mapping)
    assert run["libraries"] == 5


def test_the_same_survey_passes_against_an_index_that_still_agrees(
    tmp_path: Path, reports: Path
) -> None:
    root = tree(tmp_path / "tree")
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=index())
    assert result == gate.EXIT_OK


def test_the_free_threaded_blocker_is_the_extension_that_publishes_one_abi(
    tmp_path: Path, reports: Path
) -> None:
    """The finding, over a set carrying every wheel shape.

    A pure wheel and an ABI-free platform wheel both serve a free-threaded build;
    an ABI-bound one serves only the build it was compiled for. Of the five here,
    exactly one blocks the change, and getting that number right is the whole
    difference between ADR-0050's refusal being evidenced and being asserted.
    """
    root = tree(tmp_path / "tree")
    gate.run_wheels(root=root, reports=reports)
    findings = manifest_of(reports)["findings"]
    assert isinstance(findings, Mapping)
    entry = findings["free_threaded"]
    assert isinstance(entry, Mapping)
    assert entry["blocked"] == ["ta-lib"]


# ---------------------------------------------------------------------------
# The two declarations moving apart
# ---------------------------------------------------------------------------


def test_moving_the_interpreter_without_resurveying_is_caught(
    tmp_path: Path, reports: Path
) -> None:
    """The failure this gate exists to prevent, in the direction it will arrive from.

    Somebody bumps the runtime contract; the survey still describes the old line
    and still passes its own internal checks, so nothing but this comparison
    notices that the evidence is about an interpreter the project no longer runs.
    """
    root = tree(tmp_path / "tree", contract=CONTRACT.replace('"3.14"', '"3.15"'))
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    assert manifest.REASON_TARGET_DIVERGED in reasons(manifest_of(reports))


def test_resurveying_for_the_moved_interpreter_reveals_what_the_move_would_cost(
    tmp_path: Path, reports: Path
) -> None:
    """Following the contract to 3.15 is not enough; the evidence has to follow too.

    The Binance SDK family caps at ``<3.15``, so a survey honestly conducted
    against that line reports the cap as excluding it. That is the finding ADR-0050
    would need before the pinned line could move, and it is why the pin is exact
    rather than a floor.
    """
    root = tree(
        tmp_path / "tree",
        survey=SURVEY.replace('minor_line = "3.14"', 'minor_line = "3.15"'),
        contract=CONTRACT.replace('"3.14"', '"3.15"'),
    )
    assert gate.run_wheels(root=root, reports=reports) == gate.EXIT_GATE_FAILED
    recorded = reasons(manifest_of(reports))
    assert manifest.REASON_TARGET_DIVERGED not in recorded
    assert manifest.REASON_RECORD_INCONSISTENT in recorded


# ---------------------------------------------------------------------------
# The index moving under the record
# ---------------------------------------------------------------------------


def test_a_cap_tightening_to_exclude_the_pinned_line_is_drift(
    tmp_path: Path, reports: Path
) -> None:
    root = tree(tmp_path / "tree")
    fetcher = index(
        overrides={
            "binance-sdk-spot": (
                "11.1.0",
                "<3.14,>=3.10",
                ("binance_sdk_spot-11.1.0-py3-none-any.whl",),
            )
        }
    )
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=fetcher)
    assert result == gate.EXIT_GATE_FAILED
    assert manifest.REASON_INDEX_DIVERGED in reasons(manifest_of(reports))


def test_a_release_the_survey_has_not_seen_is_drift_rather_than_a_failure(
    tmp_path: Path, reports: Path
) -> None:
    """A new upstream release is news, not a defect.

    It is reported so that somebody resurveys, which is the only way the record
    stays worth reading.
    """
    root = tree(tmp_path / "tree")
    fetcher = index(overrides={"optuna": ("5.0.0", ">=3.9", ("optuna-5.0.0-py3-none-any.whl",))})
    result = gate.run_wheels(root=root, reports=reports, probe=True, fetcher=fetcher)
    assert result == gate.EXIT_GATE_FAILED
    document = manifest_of(reports)
    assert manifest.REASON_INDEX_DIVERGED in reasons(document)
    findings = document["findings"]
    assert isinstance(findings, Mapping)
    entry = findings["index"]
    assert isinstance(entry, Mapping)
    problems = entry["problems"]
    assert isinstance(problems, list)
    assert any("5.0.0" in str(problem) for problem in problems)


def test_an_index_that_is_down_does_not_report_a_clean_survey(
    tmp_path: Path, reports: Path
) -> None:
    """Unmeasured outranks failed, and neither is a pass.

    A probe run on a day PyPI is unreachable must not exit zero, or the gate
    reports "nothing wrong" on the evidence of having looked at nothing.
    """

    def down(url: str, *, timeout: float = 0.0) -> str:
        del timeout, url
        message = "connection refused"
        raise OSError(message)

    root = tree(tmp_path / "tree")
    assert gate.run_wheels(root=root, reports=reports, probe=True, fetcher=down) != gate.EXIT_OK


# ---------------------------------------------------------------------------
# What the manifest is worth afterwards
# ---------------------------------------------------------------------------


def test_the_manifest_verifies_against_itself_after_every_kind_of_run(
    tmp_path: Path, reports: Path
) -> None:
    root = tree(tmp_path / "tree")

    gate.run_wheels(root=root, reports=reports)
    assert manifest_of(reports)["schema"] == manifest.SCHEMA

    gate.run_wheels(root=root, reports=reports, probe=True, fetcher=index())
    assert manifest_of(reports)["schema"] == manifest.SCHEMA


def test_a_manifest_edited_after_the_run_no_longer_verifies(tmp_path: Path, reports: Path) -> None:
    """The evidence is only worth something if changing it is detectable."""
    root = tree(tmp_path / "tree")
    gate.run_wheels(root=root, reports=reports)
    path = reports / gate.MANIFEST_NAME
    document = json.loads(path.read_text(encoding="utf-8"))
    document["verdict"]["verdict"] = "passed"
    document["findings"] = {}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(manifest.WheelManifestError):
        manifest_of(reports)
