"""Phase 014's own conditions, asserted against the tree.

Three groups.

*The manifest is evidence.* It announces a schema and a version, is sealed against
editing, and refuses a document from another schema — the same envelope contract
``docs/SERIALIZATION_POLICY.md`` states for everything else this repository reads
back.

*The registers agree with what exists.* `dependency-reviews.toml` against the
generated inventory, and the documented capability states against the ones the
code can actually produce. Two copies of a rule are drift rather than a tripwire
unless something compares them.

*The gate cannot be made to lie.* No failure mask anywhere in the package, no
network in the suite, and every reason code the gate can emit declared in a
closed set.
"""

import ast
import tomllib
from pathlib import Path
from typing import Final

import pytest

from tools.quality.commands import find
from tools.quality.supply import capability, manifest
from tools.quality.supply.inventory import PYPI, SupplyChainError, collect

REVIEWS: Final[str] = "docs/engineering/dependency-reviews.toml"
POLICY: Final[str] = "docs/DEPENDENCY_POLICY.md"

FAILURE_MASKS: Final[tuple[str, ...]] = ("continue-on-error: true", "|| true", "exit 0")
"""Ways to make a check report success it did not have.

Asserted absent from the supply package for the same reason
``test_ci_security_contract.py`` asserts them absent from the workflow: a gate
that cannot fail is decoration, and a *security* gate that cannot fail is worse
than none, because it is believed.
"""


def _executable(source: str) -> str:
    """One module's code with its docstrings and comments removed.

    Args:
        source: The module text.

    Returns:
        Only the lines that execute.

    Necessary because both checks below look for strings that legitimately appear
    in prose explaining why they are forbidden — ``audit.py``'s own docstring
    names ``pip-audit || true`` as the antipattern it exists to prevent. A rule
    that forbade its own explanation would be a rule somebody deletes.
    """
    tree = ast.parse(source)
    prose = {
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return "\n".join(
        line.split("#", maxsplit=1)[0]
        for number, line in enumerate(source.splitlines(), start=1)
        if not any(start <= number <= end for start, end in prose)
    )


@pytest.fixture(scope="module")
def package_sources(repo_root: Path) -> dict[str, str]:
    """Every module of the supply package, by name."""
    directory = repo_root / "tools" / "quality" / "supply"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.py"))}


@pytest.fixture(scope="module")
def reviews(repo_root: Path) -> dict[str, object]:
    """The dependency review register, read once."""
    return tomllib.loads((repo_root / REVIEWS).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The manifest is evidence
# ---------------------------------------------------------------------------


def test_the_manifest_announces_its_schema_and_version() -> None:
    """A supply manifest fed to another reader is refused by name, not by a missing key."""
    document = manifest.build(run={}, findings={}, capability={}, verdict={})
    assert document["schema"] == manifest.SCHEMA
    assert document["schema_version"] == manifest.SCHEMA_VERSION
    assert document["phase"] == 14


def test_the_manifest_is_sealed_against_editing() -> None:
    """The digest is what makes it evidence rather than a note.

    A file edited by hand — to drop a finding, to change a verdict — is refused
    here rather than read and believed.
    """
    document = manifest.build(
        run={"commit": "a" * 40}, findings={}, capability={}, verdict={"overall": "passed"}
    )
    assert manifest.load(manifest.render(document)) == document

    tampered = dict(document)
    tampered["verdict"] = {"overall": "passed", "reasons": []}
    tampered["findings"] = {"secret_hygiene": {"verdict": "passed"}}
    with pytest.raises(SupplyChainError, match="digest does not describe its contents"):
        manifest.load(manifest.render(tampered))


def test_a_manifest_from_another_schema_is_refused() -> None:
    """Refused rather than read partially, as ADR-0041 requires of every envelope."""
    document = manifest.build(run={}, findings={}, capability={}, verdict={})
    for key, value in (("schema", "globin.evidence.manifest"), ("schema_version", 99)):
        other = dict(document)
        other[key] = value
        other[manifest.DIGEST_KEY] = manifest.digest(other)
        with pytest.raises(SupplyChainError, match=r"not a globin|Regenerate it"):
            manifest.load(manifest.render(other))


def test_the_manifest_renders_identically_twice() -> None:
    """Two writers must not be able to disagree about bytes."""
    document = manifest.build(
        run={"b": 2, "a": 1}, findings={}, capability={}, verdict={"overall": "passed"}
    )
    assert manifest.render(document) == manifest.render(document)
    assert manifest.render(document).isascii()


def test_every_reason_code_is_declared() -> None:
    """A new failure mode cannot arrive with an undeclared name.

    The codes are stable identifiers rather than sentences, so that a later
    phase's dashboard can count them without parsing English.
    """
    emitted = {
        value
        for name, value in vars(manifest).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert emitted == set(manifest.REASONS)
    assert all(code.startswith("SUPPLY_") and code.isupper() for code in manifest.REASONS)


# ---------------------------------------------------------------------------
# The registers agree with what exists
# ---------------------------------------------------------------------------


def test_every_reviewed_dependency_is_still_declared(
    repo_root: Path, reviews: dict[str, object]
) -> None:
    """The register and the generated inventory, compared in both directions.

    A review for something nothing depends on is a decision nobody can act on;
    a dependency with no review is the thing the process exists to prevent.
    """
    entries = reviews["review"]
    assert isinstance(entries, list)
    reviewed = {str(entry["name"]) for entry in entries}
    declared = {
        entry.name
        for entry in collect(repo_root)
        if entry.ecosystem == PYPI and entry.source == "pyproject.toml"
    }
    assert reviewed == declared


@pytest.mark.parametrize(
    "field",
    ["name", "ecosystem", "scope", "licence", "licence_source", "reviewed", "verdict", "reason"],
)
def test_every_review_carries_every_field(reviews: dict[str, object], field: str) -> None:
    """A review missing its licence source is a licence nobody can check."""
    entries = reviews["review"]
    assert isinstance(entries, list)
    for entry in entries:
        assert entry.get(field), f"{entry.get('name')} omits {field}"


def test_every_licence_is_permitted_by_the_policy(
    repo_root: Path, reviews: dict[str, object]
) -> None:
    """`UNKNOWN` is not safe by default, and the policy table is what decides.

    Read from the policy document rather than restated here, so the two cannot
    disagree about what is allowed.
    """
    policy = (repo_root / POLICY).read_text(encoding="utf-8")
    entries = reviews["review"]
    assert isinstance(entries, list)
    for entry in entries:
        licence = str(entry["licence"])
        assert licence != "UNKNOWN", f"{entry['name']} has an unreviewed licence"
        assert licence in policy, f"{licence} is not classified in {POLICY}"


def test_every_capability_state_is_documented(repo_root: Path) -> None:
    """The states the code can produce and the states the policy explains.

    A state the code emits and the document does not describe is a state nobody
    reading the manifest can interpret.
    """
    policy = (repo_root / POLICY).read_text(encoding="utf-8")
    for state in capability.State:
        assert f"`{state.value}`" in policy, f"{state.value} is not explained in {POLICY}"


# ---------------------------------------------------------------------------
# The gate cannot be made to lie
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mask", FAILURE_MASKS)
def test_no_module_can_mask_a_failure(package_sources: dict[str, str], mask: str) -> None:
    """A security gate that cannot fail is worse than none, because it is believed."""
    offenders = [name for name, source in package_sources.items() if mask in _executable(source)]
    assert not offenders, f"{mask!r} appears in {offenders}"


def test_the_supply_command_is_reachable_only_through_the_command_table() -> None:
    """Every gate is a name in one table, so the developer's and CI's cannot drift."""
    command = find("supply")
    assert command is not None
    assert command.steps[0].argv == ("-m", "tools.quality.supply")
    assert "pip_audit" in command.steps[0].modules, (
        "the module must be declared, or a machine without it would report an audit "
        "that found nothing rather than an audit that did not happen"
    )


def test_the_supply_gate_is_absent_from_fast_and_full() -> None:
    """It reaches the network, and `full` runs before every commit.

    A gate needing a network in `full` is a gate people learn to skip.
    """
    for name in ("fast", "full"):
        command = find(name)
        assert command is not None
        assert "supply" not in {step.name for step in command.steps}


def test_the_gate_writes_only_inside_the_ignored_run_directory(repo_root: Path) -> None:
    """Nothing generated is committed, so the tree the gate judges is the tree as written."""
    from tools.quality.supply.gate import OUTPUT_DIRECTORY

    assert OUTPUT_DIRECTORY.startswith(".globin/")
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".globin/" in ignored


def test_the_suite_never_reaches_the_network(package_sources: dict[str, str]) -> None:
    """The two functions that start a process are named, and neither is called by a test.

    ADR-0024 makes the suite offline by construction, and an autouse fixture
    refuses outbound sockets — so this asserts the design rather than the
    enforcement: everything that decides anything is pure and tested from
    literals, and only `probe` and `run` reach out.
    """
    for name in ("capability.py", "audit.py"):
        assert "subprocess.run" in package_sources[name]
    for name, source in package_sources.items():
        if name not in {"capability.py", "audit.py", "gate.py"}:
            assert "subprocess" not in _executable(source), f"{name} should not start a process"
