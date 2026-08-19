"""Where a venue fact may be written down, enforced against the real source tree.

Phase 033's registry is a committed document, and its whole value is that it is the
*only* place a Binance fact lives. That is easy to lose: the natural next commit
after "the registry holds the base URLs" is a base URL pasted into an adapter,
placed there because that is where the request will be made.

Two rules, and each has its own failing case below.

**No venue host appears in the package at all.** Not one, anywhere -- this is
stronger than "only in the registry reader", and it can be stronger because the
registry is data rather than code. The rule that would have been needed if product
families had stayed an enumeration is the rule
``test_identifier_discipline.py`` already states, and it refused that design
during this phase.

**Exactly one module parses the registry.** ``tomllib`` is I/O-capable, so the
dependency contract already keeps it out of the inner layers; what it cannot say is
that a *second* adapter must not grow its own reader. Two readers of one document
inside one package is how they come to disagree.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

#: Hostnames the venue serves, in the spellings a paste would carry. Compared
#: case-insensitively against whole string constants, so prose mentioning one is
#: unaffected and a literal holding one is not.
VENUE_HOSTS: Final[tuple[str, ...]] = (
    "binance.com",
    "binance.vision",
    "binancefuture.com",
    "githubusercontent.com",
)

#: The one module permitted to read the registry document.
REGISTRY_READER: Final[str] = "globin.adapters.api_reality"

#: How the registry is reached, in the spelling a second reader would use.
REGISTRY_MARKER: Final[str] = "binance-api-reality.toml"


def _live_constants(tree: ast.AST) -> list[str]:
    """Every string constant in a parsed module that is not a docstring.

    Args:
        tree: The parsed source.

    Returns:
        The values, in the order :func:`ast.walk` reaches them.

    A docstring is a bare string expression statement, so excluding every
    :class:`ast.Expr` wrapping a constant removes module, class, function and
    attribute docstrings in one rule.
    """
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _package_modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def test_no_venue_host_is_spelled_anywhere_in_the_package(repo_root: Path) -> None:
    """A base URL in code is a fact the registry cannot correct.

    The registry exists so that a host has one home. A literal in an adapter would
    still work, would still be wrong when the venue moved it, and would be wrong
    somewhere nobody thinks to look.
    """
    offenders: dict[str, list[str]] = {}
    for path in _package_modules(repo_root):
        named = sorted(
            {
                value
                for value in _live_constants(ast.parse(path.read_text(encoding="utf-8")))
                if any(host in value.lower() for host in VENUE_HOSTS)
            }
        )
        if named:
            offenders[module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)] = named
    assert not offenders, (
        "the package spells a venue host; every endpoint belongs in "
        f"docs/engineering/{REGISTRY_MARKER} and nowhere else: {offenders}"
    )


def test_the_checker_would_notice_a_pasted_host() -> None:
    """The rule above guards something, proved by making it fail.

    Without this, a checker that silently stopped matching would read as a passing
    rule for ever.
    """
    tree = ast.parse('BASE = "https://api.binance.com"\n')
    found = [
        value
        for value in _live_constants(tree)
        if any(host in value.lower() for host in VENUE_HOSTS)
    ]
    assert found == ["https://api.binance.com"]


def test_exactly_one_module_reads_the_registry(repo_root: Path) -> None:
    """Two readers of one document inside one package is how they disagree.

    The gate under ``tools/`` is a second reader deliberately, and that one is
    outside the package and shares none of its code -- which is the point of it.
    """
    readers = [
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        for path in _package_modules(repo_root)
        if any(
            REGISTRY_MARKER in value
            for value in _live_constants(ast.parse(path.read_text(encoding="utf-8")))
        )
    ]
    assert readers == [REGISTRY_READER], (
        f"exactly one module may reach the registry document, and these do: {readers}"
    )


def test_the_named_reader_still_reads_it(repo_root: Path) -> None:
    """The rule fails in both directions, so it cannot pass by the reader vanishing.

    ``test_process_discipline.py`` is the same shape for the same reason: a rule
    that only forbids is satisfied by nobody doing the thing at all.
    """
    reader = repo_root / PACKAGE_RELATIVE_PATH / "adapters" / "api_reality.py"
    found = _live_constants(ast.parse(reader.read_text(encoding="utf-8")))
    assert any(REGISTRY_MARKER in value for value in found)


def test_the_registry_document_exists(repo_root: Path) -> None:
    """The rules above are about a document, so the document must be there.

    An absent registry would make every rule here vacuously true while the package
    reported every capability as unmeasured.
    """
    assert (repo_root / "docs" / "engineering" / REGISTRY_MARKER).is_file()


@pytest.mark.parametrize("layer", ["domain", "ports"])
def test_no_inner_layer_parses_the_registry(repo_root: Path, layer: str) -> None:
    """``tomllib`` is I/O-capable, and the inner layers may import none of it.

    Restated here against the api-reality modules specifically, because the
    dependency contract's own test would catch the import and this names the reason
    a reader looking at this subject would want.
    """
    module = repo_root / PACKAGE_RELATIVE_PATH / layer / "api_reality.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        name.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "tomllib" not in imported
