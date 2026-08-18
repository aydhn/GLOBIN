"""Every absent-safe factory is declared, and every declaration names a real one.

**Both directions, and the second is the one that earns the file.** A rule that
only checked "every declared path exists" would keep passing when a seventh
absent-safe factory arrived undeclared — and an undeclared factory is a component
GLOBIN silently does not survey, which is exactly the state `runtime.degradation`
exists to make impossible.

The convention this leans on is already established and already enforced
elsewhere: an adapter that may be absent answers with a stand-in class named
`Unavailable*` rather than raising, so `globin.adapters` imports on a host with
none of the six libraries. That is what
`tests/architecture/test_credential_discipline.py` protects for the Win32 half and
what `tests/smoke/test_import_surface.py` proves end to end. This file adds the
consequence: whatever chooses between the two arms must be in the contract.

**The checker is exercised against something it must catch and something it must
not**, which `docs/TESTING_STRATEGY.md` requires of every checker in this
repository — a rule that could not fail is a rule nobody has tested.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.degradation import CONTRACT_RELATIVE_PATH, read_contract

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
"""Where the repository is, from this file."""

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

STAND_IN_PREFIX: Final[str] = "Unavailable"
"""What an absent-safe stand-in class is called.

The convention rather than a rule invented here: `UnavailableProcessProbe`,
`UnavailableOpenTelemetry`, `UnavailablePrometheus`, `UnavailableSecretStore`,
`UnavailableSystemApi` and `UnavailableSecretVault` all predate or arrive with this
check, and each is the answer its factory gives where the library is missing.
"""

EXEMPT: Final[frozenset[str]] = frozenset({"globin.adapters.degradation"})
"""Modules that define no absent-safe factory of their own.

Only the survey itself, which imports every stand-in in order to classify what the
factories returned. Listing it here rather than excluding "anything that imports a
stand-in" keeps the exemption to one named module.
"""


def _stand_in_modules() -> dict[str, Path]:
    """Every module defining a class whose name marks it as a stand-in.

    Returns:
        Dotted module name to its path.
    """
    package = REPO_ROOT / PACKAGE_RELATIVE_PATH
    found: dict[str, Path] = {}
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defines = any(
            isinstance(node, ast.ClassDef) and node.name.startswith(STAND_IN_PREFIX)
            for node in ast.walk(tree)
        )
        if defines:
            relative = path.relative_to(package).with_suffix("")
            found[f"globin.{relative.as_posix().replace('/', '.')}"] = path
    return found


def _declared_modules() -> set[str]:
    """Every module the contract names through a `reached_through` path.

    Returns:
        Dotted module names, with the attribute stripped.
    """
    specs = read_contract(REPO_ROOT / CONTRACT_RELATIVE_PATH)
    assert specs is not None, "the committed degradation contract must be readable"
    return {spec.reached_through.rpartition(".")[0] for spec in specs if spec.reached_through}


def test_every_declared_factory_names_something_real() -> None:
    """A contract row pointing at nothing would survey nothing and say ready."""
    specs = read_contract(REPO_ROOT / CONTRACT_RELATIVE_PATH)
    assert specs is not None
    package = REPO_ROOT / PACKAGE_RELATIVE_PATH
    missing: list[str] = []
    for spec in specs:
        if not spec.reached_through:
            continue
        module, _, attribute = spec.reached_through.rpartition(".")
        relative = Path(module.removeprefix("globin.").replace(".", "/") + ".py")
        source = package / relative
        if not source.exists():
            missing.append(spec.reached_through)
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        if attribute not in defined:
            missing.append(spec.reached_through)
    assert not missing


def test_every_absent_safe_module_is_declared() -> None:
    """The direction that earns the file.

    A seventh factory added without a contract row is a component nothing
    surveys, and the posture would go on saying ready about a host that had lost
    something.
    """
    undeclared = sorted(set(_stand_in_modules()) - _declared_modules() - EXEMPT)
    assert not undeclared


def test_the_exemption_names_only_modules_that_exist() -> None:
    """A stale exemption is a hole nobody can see.

    The same rule the credential allowlist follows: an entry that stopped
    matching anything has quietly widened the check it was carved out of.
    """
    package = REPO_ROOT / PACKAGE_RELATIVE_PATH
    for module in EXEMPT:
        relative = Path(module.removeprefix("globin.").replace(".", "/") + ".py")
        assert (package / relative).exists(), module


def test_at_least_six_components_are_declared() -> None:
    """Non-vacuity: a contract that had emptied itself would pass everything above."""
    specs = read_contract(REPO_ROOT / CONTRACT_RELATIVE_PATH)
    assert specs is not None
    assert len(specs) >= 6


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("class UnavailableThing:\n    pass\n", True, id="defines-a-stand-in"),
        pytest.param("class OrdinaryThing:\n    pass\n", False, id="defines-nothing"),
        pytest.param(
            "def build() -> object:\n    return UnavailableThing()\n",
            False,
            id="uses-one-without-defining-it",
        ),
    ],
)
def test_the_stand_in_check_notices_a_definition_and_spares_everything_else(
    tmp_path: Path, source: str, expected: bool
) -> None:
    """The checker's own failing cases, in both directions.

    The third row is the one that matters: the survey module *uses* every stand-in
    and defines none, so a check that looked for the name anywhere would have to
    exempt the very module it exists to serve.
    """
    target = tmp_path / "sample.py"
    target.write_text(source, encoding="utf-8")
    tree = ast.parse(target.read_text(encoding="utf-8"))
    defines = any(
        isinstance(node, ast.ClassDef) and node.name.startswith(STAND_IN_PREFIX)
        for node in ast.walk(tree)
    )
    assert defines is expected
