"""Whether `contextvars` has spread beyond the one module allowed to hold it.

`globin.application.tracing` argues at length that a span-nesting context variable
does not contradict ADR-0026, and the argument turns on two properties: the
variable holds a `SpanContext` and nothing else, and reaching it requires being
handed the scope. Prose cannot enforce either. This can.

**Why nothing else already covers this.** The dependency contract cannot help —
`contextvars` is not I/O-capable and is therefore permitted in every inner layer.
The import-time checker would catch a `ContextVar(...)` at module scope but says
nothing about *which* module holds one or *what* it holds.

Like its neighbours this is a proxy rather than a proof: it matches spellings, so
an alias or an `importlib.import_module` call defeats it. It catches the way a
boundary is realistically eroded — somebody reaches for the convenient thing — and
it has its own failing cases in both directions below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

GUARDED: Final[str] = "contextvars"
"""The module this rule is about."""

PERMITTED: Final[str] = "globin.application.tracing"
"""The one module that may name it."""

FORBIDDEN_HOLDINGS: Final[tuple[str, ...]] = ("Logger", "LogSink")
"""Types a context variable must never carry.

ADR-0026's objection is about the correlation id, and a variable holding a logger
is the shortest route to an ambient one.
"""


def _names(tree: ast.AST) -> list[str]:
    """Every spelling of the guarded module in a parsed file.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found, in the order :func:`ast.walk` reaches them.

    Both import forms are matched, and only on the top-level name, so
    ``import contextvars.x`` and ``from contextvars import ContextVar`` are both
    caught. A relative ``from . import x`` carries no module name and is skipped.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if alias.name.split(".")[0] == GUARDED)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == GUARDED
        ):
            found.append(node.module)
    return found


def _modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def _identifier(path: Path, repo_root: Path) -> str:
    """The dotted module name of one file.

    Args:
        path: The file.
        repo_root: The repository root.

    Returns:
        Its dotted name.
    """
    return module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)


def test_the_guarded_module_is_something_the_package_actually_uses() -> None:
    """Guard the guard: a rule about a module nobody imports is not a rule."""
    tracing = Path(__file__).resolve().parents[2] / "src" / "globin" / "application" / "tracing.py"
    assert GUARDED in tracing.read_text(encoding="utf-8")


def test_only_one_module_names_contextvars(repo_root: Path) -> None:
    """One module owns propagation, so nothing above it can hold ambient state.

    This is rule 2 of the four `globin.application.tracing` states: reaching the
    variable requires being handed the scope. A second module holding one would
    make that sentence false without anybody editing it.
    """
    offenders = {
        _identifier(path, repo_root): found
        for path in _modules(repo_root)
        if (found := _names(ast.parse(path.read_text(encoding="utf-8"))))
        and _identifier(path, repo_root) != PERMITTED
    }
    assert not offenders, (
        f"contextvars is named outside {PERMITTED}; propagation lives in one place "
        f"so that ADR-0026's rule about ambient state holds everywhere else: {offenders}"
    )


def test_the_permitted_module_does_name_it(repo_root: Path) -> None:
    """The other direction, so the check above is not vacuously true."""
    path = repo_root / PACKAGE_RELATIVE_PATH / "application" / "tracing.py"
    assert _names(ast.parse(path.read_text(encoding="utf-8")))


def test_the_context_variable_is_built_inside_a_function(repo_root: Path) -> None:
    """The variable is created by a factory, never at module or class scope.

    **There is deliberately no second import-time checker here.**
    `test_architecture_contract.py::test_layer_modules_execute_no_work_when_imported`
    already refuses *every* call at module or class scope in *every* layer
    package, which covers `ContextVar(...)` without naming it — and a second copy
    of that rule is exactly the drift `SOURCE_OF_TRUTH.md` forbids.

    What this adds is the other half, which that rule cannot express: the call
    must exist *somewhere*, inside a function. A scope whose variable had
    quietly become a module constant would satisfy the import rule by being
    deleted, and nothing would notice.
    """
    path = repo_root / PACKAGE_RELATIVE_PATH / "application" / "tracing.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    inside: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        inside.extend(
            node.name
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and "ContextVar" in ast.unparse(call.func)
        )
    assert inside, "no function builds a context variable, so propagation has no owner"


def test_the_scope_holds_no_logger(repo_root: Path) -> None:
    """Rule 1: the variable carries a `SpanContext` and nothing else.

    A scope holding a logger is the shortest route to the ambient correlation id
    ADR-0026 refused, so the field types are checked rather than trusted.
    """
    path = repo_root / PACKAGE_RELATIVE_PATH / "application" / "tracing.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    annotations = [
        ast.unparse(node.annotation)
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and node.annotation is not None
    ]
    for annotation in annotations:
        for forbidden in FORBIDDEN_HOLDINGS:
            assert forbidden not in annotation, (
                f"the span scope declares a {forbidden}, which would let a context "
                f"variable carry the correlation ADR-0026 keeps explicit"
            )


@pytest.mark.parametrize(
    ("source", "caught"),
    [
        pytest.param("import contextvars\n", True, id="plain"),
        pytest.param("import contextvars as cv\n", True, id="aliased"),
        pytest.param("from contextvars import ContextVar\n", True, id="from-import"),
        pytest.param("def f():\n    import contextvars\n", True, id="inside-a-function"),
        pytest.param("import contextlib\n", False, id="unrelated-module"),
        pytest.param("from globin.domain import tracing\n", False, id="unrelated-from"),
        pytest.param("from . import tracing\n", False, id="relative"),
        pytest.param("contextvars = 1\n", False, id="a-local-of-the-same-name"),
    ],
)
def test_the_detector_notices_a_reach_and_spares_everything_else(source: str, caught: bool) -> None:
    """Guard the guard, in both directions.

    An import inside a function is included on purpose: that is where a
    convenience import actually appears, and a checker that only read the header
    would miss it.
    """
    assert bool(_names(ast.parse(source))) is caught
