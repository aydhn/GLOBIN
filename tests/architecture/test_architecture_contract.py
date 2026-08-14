"""Enforce the architecture contract declared in `docs/architecture/dependency-rules.toml`.

Layering rules decay quietly. Nothing breaks the day a domain module imports an
HTTP client — it breaks eighteen months later, when the core can no longer be
tested without a network and nobody remembers deciding that. These tests exist
so the decay is a failing build rather than an archaeology exercise.

Three properties are worth stating, because each is a way this file could look
useful while proving nothing:

* **The contract file is the only statement of the matrix.** No second copy of
  "domain may import nothing" is hard-coded below. The tests read the TOML and
  check the real import graph against it, so amending the contract is a visible
  edit to one file rather than a hunt through assertions.
* **Imports are read from the syntax tree, not by importing.** Importing the
  modules would execute them, and one of the rules under test is that importing
  executes nothing.
* **The checker's failing case is exercised.** A boundary test that has never
  failed is indistinguishable from one that cannot. The synthetic-violation
  tests below are the same guard `test_link_checker_detects_a_broken_link`
  applies to the Markdown link checker.

Test names name the rule that broke, so a failure line in CI output is already
the diagnosis.
"""

import ast
import importlib
import re
import tomllib
from pathlib import Path

import pytest

from globin.adapters.architecture import (
    AstModuleImportSource,
    TomlArchitectureContractSource,
    extract_imports,
    module_name,
)
from globin.application.architecture_review import ArchitectureReview
from globin.domain.architecture import (
    LAYER_ORDER,
    ArchitectureContract,
    ArchitectureReport,
    Layer,
    ModuleImports,
)
from globin.runtime.composition import (
    CONTRACT_RELATIVE_PATH,
    PACKAGE_RELATIVE_PATH,
    ROOT_PACKAGE,
    build_architecture_review,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def contract(repo_root: Path) -> ArchitectureContract:
    """The declared architecture contract."""
    return TomlArchitectureContractSource(repo_root / CONTRACT_RELATIVE_PATH).load()


@pytest.fixture(scope="session")
def modules(repo_root: Path) -> tuple[ModuleImports, ...]:
    """Every module in the package, with what each imports."""
    return AstModuleImportSource(repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE).modules()


@pytest.fixture(scope="session")
def report(repo_root: Path) -> ArchitectureReport:
    """The review of this repository, wired by the composition root."""
    return build_architecture_review(repo_root).run()


def _imports_of(modules: tuple[ModuleImports, ...], package: str) -> list[tuple[str, str]]:
    """Return every (module, imported) pair for modules inside ``package``."""
    return [
        (item.module, imported)
        for item in modules
        if item.module == package or item.module.startswith(f"{package}.")
        for imported in item.imported
    ]


# --------------------------------------------------------------------------
# The contract itself
# --------------------------------------------------------------------------


def test_the_dependency_contract_declares_a_policy_for_every_layer(
    contract: ArchitectureContract,
) -> None:
    declared = [policy.layer for policy in contract.policies]
    assert declared == list(LAYER_ORDER)
    assert contract.root_package == ROOT_PACKAGE


def test_the_declared_layers_match_the_domain_layer_enumeration(repo_root: Path) -> None:
    """The contract file and `Layer` are the one sanctioned copy — compare them.

    `docs/engineering/SOURCE_OF_TRUTH.md` permits a duplicated value only where a
    test fails when the copies diverge. This is that test. Without it, adding a
    layer to the TOML and forgetting the enum would silently leave the new layer
    ungoverned.
    """
    with (repo_root / CONTRACT_RELATIVE_PATH).open("rb") as handle:
        document = tomllib.load(handle)
    assert set(document["layers"]) == {layer.value for layer in Layer}


def test_every_declared_layer_package_exists_in_the_source_tree(
    repo_root: Path, contract: ArchitectureContract
) -> None:
    package_root = repo_root / PACKAGE_RELATIVE_PATH
    missing = [
        policy.package
        for policy in contract.policies
        if not (
            package_root / policy.package.removeprefix(f"{ROOT_PACKAGE}.") / "__init__.py"
        ).is_file()
    ]
    assert not missing, f"declared layers with no package on disk: {missing}"


def test_the_declared_dependency_direction_is_acyclic(contract: ArchitectureContract) -> None:
    """A layer may only depend on layers declared before it.

    The direction is what makes the architecture worth having. If the contract
    itself permitted a loop, every downstream test would still pass while the
    rule meant nothing.
    """
    for position, layer in enumerate(LAYER_ORDER):
        inner = set(LAYER_ORDER[:position])
        outward = contract.policy_for(layer).may_import - inner
        assert not outward, (
            f"{layer.value!r} may import {sorted(item.value for item in outward)}, "
            f"which is not strictly inward of it"
        )


# --------------------------------------------------------------------------
# The real import graph
# --------------------------------------------------------------------------


def test_the_source_tree_satisfies_the_architecture_contract(report: ArchitectureReport) -> None:
    """The general check. The named rules below exist for better failure messages."""
    detail = "\n  ".join(
        f"{item.module} -> {item.imported}: {item.rule}" for item in report.violations
    )
    assert not report.violations, f"architecture boundary violations:\n  {detail}"


def test_domain_imports_no_outer_layer(
    contract: ArchitectureContract, modules: tuple[ModuleImports, ...]
) -> None:
    offenders = [
        f"{module} -> {imported}"
        for module, imported in _imports_of(modules, contract.policy_for(Layer.DOMAIN).package)
        if contract.layer_of(imported) not in (None, Layer.DOMAIN)
    ]
    assert not offenders, f"domain must depend on no other layer: {offenders}"


def test_ports_imports_neither_adapters_nor_runtime(
    contract: ArchitectureContract, modules: tuple[ModuleImports, ...]
) -> None:
    forbidden = {Layer.ADAPTERS, Layer.RUNTIME}
    offenders = [
        f"{module} -> {imported}"
        for module, imported in _imports_of(modules, contract.policy_for(Layer.PORTS).package)
        if contract.layer_of(imported) in forbidden
    ]
    assert not offenders, f"a port must not know who implements it: {offenders}"


def test_application_does_not_import_a_concrete_adapter(
    contract: ArchitectureContract, modules: tuple[ModuleImports, ...]
) -> None:
    forbidden = {Layer.ADAPTERS, Layer.RUNTIME}
    offenders = [
        f"{module} -> {imported}"
        for module, imported in _imports_of(modules, contract.policy_for(Layer.APPLICATION).package)
        if contract.layer_of(imported) in forbidden
    ]
    assert not offenders, f"a use case must depend on ports, not implementations: {offenders}"


def test_inner_layers_import_no_io_capable_module(
    contract: ArchitectureContract, modules: tuple[ModuleImports, ...]
) -> None:
    """Domain, ports and application must stay runnable without the world."""
    offenders: list[str] = []
    for policy in contract.policies:
        if policy.may_perform_io:
            continue
        offenders.extend(
            f"{policy.layer.value}: {module} -> {imported}"
            for module, imported in _imports_of(modules, policy.package)
            if imported.split(".", 1)[0] in contract.io_capable_modules
        )
    assert not offenders, f"inner layers must perform no I/O: {offenders}"


def test_shared_policy_modules_import_no_layer(
    contract: ArchitectureContract, modules: tuple[ModuleImports, ...]
) -> None:
    """The shared-to-layer relationship must stay one-way.

    `project_contract` and `roadmap` sit above the stack so any layer may read
    them. That only remains safe while they read nothing back — otherwise they
    become a covert channel between layers that the direction rules never see.
    """
    offenders = [
        f"{item.module} -> {imported}"
        for item in modules
        if item.module in contract.shared_modules
        for imported in item.imported
        if contract.layer_of(imported) is not None
    ]
    assert not offenders, f"shared policy modules must import no layer: {offenders}"


def test_there_is_no_import_cycle_inside_the_package(report: ArchitectureReport) -> None:
    detail = ["  " + " -> ".join([*cycle, cycle[0]]) for cycle in report.cycles]
    assert not report.cycles, "import cycles found:\n" + "\n".join(detail)


# --------------------------------------------------------------------------
# Import-time behaviour
# --------------------------------------------------------------------------


def _calls_executed_at_import(body: list[ast.stmt]) -> list[str]:
    """Return the calls a module would evaluate merely by being imported.

    Function bodies are skipped because they run only when called. Decorator
    lists are skipped because `@dataclass(frozen=True)` is unavoidable and
    inert. Class bodies and `if TYPE_CHECKING:` blocks *are* followed, because
    both execute at import.
    """
    calls: list[str] = []
    for statement in body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if isinstance(statement, ast.ClassDef):
            calls.extend(_calls_executed_at_import(statement.body))
        elif isinstance(statement, ast.If):
            calls.extend(_expression_calls(statement.test))
            calls.extend(_calls_executed_at_import(statement.body))
            calls.extend(_calls_executed_at_import(statement.orelse))
        else:
            calls.extend(_expression_calls(statement))
    return calls


def _expression_calls(node: ast.AST) -> list[str]:
    return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]


def test_layer_modules_execute_no_work_when_imported(
    repo_root: Path, contract: ArchitectureContract
) -> None:
    """Importing a layer must not open a file, build a client or start a thread.

    A blanket "no calls at module level" is stricter than the rule it stands
    for, and deliberately so: deciding whether an arbitrary call reaches the
    outside world is undecidable, whereas this is exact. It applies to the layer
    packages only — `project_contract` and `roadmap` predate the rule and build
    their frozen constants at import, which is inert but would trip it.
    """
    offenders: list[str] = []
    for policy in contract.policies:
        directory = (
            repo_root / PACKAGE_RELATIVE_PATH / policy.package.removeprefix(f"{ROOT_PACKAGE}.")
        )
        for path in sorted(directory.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)}: {call}()"
                for call in _calls_executed_at_import(tree.body)
            )
    assert not offenders, f"work performed at import time: {offenders}"


def test_the_import_time_check_notices_work() -> None:
    """Guard the checker above: a validator whose negative case is never run rots."""
    assert _calls_executed_at_import(ast.parse("import json\nD = json.loads('{}')\n").body) == [
        "json.loads"
    ]
    assert _calls_executed_at_import(ast.parse("def f():\n    return open('x')\n").body) == []
    assert _calls_executed_at_import(ast.parse("class A:\n    B = dict()\n").body) == ["dict"]


def test_every_layer_package_imports_cleanly_and_states_its_responsibility(
    contract: ArchitectureContract,
) -> None:
    for policy in contract.policies:
        module = importlib.import_module(policy.package)
        assert module.__doc__, f"{policy.package} does not document what it is for"


# --------------------------------------------------------------------------
# The review can fail
# --------------------------------------------------------------------------


class _FixedContract:
    """A contract source returning whatever the test chose.

    A helper class rather than a test class: it exists to satisfy
    `ArchitectureContractSource` structurally, which is what proves the port is
    a real seam and not decoration.
    """

    def __init__(self, contract: ArchitectureContract) -> None:
        self._contract = contract

    def load(self) -> ArchitectureContract:
        return self._contract


class _FixedModules:
    """A module source returning a synthetic import graph."""

    def __init__(self, modules: tuple[ModuleImports, ...]) -> None:
        self._modules = modules

    def modules(self) -> tuple[ModuleImports, ...]:
        return self._modules


def _review(contract: ArchitectureContract, graph: tuple[ModuleImports, ...]) -> ArchitectureReport:
    return ArchitectureReview(_FixedContract(contract), _FixedModules(graph)).run()


def test_the_review_reports_an_inward_boundary_breach(contract: ArchitectureContract) -> None:
    result = _review(
        contract,
        (ModuleImports("globin.domain.invented", ("globin.adapters.invented",)),),
    )
    assert [item.imported for item in result.violations] == ["globin.adapters.invented"]
    assert "not 'adapters'" in result.violations[0].rule
    assert not result.is_clean


def test_the_review_reports_io_reaching_an_inner_layer(contract: ArchitectureContract) -> None:
    result = _review(contract, (ModuleImports("globin.application.invented", ("socket",)),))
    assert [item.rule for item in result.violations] == ["'application' must perform no I/O"]


def test_the_review_reports_an_import_cycle(contract: ArchitectureContract) -> None:
    result = _review(
        contract,
        (
            ModuleImports("globin.adapters.one", ("globin.adapters.two",)),
            ModuleImports("globin.adapters.two", ("globin.adapters.one",)),
        ),
    )
    assert result.cycles == (("globin.adapters.one", "globin.adapters.two"),)
    assert not result.is_clean


def test_the_review_reports_a_shared_module_reaching_into_a_layer(
    contract: ArchitectureContract,
) -> None:
    """The shared-to-layer rule needs its own negative case.

    In the real tree the shared modules import no layer, so this branch would
    otherwise never execute — and an unexercised check is indistinguishable
    from a broken one.
    """
    result = _review(
        contract,
        (ModuleImports("globin.project_contract", ("globin.domain.invented",)),),
    )
    assert [item.imported for item in result.violations] == ["globin.domain.invented"]
    assert "shared policy module must import no layer" in result.violations[0].rule


def test_policy_lookup_refuses_a_layer_the_contract_does_not_govern() -> None:
    """A missing policy must raise, never fall back to something permissive.

    Falling back would mean a layer dropped from the contract file silently
    became unrestricted — the exact opposite of what removing its rules should
    do.
    """
    ungoverned = ArchitectureContract(
        root_package=ROOT_PACKAGE,
        policies=(),
        shared_modules=frozenset(),
        io_capable_modules=frozenset(),
    )
    with pytest.raises(KeyError, match="no policy for layer"):
        ungoverned.policy_for(Layer.DOMAIN)


def test_the_review_permits_the_declared_direction(contract: ArchitectureContract) -> None:
    """The checker must also stay quiet about legitimate imports."""
    result = _review(
        contract,
        (
            ModuleImports("globin.runtime.invented", ("globin.adapters.invented", "pathlib")),
            ModuleImports("globin.adapters.invented", ("globin.ports.invented", "tomllib")),
            ModuleImports("globin.ports.invented", ("globin.domain.invented",)),
            ModuleImports("globin.domain.invented", ("dataclasses", "globin.project_contract")),
        ),
    )
    assert result.is_clean


# --------------------------------------------------------------------------
# The import extractor
# --------------------------------------------------------------------------


def test_import_extraction_covers_every_import_form() -> None:
    """Each form below is a way a dependency could otherwise become invisible."""
    source = (
        "import json\n"
        "import os.path\n"
        "from typing import TYPE_CHECKING\n"
        "from globin import adapters\n"
        "from globin.domain.architecture import Layer\n"
        "if TYPE_CHECKING:\n"
        "    from globin.runtime.composition import build_architecture_review\n"
        "def f() -> None:\n"
        "    import sqlite3\n"
    )
    extracted = extract_imports(ast.parse(source), ROOT_PACKAGE)
    assert "json" in extracted
    assert "os.path" in extracted
    assert "sqlite3" in extracted, "an import inside a function is still a dependency"
    assert "globin.adapters" in extracted, "`from globin import adapters` reaches a layer"
    assert "globin.domain.architecture" in extracted
    assert "globin.runtime.composition" in extracted, "a TYPE_CHECKING import is still a dependency"


def test_import_extraction_rejects_a_relative_import() -> None:
    """Relative imports are banned by lint; the extractor must not quietly ignore one."""
    with pytest.raises(ValueError, match="relative import"):
        extract_imports(ast.parse("from . import sibling\n"), ROOT_PACKAGE)


def test_module_name_resolves_packages_and_modules(repo_root: Path) -> None:
    package_root = repo_root / PACKAGE_RELATIVE_PATH
    assert module_name(package_root / "__init__.py", package_root, ROOT_PACKAGE) == "globin"
    assert (
        module_name(package_root / "domain" / "__init__.py", package_root, ROOT_PACKAGE)
        == "globin.domain"
    )
    assert (
        module_name(package_root / "domain" / "architecture.py", package_root, ROOT_PACKAGE)
        == "globin.domain.architecture"
    )


# --------------------------------------------------------------------------
# Contract loading refuses to guess
# --------------------------------------------------------------------------


def _contract_document(*layers: Layer) -> str:
    """Build the smallest contract document declaring exactly ``layers``."""
    tables = "\n".join(
        f"[layers.{layer.value}]\n"
        f'package = "globin.{layer.value}"\n'
        f'responsibility = "Declared for this test."\n'
        f"may_import = []\n"
        f"may_perform_io = false\n"
        for layer in layers
    )
    return (
        '[meta]\nroot_package = "globin"\n\n'
        "[shared]\nmodules = []\n\n"
        '[io]\ncapable_modules = ["os"]\n\n' + tables
    )


def _write_contract(tmp_path: Path, text: str) -> TomlArchitectureContractSource:
    path = tmp_path / "dependency-rules.toml"
    path.write_text(text, encoding="utf-8")
    return TomlArchitectureContractSource(path)


def test_a_minimal_contract_loads(tmp_path: Path) -> None:
    """Guard the two negative cases below: they must fail for the reason claimed."""
    loaded = _write_contract(tmp_path, _contract_document(*LAYER_ORDER)).load()
    assert [policy.layer for policy in loaded.policies] == list(LAYER_ORDER)


def test_contract_loading_rejects_an_unknown_layer(tmp_path: Path) -> None:
    """A layer nobody governs must not be creatable by editing one file."""
    text = _contract_document(*LAYER_ORDER) + '\n[layers.persistence]\npackage = "x"\n'
    with pytest.raises(ValueError, match="is not a known layer"):
        _write_contract(tmp_path, text).load()


def test_contract_loading_rejects_a_missing_layer(tmp_path: Path) -> None:
    """Deleting a layer's rules must fail loudly, not leave that layer unchecked."""
    remaining = tuple(layer for layer in LAYER_ORDER if layer is not Layer.PORTS)
    with pytest.raises(ValueError, match="does not declare"):
        _write_contract(tmp_path, _contract_document(*remaining)).load()


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('root_package = "globin"', "root_package = 12", "meta.root_package"),
        ('[meta]\nroot_package = "globin"', "[meta]", "meta.root_package"),
        ("modules = []", 'modules = "globin.roadmap"', "shared.modules"),
        ('capable_modules = ["os"]', "capable_modules = [1]", "io.capable_modules"),
        ("may_perform_io = false", 'may_perform_io = "no"', "may_perform_io is missing"),
        ('package = "globin.domain"', "package = []", "layers.domain.package"),
        ("[shared]\nmodules = []\n", "", "[shared] is missing or is not a table"),
    ],
)
def test_contract_loading_refuses_malformed_input(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    """Every field is validated, because a permissive default disables a rule silently.

    ``ARCHITECTURE_PRINCIPLES.md`` principle 9: explicit refusal beats silent
    fallback. A contract that half-loads is worse than one that fails, because
    the build stays green while part of the architecture goes unchecked.
    """
    text = _contract_document(*LAYER_ORDER).replace(old, new, 1)
    with pytest.raises(ValueError, match=re.escape(expected)):
        _write_contract(tmp_path, text).load()
