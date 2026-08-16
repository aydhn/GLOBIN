"""GLOBIN's own call sites do not use the standard library's logging, and this proves it.

Phase 006 decided that GLOBIN logs through its own port rather than through
:mod:`logging`, and ``adapters/observability.py`` records why: module-level handler
state is exactly the global configuration ``ENGINEERING_CONTRACT.md`` invariant 5
exists to keep out. Phase 023 added a **bridge** so that a dependency emitting
standard-library records is not lost — which is the addition that module
anticipated, and which makes this tripwire necessary rather than optional.

Nothing else covers it:

* The dependency contract permits :mod:`logging` in ``adapters`` and ``runtime``,
  which is correct and is what lets the bridge exist at all. It cannot express
  "this one module, and no other".
* The no-work-at-import rule catches ``logging.basicConfig()`` written at module
  level and nothing written inside a function.
* ``test_observability_contract.py`` compares ``LOGGING_POLICY.md`` against the
  code that *is* there. Neither notices code that should not be.

**This is a tripwire, not a prohibition forever.** The phase that has a legitimate
second bridge edits the allowance below **in its own diff**, where the decision is
visible, rather than discovering the door was already open.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.support import REPO_ROOT

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

BRIDGE_MODULE: Final[str] = "diagnostics.py"
"""The one adapter module permitted to name :mod:`logging`.

Named by filename rather than by dotted path because this test reads the tree
rather than importing it — the same reason every module under
``tests/architecture`` uses :mod:`ast`.
"""

HOOK_OWNERS: Final[tuple[str, ...]] = ("diagnostics.py", "runtime_state.py")
"""The modules permitted to write a process-global hook.

``diagnostics.py`` installs the three fault hooks; ``runtime_state.py`` registers
the signal handlers and the ``atexit`` fallback. Both do it through an injected
registrar, and both are in ``adapters``.
"""

FORBIDDEN_ATTRIBUTES: Final[tuple[str, ...]] = (
    "basicConfig",
    "getLogger",
    "addHandler",
    "captureWarnings",
)
"""Standard-library logging entry points GLOBIN's own call sites must not use."""

PROCESS_HOOKS: Final[tuple[str, ...]] = ("excepthook", "unraisablehook")
"""Attributes whose assignment changes how the whole interpreter reports a fault."""


def _modules(root: Path) -> list[Path]:
    """Every module in the package.

    Args:
        root: The repository root.

    Returns:
        Each ``.py`` file under ``src/globin``, sorted so failures read the same
        way twice.
    """
    return sorted((root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def _imports_logging(tree: ast.AST) -> bool:
    """Whether a parsed module imports :mod:`logging` by any spelling.

    Args:
        tree: The parsed module.

    Returns:
        Whether ``logging`` is imported, aliased or imported from.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            if any(name == "logging" or name.startswith("logging.") for name in names):
                return True
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "logging":
            return True
    return False


def _hook_assignments(tree: ast.AST) -> list[str]:
    """Every assignment to a process-global fault hook.

    Args:
        tree: The parsed module.

    Returns:
        The attribute names assigned, such as ``sys.excepthook``.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in PROCESS_HOOKS:
                found.append(ast.unparse(target))
    return found


def test_the_allowance_names_a_module_that_exists() -> None:
    """Guard the guard.

    An allowance naming a file that is not there would make every check below
    compare against a set nothing can be in, and pass on any tree — the failure
    mode a tripwire has.
    """
    assert (REPO_ROOT / PACKAGE_RELATIVE_PATH / "adapters" / BRIDGE_MODULE).exists()
    for owner in HOOK_OWNERS:
        assert (REPO_ROOT / PACKAGE_RELATIVE_PATH / "adapters" / owner).exists()


def test_only_the_bridge_adapter_imports_the_standard_library_logging() -> None:
    """Everything else logs through GLOBIN's own port, per ADR-0025 and ADR-0026."""
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _modules(REPO_ROOT)
        if path.name != BRIDGE_MODULE
        and _imports_logging(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "these modules import the standard library's `logging`, which only the "
        f"bridge in adapters/{BRIDGE_MODULE} may do:\n  " + "\n  ".join(offenders)
    )


def test_no_module_configures_the_root_logger_outside_the_bridge() -> None:
    """`basicConfig` and friends are the global handler state invariant 5 excludes."""
    offenders: list[str] = []
    for path in _modules(REPO_ROOT):
        if path.name == BRIDGE_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {node.attr}")
    assert not offenders, "standard-library logging configuration outside the bridge:\n  " + (
        "\n  ".join(offenders)
    )


def test_a_process_hook_is_only_written_by_a_module_that_owns_one() -> None:
    """Replacing `sys.excepthook` anywhere else would be ambient state by another name."""
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()} -> {assignment}"
        for path in _modules(REPO_ROOT)
        if path.name not in HOOK_OWNERS
        for assignment in _hook_assignments(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, "process hooks written outside the modules that own them:\n  " + (
        "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("import logging", True, id="plain-import"),
        pytest.param("import logging.handlers", True, id="submodule-import"),
        pytest.param("import logging as stdlog", True, id="aliased-import"),
        pytest.param("from logging import Handler", True, id="from-import"),
        pytest.param("from logging.handlers import QueueHandler", True, id="from-submodule"),
        pytest.param("def f():\n    import logging", True, id="inside-a-function"),
        pytest.param("import loggingish", False, id="different-module-sharing-a-prefix"),
        pytest.param("logging = 1", False, id="a-local-named-logging"),
        pytest.param("from globin.domain import observability", False, id="unrelated-import"),
    ],
)
def test_the_import_detector_fires_exactly_when_it_should(source: str, expected: bool) -> None:
    """The checker's own failing cases, in both directions.

    A detector nobody has seen report anything is indistinguishable from one that
    cannot report at all, and the must-not-fire half is what stops it being
    satisfied by a substring match.
    """
    assert _imports_logging(ast.parse(source)) is expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("sys.excepthook = mine", ["sys.excepthook"], id="main-thread"),
        pytest.param("sys.unraisablehook = mine", ["sys.unraisablehook"], id="unraisable"),
        pytest.param("threading.excepthook = mine", ["threading.excepthook"], id="thread"),
        pytest.param("excepthook = mine", [], id="a-bare-local-of-the-same-name"),
        pytest.param("registry.write('sys.excepthook', mine)", [], id="written-through-a-registry"),
        pytest.param("value = sys.excepthook", [], id="reading-rather-than-writing"),
    ],
)
def test_the_hook_detector_fires_exactly_when_it_should(source: str, expected: list[str]) -> None:
    """Reading a hook is fine; replacing one is what changes the process.

    The registry case matters most: writing through an injected registrar is the
    house pattern this phase uses, and a detector that flagged it would push the
    next author towards touching :mod:`sys` directly to avoid the warning.
    """
    assert _hook_assignments(ast.parse(source)) == expected
