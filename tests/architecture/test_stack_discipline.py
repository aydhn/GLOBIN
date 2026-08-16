"""Whether the scientific stack has crossed into the package, enforced on the real tree.

Phase 022 **verifies** `numpy` and `pandas`; it does not adopt them. That
distinction is easy to state and easy to lose, because the libraries are now
installed, importable and one line away from any module somebody is editing.

**Why nothing else already covers this.** Three checks look as though they might,
and none does:

* The dependency contract forbids an inner layer importing an I/O-capable module.
  `numpy` and `pandas` are not in that list and should not be — the list is about
  reaching outside the process, and an array library does not.
* `pyproject.toml` declares both as runtime dependencies, so nothing in packaging
  objects to importing them. That declaration is what Phase 021 delivered.
* The stack gate proves they behave correctly. A correct library is exactly the
  kind somebody reaches for.

So the rule enforced here is the one none of those can: no module under
`src/globin` imports either library, anywhere, including inside a function body.

**This is a tripwire, not a prohibition forever.**
[`docs/PRECISION_POLICY.md`](../../docs/PRECISION_POLICY.md) rule 1 is a one-way
door — a `float` may never be the last transformation before a venue or a ledger,
and may never decide a refusal — and the same document defers the numeric type
indicators and models use to Phases 113-128. The phase that has a legitimate use
edits the set below **in its own diff**, where the decision is visible, rather
than discovering that the door was already open.

Like its two neighbours this is a proxy rather than a proof: it matches spellings,
so an alias or an `importlib.import_module` call defeats it. It catches the way a
boundary is realistically eroded — somebody reaches for the convenient thing — and
it has its own failing cases in both directions below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE
from tools.quality.stack.gate import declaration_of

#: Top-level distributions the package may not import. Derived from the stack
#: contract rather than written out, so a library added to that declaration is
#: covered here without anybody remembering to add it twice.
VERIFIED_NOT_ADOPTED: Final[frozenset[str]] = frozenset(
    library.import_name for library in declaration_of().libraries
)


def _stack_imports(tree: ast.AST) -> list[str]:
    """Every import of a verified-but-not-adopted library in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found, in the order :func:`ast.walk` reaches them.

    Both import forms are matched, and only on the **top-level** name, so
    `import numpy.linalg` and `from pandas.api import types` are caught as well as
    the bare spellings. A relative `from . import x` carries no module name and is
    skipped rather than compared against `None`.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if _root_of(alias.name) in VERIFIED_NOT_ADOPTED
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.level == 0
            and _root_of(node.module) in VERIFIED_NOT_ADOPTED
        ):
            found.append(node.module)
    return found


def _root_of(module: str) -> str:
    """The top-level package a dotted module name belongs to.

    Args:
        module: The dotted name.

    Returns:
        Everything before the first dot.
    """
    return module.split(".", maxsplit=1)[0]


def _package_modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def test_the_declaration_names_something_to_guard_against() -> None:
    """Guard the guard.

    An empty set would make the check below compare against nothing and pass on
    every tree, which is the failure mode a tripwire has.
    """
    assert {"numpy", "pandas"} <= VERIFIED_NOT_ADOPTED


def test_no_module_in_the_package_imports_the_scientific_stack(repo_root: Path) -> None:
    """Verification is not adoption, and this is where the two stay apart.

    ADR-0058 records the reasoning. If this fails in a phase that meant it, the
    fix is to edit the stack contract in that phase's diff — not to add an
    exemption here.
    """
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): imports
        for path in _package_modules(repo_root)
        if (imports := _stack_imports(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert not offenders, (
        "the scientific stack is imported inside the package; Phase 022 verifies "
        "numpy and pandas and does not adopt them, and PRECISION_POLICY.md rule 1 "
        f"is a one-way door that is cheapest to hold now: {offenders}"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("import numpy\n", ["numpy"], id="a plain import"),
        pytest.param("import numpy as np\n", ["numpy"], id="an aliased import"),
        pytest.param("import numpy.linalg\n", ["numpy.linalg"], id="a submodule"),
        pytest.param("from pandas import DataFrame\n", ["pandas"], id="a from-import"),
        pytest.param(
            "from pandas.api import types\n", ["pandas.api"], id="a from-import of a submodule"
        ),
        pytest.param(
            "def f():\n    import numpy\n    return numpy\n",
            ["numpy"],
            id="inside a function, where nothing else would see it",
        ),
        pytest.param("import os, numpy\n", ["numpy"], id="second in a multiple import"),
        pytest.param("import json\n", [], id="an unrelated import is spared"),
        pytest.param("from globin.domain import values\n", [], id="a package import is spared"),
        pytest.param(
            "import numpyish\n", [], id="a name merely starting with a guarded one is spared"
        ),
        pytest.param("from . import values\n", [], id="a relative import is spared"),
        pytest.param("numpy = 1\n", [], id="a local named after one is spared"),
    ],
)
def test_the_import_check_notices_a_reach_and_spares_everything_else(
    source: str, expected: list[str]
) -> None:
    """The guard's own failing cases, in both directions.

    `TESTING_STRATEGY.md` requires every checker to be exercised by something it
    must catch and something it must not. The last four rows are the ones that
    matter: a check matching `numpyish` or a relative import would refuse correct
    code, and a check missing the in-function form would be defeated by the exact
    move somebody makes when they want to avoid a module-level import.
    """
    assert _stack_imports(ast.parse(source)) == expected
