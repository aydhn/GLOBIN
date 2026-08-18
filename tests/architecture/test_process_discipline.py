"""Exactly one module in GLOBIN may start a process, it is named, and it does.

Before Phase 032 nothing under `src/globin` imported `subprocess` at all. That was
never a rule — `docs/architecture/dependency-rules.toml` has always listed
`subprocess` among the I/O-capable modules and always let the adapters layer
perform I/O — it was an unbroken property, and an unbroken property with nothing
holding it is one edit from being broken by somebody who had a good reason that
afternoon.

This is the shape `test_library_discipline.py` uses for the socket, including the
part that matters most: **both directions**. A rule asserting that no module
outside the named one reaches a process is vacuously satisfied by a tree where
nothing does, so the second test asserts the named module still does. A proxy
rather than a proof — a module handed an open pipe would defeat it — but a
deterministic one, and it catches the way the boundary is realistically eroded:
somebody importing `subprocess` in a second place because it was convenient there
too.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.support import REPO_ROOT

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
ROOT_PACKAGE: Final[str] = "globin"

PROCESS_MODULE: Final[str] = "globin.adapters.provisioning"
"""The one module in GLOBIN that may start a child process."""

PROCESS_IMPORTS: Final[tuple[str, ...]] = ("subprocess", "multiprocessing")
"""Standard-library routes to a child process, permitted only in
:data:`PROCESS_MODULE`.

`multiprocessing` joins `subprocess` because it is a route to the same
capability: a module that could not import one but could import the other would
be one convenience away from starting a process anyway.
"""

PROCESS_CALLS: Final[tuple[str, ...]] = (
    "system",
    "popen",
    "spawnl",
    "spawnle",
    "spawnv",
    "spawnve",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "posix_spawn",
    "startfile",
)
"""`os` attributes that start a process, matched only when qualified by `os`.

`os` is imported almost everywhere and legitimately so — it is how the runtime
tree reads an environment variable. Only these attributes are the subject.

**Qualified rather than bare, and Phase 032 learned why by writing it wrong
first.** A bare `system` matched `HostFacts.system` — the operating system's
*name* — in seven modules that start nothing, which would have made this rule
either permanently red or permanently suppressed. Matching `os.system` costs a
little precision against `from os import system`, which
`test_no_module_imports_a_process_starter_from_os` covers separately, and buys a
rule that means what it says. The socket discipline made the same correction to
its own neighbour, for the same reason.
"""


def _modules(root: Path) -> list[Path]:
    """Every module in the package."""
    return sorted((root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def _module_name(path: Path, root: Path) -> str:
    """The dotted name of one module."""
    relative = path.relative_to(root / PACKAGE_RELATIVE_PATH).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join([ROOT_PACKAGE, *parts]) if parts else ROOT_PACKAGE


def _imports(tree: ast.AST, target: str) -> set[str]:
    """Every spelling by which one module is imported."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names if alias.name.split(".")[0] == target}
        elif (
            isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == target
        ):
            found.add(node.module)
    return found


def _os_attributes(tree: ast.AST) -> set[str]:
    """Every attribute reached through a name bound as `os`.

    Args:
        tree: A parsed module.

    Returns:
        The attribute names, so `os.system(...)` yields `{"system"}` and
        `facts.system` yields nothing.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            found.add(node.attr)
    return found


def _imported_names(tree: ast.AST, module: str) -> set[str]:
    """Every name imported *from* one module.

    Args:
        tree: A parsed module.
        module: The module imported from.

    Returns:
        The bound names, so `from os import system` yields `{"system"}`.

    The half `_os_attributes` cannot see: a name unbound from its module reads
    like any other call, so the import is where it has to be caught.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            found |= {alias.asname or alias.name for alias in node.names}
    return found


@pytest.fixture(scope="module")
def package_trees(repo_root: Path) -> dict[str, ast.AST]:
    """Every module in the package, parsed once."""
    return {
        _module_name(path, repo_root): ast.parse(path.read_text(encoding="utf-8"))
        for path in _modules(repo_root)
    }


def test_only_one_module_can_start_a_process(package_trees: dict[str, ast.AST]) -> None:
    """The count of modules able to start a child is one, and it is named."""
    offenders: dict[str, list[str]] = {}
    for name, tree in package_trees.items():
        if name == PROCESS_MODULE:
            continue
        found = sorted(
            {spelling for guard in PROCESS_IMPORTS for spelling in _imports(tree, guard)}
        )
        if found:
            offenders[name] = found
    assert not offenders, f"a process became reachable outside {PROCESS_MODULE}: {offenders}"


def test_no_module_reaches_a_process_through_os(package_trees: dict[str, ast.AST]) -> None:
    """`os.system` and its neighbours are refused everywhere, including the one.

    Unlike the import rule, this one has no exception. The named module starts
    its child through `subprocess.run` with an argument vector; `os.system` takes
    a string and hands it to a shell, which is the thing
    `globin.domain.process.CommandRequest` exists to make unrepresentable.
    """
    offenders: dict[str, list[str]] = {}
    for name, tree in package_trees.items():
        used = sorted(_os_attributes(tree).intersection(PROCESS_CALLS))
        if used:
            offenders[name] = used
    assert not offenders, f"a shell-shaped process route was used: {offenders}"


def test_no_module_imports_a_process_starter_from_os(
    package_trees: dict[str, ast.AST],
) -> None:
    """The other half: a name unbound from `os` reads like any other call.

    `from os import system` would make `system(...)` invisible to the qualified
    check above, so the import is where it is caught instead.
    """
    offenders: dict[str, list[str]] = {}
    for name, tree in package_trees.items():
        bound = sorted(_imported_names(tree, "os").intersection(PROCESS_CALLS))
        if bound:
            offenders[name] = bound
    assert not offenders, f"a process starter was unbound from os: {offenders}"


def test_the_module_that_starts_a_process_does_import_one(
    package_trees: dict[str, ast.AST],
) -> None:
    """The other direction, so the rule above is not vacuously true.

    Without this, deleting the adapter would make the first test pass more
    convincingly than ever.
    """
    tree = package_trees[PROCESS_MODULE]
    found = {spelling for guard in PROCESS_IMPORTS for spelling in _imports(tree, guard)}
    assert found, f"{PROCESS_MODULE} starts no process, so the rule guards nothing"


def test_the_os_attribute_walk_finds_its_own_failing_case() -> None:
    """Guard the guard, and pin the over-breadth this rule was written with first.

    A walk returning nothing would make the `os` rule pass over any tree. And a
    walk matching bare attribute names would flag `facts.system`, which is the
    operating system's *name* and appears in seven modules that start nothing.
    """
    assert "system" in _os_attributes(ast.parse("import os\nos.system('echo hi')\n"))
    assert not _os_attributes(ast.parse("x = facts.system\n"))
    assert not _os_attributes(ast.parse("x = 1\n")).intersection(PROCESS_CALLS)


def test_the_from_import_walk_finds_its_own_failing_case() -> None:
    """Guard the guard, for the half the qualified check cannot see."""
    assert _imported_names(ast.parse("from os import system\n"), "os") == {"system"}
    assert _imported_names(ast.parse("from os import system as s\n"), "os") == {"s"}
    assert _imported_names(ast.parse("from json import loads\n"), "os") == set()


def test_the_import_walk_finds_its_own_failing_case() -> None:
    """Guard the guard, for the other rule."""
    assert _imports(ast.parse("import subprocess\n"), "subprocess") == {"subprocess"}
    assert _imports(ast.parse("from subprocess import run\n"), "subprocess") == {"subprocess"}
    assert _imports(ast.parse("import json\n"), "subprocess") == set()


def test_a_docstring_naming_subprocess_does_not_violate_the_rule() -> None:
    """Prose may explain the rule it is subject to.

    The neighbouring socket discipline had to learn this the hard way: a check
    written over raw text made the file explaining why a function is forbidden
    violate the rule that forbade it.
    """
    tree = ast.parse('"""This module must not import subprocess."""\n')
    assert _imports(tree, "subprocess") == set()


def test_the_named_module_exists_where_the_rule_says_it_does() -> None:
    """A rule naming a module that has moved guards nothing, silently."""
    relative = PROCESS_MODULE.removeprefix(f"{ROOT_PACKAGE}.").replace(".", "/")
    assert (REPO_ROOT / PACKAGE_RELATIVE_PATH / f"{relative}.py").is_file()
