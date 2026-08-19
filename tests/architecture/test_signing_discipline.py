"""Whether `cryptography` has spread beyond the one adapter that may reach it.

The same rule `test_probe_discipline.py` holds for `psutil` and
`test_credential_discipline.py` holds for the three Win32 libraries, applied to
the seventh absent-safe component. `cryptography` is declared *and* imported, so
the rule is not "nobody touches this" but "exactly one module does".

**Two things make this stricter than its neighbours**, and both are about what
the library is for rather than about how it is imported.

*A private key must not reach a second module.* The one permitted importer is
also the only place a PEM is parsed, and confining the parse confines every path
by which a key object could be handed somewhere it might be rendered. A second
importer would be a second place that could hold one.

*PSS must be absent rather than unused.* The venue states plainly that it does
not support the PSS signature scheme, and PSS is one argument away from PKCS#1
v1.5 in this library's API — same call, same signature length, silently rejected
by the venue. So this file asserts the token appears nowhere in the package at
all, which is the same shape as `test_rest_contract.py`'s check that no
`CERT_NONE` exists: a validator can only refuse what reaches it, and an absence is
stronger than a branch.

Like its neighbours this is a proxy rather than a proof: it matches spellings, so
an alias or an `importlib.import_module` call defeats it.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

GUARDED: Final[str] = "cryptography"
"""The distribution this rule is about."""

PERMITTED: Final[str] = "globin.adapters.signing"
"""The one module that may name it."""

FORBIDDEN_TOKENS: Final[tuple[str, ...]] = ("PSS", "MGF1")
"""Spellings that must appear nowhere in the package, as code.

`PSS` is the signature scheme the venue documents as unsupported: *"We currently
do not support the PSS signature scheme."* `MGF1` is the mask generation function
PSS requires, so it cannot appear without PSS and is guarded beside it — a
belt-and-braces pairing rather than a second rule.

**Checked against the AST rather than the text**, which
`test_rest_contract.py` learned the hard way: its first draft flagged the
transport's own docstring explaining why `CERT_NONE` is absent. A rule that
cannot be explained in prose without failing is a rule people delete.
"""


def _package_modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def _imports(tree: ast.AST) -> list[str]:
    """Every import of the guarded distribution in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found.

    Both import forms are matched, and only on the top-level name, so
    `from cryptography.hazmat.primitives import hashes` is caught as well as a
    bare `import cryptography`. A relative import carries no module name and is
    skipped rather than compared against `None`.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name.split(".", 1)[0] == GUARDED
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.level == 0
            and node.module.split(".", 1)[0] == GUARDED
        ):
            found.append(node.module)
    return found


def _code_names(tree: ast.AST) -> list[str]:
    """Every attribute and bare name a parsed module uses, excluding strings.

    Args:
        tree: The parsed source.

    Returns:
        The identifiers, in the order `ast.walk` reaches them.

    Docstrings and string constants are excluded by construction: only `ast.Name`
    and `ast.Attribute` nodes are visited, so prose explaining why a token is
    forbidden cannot trip the rule that forbids it.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
    return found


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Where the repository is, from this file."""
    return Path(__file__).resolve().parents[2]


def test_exactly_one_module_imports_the_signing_library(repo_root: Path) -> None:
    """A second importer is a second place a private key could be held."""
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): found
        for path in _package_modules(repo_root)
        if (found := _imports(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert set(offenders) == {PERMITTED}, (
        f"{GUARDED} may be named only in {PERMITTED}; found in {sorted(offenders)}"
    )


def test_the_permitted_module_actually_imports_it(repo_root: Path) -> None:
    """The other direction, which is what stops this rule going vacuous.

    A rule that only forbade extra importers would keep passing if the permitted
    one stopped importing anything — at which point the whole signing capability
    would be gone and this file would still be green.
    """
    path = repo_root / PACKAGE_RELATIVE_PATH / "adapters" / "signing.py"
    assert _imports(ast.parse(path.read_text(encoding="utf-8"))), (
        f"{PERMITTED} imports nothing from {GUARDED}; the asymmetric signers cannot work"
    )


def test_the_import_is_inside_a_function(repo_root: Path) -> None:
    """A module-scope import would make `globin.adapters` unimportable without it.

    The whole absent-safe arrangement rests on this: `import globin.adapters` must
    cost nothing on a host with no `cryptography`, which is every CI `quality` run.
    A top-level import would raise at import time, before any factory could return
    a stand-in.
    """
    path = repo_root / PACKAGE_RELATIVE_PATH / "adapters" / "signing.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom)) and _imports(node)
    ]
    assert not module_level, (
        f"{PERMITTED} imports {GUARDED} at module scope; it must be inside the factory so a "
        "host without the library can still import globin.adapters"
    )


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_no_pss_token_appears_as_code_anywhere_in_the_package(repo_root: Path, token: str) -> None:
    """The venue says it does not support PSS, so PSS is absent rather than unused.

    An absence is stronger than a branch: there is no argument, no setting and no
    conditional that could select it, so the only way to sign with PSS is to add
    the token — which fails here.
    """
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        for path in _package_modules(repo_root)
        if token in _code_names(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        f"{token!r} appears as code in {sorted(offenders)}; the venue documents that it does "
        "not support the PSS signature scheme"
    )


def test_the_checker_finds_a_case_it_must_catch() -> None:
    """Guard the guard, as `docs/TESTING_STRATEGY.md` requires of every checker here."""
    assert _imports(ast.parse("import cryptography")) == ["cryptography"]
    assert _imports(ast.parse("from cryptography.hazmat import primitives")) == [
        "cryptography.hazmat"
    ]
    assert _imports(ast.parse("from . import signing")) == []
    assert _imports(ast.parse("import hashlib")) == []
    assert "PSS" in _code_names(ast.parse("padding.PSS(mgf=None)"))
    assert "PSS" not in _code_names(ast.parse('"""PSS is not used here."""'))
    assert "PSS" not in _code_names(ast.parse('MESSAGE = "we do not use PSS"'))
