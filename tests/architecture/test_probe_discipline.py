"""Whether psutil has spread beyond the one adapter that may reach it.

`numpy` and `pandas` are declared and never imported, and
`test_stack_discipline.py` enforces that. `psutil` is the opposite case: it is
declared *and* imported, which makes a different rule necessary — not "nobody
touches this" but "exactly one module does".

**Why nothing else already covers this.** The dependency contract forbids an inner
layer importing an I/O-capable module, and psutil is not in that list because the
list names standard-library packages. Packaging declares it, so nothing there
objects. The stack tripwire derives its guarded set from the stack contract, which
psutil is deliberately not in — it is adopted, not merely verified.

So the rule enforced here is the one none of those can: `psutil` is named in
`globin.adapters.health` and nowhere else under `src/globin`. That is what makes
the CI story true — the library is absent in the `quality` job on every run — and
what keeps the absence handled in one place rather than at every call site.

Like its neighbours this is a proxy rather than a proof: it matches spellings, so
an alias or an `importlib.import_module` call defeats it.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

GUARDED: Final[str] = "psutil"
"""The distribution this rule is about."""

PERMITTED: Final[str] = "globin.adapters.health"
"""The one module that may name it."""


def _imports(tree: ast.AST) -> list[str]:
    """Every import of the guarded distribution in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found.

    Both import forms are matched, and only on the top-level name, so
    `import psutil._common` is caught as well as the bare spelling. A relative
    import carries no module name and is skipped rather than compared against
    `None`.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name
                for alias in node.names
                if alias.name.split(".", maxsplit=1)[0] == GUARDED
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.level == 0
            and node.module.split(".", maxsplit=1)[0] == GUARDED
        ):
            found.append(node.module)
    return found


def test_the_guarded_name_is_something_the_repository_actually_declares() -> None:
    """Guard the guard: a rule about a dependency nobody has is not a rule."""
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert GUARDED in project.read_text(encoding="utf-8")


def test_only_one_adapter_names_psutil(repo_root: Path) -> None:
    """One module owns the absence, so nothing above it has to."""
    package = repo_root / PACKAGE_RELATIVE_PATH
    offenders = {
        module_name(path, package, ROOT_PACKAGE): found
        for path in sorted(package.rglob("*.py"))
        if (found := _imports(ast.parse(path.read_text(encoding="utf-8"))))
        and module_name(path, package, ROOT_PACKAGE) != PERMITTED
    }
    assert not offenders, (
        f"psutil is imported outside {PERMITTED}; the absence is handled in one "
        f"place so that every layer above can be written as if it were present: {offenders}"
    )


def test_the_permitted_adapter_does_name_it() -> None:
    """The other direction, so the check above is not vacuously true."""
    source = Path(__file__).resolve().parents[2] / PACKAGE_RELATIVE_PATH / "adapters" / "health.py"
    assert _imports(ast.parse(source.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("import psutil\n", ["psutil"], id="a plain import"),
        pytest.param("import psutil as ps\n", ["psutil"], id="an aliased import"),
        pytest.param("import psutil._common\n", ["psutil._common"], id="a submodule"),
        pytest.param("from psutil import Process\n", ["psutil"], id="a from-import"),
        pytest.param(
            "def f():\n    import psutil\n    return psutil\n",
            ["psutil"],
            id="inside a function, which is how this repository does it",
        ),
        pytest.param("import json\n", [], id="an unrelated import is spared"),
        pytest.param("import psutilish\n", [], id="a name merely starting with it is spared"),
        pytest.param("from . import health\n", [], id="a relative import is spared"),
        pytest.param("psutil = 1\n", [], id="a local named after it is spared"),
    ],
)
def test_the_import_check_notices_a_reach_and_spares_everything_else(
    source: str, expected: list[str]
) -> None:
    """The guard's own failing cases, in both directions.

    The in-function row is the one that matters most here: it is exactly how
    `system_process_probe` reaches the library, so a check that missed it would
    pass while the rule it states was unenforced.
    """
    assert _imports(ast.parse(source)) == expected
