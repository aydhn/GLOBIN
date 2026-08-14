"""The architecture contract, modelled as pure domain types.

GLOBIN's layering rule is stated in prose in ``docs/architecture/README.md``
and declared as data in ``docs/architecture/dependency-rules.toml``. This
module is the third form: the rule as *behaviour*, so that deciding whether a
particular import is permitted is a function call rather than a judgement.

Why the rule is modelled here rather than inside the test that enforces it:
``ARCHITECTURE_PRINCIPLES.md`` principle 10 requires policy to be executable
where it can be, and Phase 001 set the precedent with
:mod:`globin.project_contract`. A rule that lives only inside a test is
reachable only by that test.

Nothing in this module performs I/O. It is handed data — a parsed contract and
an already-extracted import graph — and returns findings. Reading the TOML file
and parsing Python source are adapter concerns.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Layer(StrEnum):
    """The architectural layers, ordered from innermost to outermost.

    Deliberately duplicated: the same five names are declared in
    ``docs/architecture/dependency-rules.toml``, and
    ``tests/architecture/test_architecture_contract.py`` compares the two. That is the only
    form of duplication ``docs/engineering/SOURCE_OF_TRUTH.md`` permits — a
    copy with a test that fails when the copies diverge.

    The copy earns its place the same way :class:`globin.project_contract.ExchangeScope`
    does: introducing a sixth layer becomes a visible change to a type, not a
    new string appearing in a configuration file.
    """

    DOMAIN = "domain"
    PORTS = "ports"
    APPLICATION = "application"
    ADAPTERS = "adapters"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class LayerPolicy:
    """What one layer is permitted to depend on.

    Args:
        layer: The layer this policy governs.
        package: Its fully qualified package name, for example ``globin.domain``.
        responsibility: One sentence describing what the layer is for.
        may_import: Layers this one may depend on. A layer may always use
            itself; that is not recorded here.
        may_perform_io: Whether the layer may import an I/O-capable module.
    """

    layer: Layer
    package: str
    responsibility: str
    may_import: frozenset[Layer]
    may_perform_io: bool


@dataclass(frozen=True, slots=True)
class ModuleImports:
    """Every module one source file imports.

    Args:
        module: Fully qualified name of the importing module.
        imported: Fully qualified names of the modules it imports, sorted and
            deduplicated so that a review is reproducible.

    Imports written inside an ``if TYPE_CHECKING:`` block are included. They
    are real architectural dependencies: a module that needs a type from
    another layer is coupled to it whether or not the import survives to
    runtime, and excluding them would let a violation hide behind a forward
    reference.
    """

    module: str
    imported: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryViolation:
    """One import that the contract forbids.

    Args:
        module: The module containing the offending import.
        imported: What it imported.
        rule: The broken rule, phrased so the failure message explains itself
            without the reader consulting the contract.
    """

    module: str
    imported: str
    rule: str


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    """The outcome of reviewing an import graph against a contract.

    Args:
        violations: Forbidden imports, ordered deterministically.
        cycles: Import cycles, each given as the modules forming the loop.
    """

    violations: tuple[BoundaryViolation, ...]
    cycles: tuple[tuple[str, ...], ...]

    @property
    def is_clean(self) -> bool:
        """Whether the graph satisfies the contract completely."""
        return not self.violations and not self.cycles


@dataclass(frozen=True, slots=True)
class ArchitectureContract:
    """The complete set of rules governing dependencies inside GLOBIN.

    Args:
        root_package: The distribution's import namespace, ``globin``.
        policies: One policy per layer.
        shared_modules: Modules that sit above the layer stack and may be read
            by any layer. They must themselves import no layer.
        io_capable_modules: Top-level standard library packages whose import
            signals that a module can reach outside its own process.
    """

    root_package: str
    policies: tuple[LayerPolicy, ...]
    shared_modules: frozenset[str]
    io_capable_modules: frozenset[str]

    def layer_of(self, module: str) -> Layer | None:
        """Return the layer owning ``module``, or ``None`` if it owns none.

        A module belongs to a layer when it *is* the layer package or lives
        beneath it. ``globin`` itself and the shared policy modules belong to
        no layer, and that is not an error — it is what lets them be imported
        from anywhere.

        Args:
            module: A fully qualified module name.

        Returns:
            The owning :class:`Layer`, or ``None``.
        """
        for policy in self.policies:
            if module == policy.package or module.startswith(f"{policy.package}."):
                return policy.layer
        return None

    def policy_for(self, layer: Layer) -> LayerPolicy:
        """Return the policy governing ``layer``.

        Args:
            layer: The layer to look up.

        Returns:
            Its :class:`LayerPolicy`.

        Raises:
            KeyError: If the contract declares no policy for ``layer``. A
                missing policy is a defect in the contract file, not a reason
                to fall back to a permissive default.
        """
        for policy in self.policies:
            if policy.layer is layer:
                return policy
        msg = f"contract declares no policy for layer {layer.value!r}"
        raise KeyError(msg)

    def violations_in(self, module_imports: ModuleImports) -> tuple[BoundaryViolation, ...]:
        """Return every import in ``module_imports`` that this contract forbids.

        Three rules are applied:

        1. A shared policy module may import no layer, keeping the
           shared-to-layer relationship one-way.
        2. A layer may import only the layers its policy names.
        3. A layer whose policy denies I/O may import no I/O-capable module.

        Args:
            module_imports: One module and everything it imports.

        Returns:
            The violations, in the order the imports were given.
        """
        if module_imports.module in self.shared_modules:
            return self._shared_module_violations(module_imports)

        layer = self.layer_of(module_imports.module)
        if layer is None:
            return ()

        policy = self.policy_for(layer)
        found: list[BoundaryViolation] = []
        for imported in module_imports.imported:
            found.extend(self._violations_for_import(module_imports.module, imported, policy))
        return tuple(found)

    def review(self, modules: Sequence[ModuleImports]) -> ArchitectureReport:
        """Review a whole import graph against this contract.

        Args:
            modules: Every module in the graph and what each imports.

        Returns:
            An :class:`ArchitectureReport`. Violations are sorted by module and
            then by import so that two runs over the same tree report
            identically — ``ENGINEERING_CONTRACT.md`` invariant 3.
        """
        violations = [violation for module in modules for violation in self.violations_in(module)]
        violations.sort(key=lambda item: (item.module, item.imported, item.rule))
        return ArchitectureReport(
            violations=tuple(violations),
            cycles=import_cycles(modules, self.root_package),
        )

    def _shared_module_violations(
        self, module_imports: ModuleImports
    ) -> tuple[BoundaryViolation, ...]:
        found: list[BoundaryViolation] = []
        for imported in module_imports.imported:
            layer = self.layer_of(imported)
            if layer is not None:
                found.append(
                    BoundaryViolation(
                        module=module_imports.module,
                        imported=imported,
                        rule=(
                            f"shared policy module must import no layer, "
                            f"but imports {layer.value!r}"
                        ),
                    )
                )
        return tuple(found)

    def _violations_for_import(
        self, module: str, imported: str, policy: LayerPolicy
    ) -> tuple[BoundaryViolation, ...]:
        target = self.layer_of(imported)
        if target is not None:
            if target is policy.layer or target in policy.may_import:
                return ()
            return (
                BoundaryViolation(
                    module=module,
                    imported=imported,
                    rule=(
                        f"{policy.layer.value!r} may import "
                        f"{sorted(item.value for item in policy.may_import)}, "
                        f"not {target.value!r}"
                    ),
                ),
            )

        if not policy.may_perform_io and top_level_package(imported) in self.io_capable_modules:
            return (
                BoundaryViolation(
                    module=module,
                    imported=imported,
                    rule=f"{policy.layer.value!r} must perform no I/O",
                ),
            )
        return ()


def top_level_package(module: str) -> str:
    """Return the first dotted component of ``module``.

    Args:
        module: A fully qualified module name such as ``urllib.request``.

    Returns:
        Its top-level package, ``urllib`` for the example above.
    """
    return module.split(".", 1)[0]


def import_cycles(
    modules: Iterable[ModuleImports], root_package: str
) -> tuple[tuple[str, ...], ...]:
    """Find import cycles among the project's own modules.

    Only edges between modules present in ``modules`` are followed. An import
    of a third-party or standard library module cannot participate in a cycle
    within GLOBIN, and an import of a module that was not scanned cannot be
    verified either way.

    Args:
        modules: The import graph.
        root_package: Namespace outside which edges are ignored.

    Returns:
        Each cycle as a tuple of module names, rotated so that the
        alphabetically smallest module comes first and sorted overall, so the
        result is stable across runs.
    """
    graph = _own_edges(modules, root_package)
    cycles: set[tuple[str, ...]] = set()
    finished: set[str] = set()
    path: list[str] = []
    on_path: set[str] = set()

    def visit(node: str) -> None:
        path.append(node)
        on_path.add(node)
        for neighbour in graph.get(node, ()):
            if neighbour in on_path:
                cycles.add(_normalise_cycle(path[path.index(neighbour) :]))
            elif neighbour not in finished:
                visit(neighbour)
        on_path.discard(node)
        path.pop()
        finished.add(node)

    for module in sorted(graph):
        if module not in finished:
            visit(module)
    return tuple(sorted(cycles))


def _own_edges(
    modules: Iterable[ModuleImports], root_package: str
) -> Mapping[str, tuple[str, ...]]:
    """Restrict the graph to edges between scanned modules inside ``root_package``."""
    known = {item.module for item in modules if top_level_package(item.module) == root_package}
    return {
        item.module: tuple(target for target in item.imported if target in known)
        for item in modules
        if item.module in known
    }


def _normalise_cycle(cycle: Sequence[str]) -> tuple[str, ...]:
    """Rotate ``cycle`` so it starts at its smallest member.

    The same loop discovered from two different entry points is one cycle, not
    two. Rotating to a canonical starting point makes the set deduplicate it.
    """
    start = cycle.index(min(cycle))
    return tuple(cycle[start:]) + tuple(cycle[:start])


LAYER_ORDER: Final[tuple[Layer, ...]] = (
    Layer.DOMAIN,
    Layer.PORTS,
    Layer.APPLICATION,
    Layer.ADAPTERS,
    Layer.RUNTIME,
)
"""The layers from innermost to outermost, for reporting and documentation."""
