"""Filesystem-backed sources for the architecture review.

Two adapters live here. One reads the declared contract from TOML; the other
derives the import graph by parsing Python source. Both are the *only* reason
the architecture review touches a disk, which is exactly why they sit in this
layer rather than beside the use case that consumes them.

Malformed input raises :exc:`ValueError` with a message naming the offending
key. It is deliberately not a bespoke exception type: GLOBIN's error taxonomy
is designed in Phase 005, and inventing a competing hierarchy here is the
specific mistake ``ENGINEERING_CONTRACT.md`` warns against. What matters now is
that a broken contract file fails loudly rather than degrading into permissive
defaults — silent fallback is the failure mode
``ARCHITECTURE_PRINCIPLES.md`` principle 9 exists to prevent.
"""

import ast
import tomllib
from pathlib import Path

from globin.domain.architecture import (
    LAYER_ORDER,
    ArchitectureContract,
    Layer,
    LayerPolicy,
    ModuleImports,
)


class TomlArchitectureContractSource:
    """Loads the architecture contract from a TOML document.

    Args:
        path: Location of ``dependency-rules.toml``.

    TOML is parsed with the standard library's :mod:`tomllib`, so the contract
    costs no runtime dependency — which matters, because ADR-0003 makes the
    empty runtime dependency list an invariant rather than a default.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> ArchitectureContract:
        """Parse the contract document.

        Returns:
            The parsed :class:`~globin.domain.architecture.ArchitectureContract`.

        Raises:
            ValueError: If a required table or key is missing, has the wrong
                type, or names a layer the domain model does not define.
            OSError: If the document cannot be read.
        """
        with self._path.open("rb") as handle:
            document = tomllib.load(handle)

        where = str(self._path)
        meta = _table(document.get("meta"), f"{where}: [meta]")
        shared = _table(document.get("shared"), f"{where}: [shared]")
        io_table = _table(document.get("io"), f"{where}: [io]")
        layers = _table(document.get("layers"), f"{where}: [layers]")

        return ArchitectureContract(
            root_package=_text(meta.get("root_package"), f"{where}: meta.root_package"),
            policies=_policies(layers, where),
            shared_modules=frozenset(
                _text_tuple(shared.get("modules"), f"{where}: shared.modules")
            ),
            io_capable_modules=frozenset(
                _text_tuple(io_table.get("capable_modules"), f"{where}: io.capable_modules")
            ),
        )


class AstModuleImportSource:
    """Derives the import graph by parsing every module under a package root.

    Args:
        package_root: Directory holding the package, for example
            ``<repo>/src/globin``.
        root_package: The package's import name, for example ``globin``.

    Imports are read from the abstract syntax tree rather than by importing the
    modules. Importing them would execute them, which would make the check
    depend on the very import-time behaviour it is meant to police.
    """

    def __init__(self, package_root: Path, root_package: str) -> None:
        self._package_root = package_root
        self._root_package = root_package

    def modules(self) -> tuple[ModuleImports, ...]:
        """Parse every module beneath the package root.

        Returns:
            One :class:`~globin.domain.architecture.ModuleImports` per module,
            ordered by module name.

        Raises:
            SyntaxError: If a source file cannot be parsed. A file that does
                not parse is a defect; skipping it would hide whatever it
                imports.
            OSError: If a source file cannot be read.
        """
        found: list[ModuleImports] = []
        for path in sorted(self._package_root.rglob("*.py")):
            module = module_name(path, self._package_root, self._root_package)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found.append(
                ModuleImports(
                    module=module,
                    imported=extract_imports(tree, self._root_package),
                )
            )
        return tuple(sorted(found, key=lambda item: item.module))


def module_name(path: Path, package_root: Path, root_package: str) -> str:
    """Return the fully qualified module name of a source file.

    Args:
        path: The ``.py`` file.
        package_root: Directory holding the package.
        root_package: The package's import name.

    Returns:
        The dotted module name. A package's ``__init__.py`` resolves to the
        package itself rather than to a module called ``__init__``.
    """
    parts = list(path.relative_to(package_root).parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join([root_package, *parts])


def extract_imports(tree: ast.Module, root_package: str) -> tuple[str, ...]:
    """Return every module name imported anywhere in ``tree``.

    The whole tree is walked, so an import nested inside a function or inside
    an ``if TYPE_CHECKING:`` block counts exactly as much as one at the top.
    Both are genuine architectural dependencies, and treating either as invisible
    would leave a documented way to hide a violation.

    Args:
        tree: A parsed module.
        root_package: GLOBIN's own namespace. For ``from X import y`` where
            ``X`` is inside it, ``X.y`` is recorded as well, so that
            ``from globin import adapters`` is seen as reaching the adapters
            layer and not merely the root package.

    Returns:
        Sorted, deduplicated module names.

    Raises:
        ValueError: If a relative import is found. Relative imports are banned
            repository-wide by ``ban-relative-imports`` in ``pyproject.toml``,
            so one appearing here means the lint gate was bypassed.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(_import_from_targets(node, root_package))
    return tuple(sorted(names))


def _import_from_targets(node: ast.ImportFrom, root_package: str) -> tuple[str, ...]:
    if node.level:
        msg = (
            f"relative import found at line {node.lineno}; GLOBIN bans relative "
            f"imports repository-wide (pyproject.toml, ban-relative-imports)"
        )
        raise ValueError(msg)

    base = node.module
    if base is None:  # pragma: no cover - unreachable while level is 0
        return ()
    if base.split(".", 1)[0] != root_package:
        return (base,)
    return (base, *(f"{base}.{alias.name}" for alias in node.names))


def _policies(layers: dict[str, object], where: str) -> tuple[LayerPolicy, ...]:
    declared = {
        _layer(name, where): _table(body, f"{where}: [layers.{name}]")
        for name, body in layers.items()
    }
    missing = [layer.value for layer in LAYER_ORDER if layer not in declared]
    if missing:
        msg = f"{where}: [layers] does not declare {missing}"
        raise ValueError(msg)

    return tuple(
        LayerPolicy(
            layer=layer,
            package=_text(declared[layer].get("package"), f"{where}: layers.{layer.value}.package"),
            responsibility=_text(
                declared[layer].get("responsibility"),
                f"{where}: layers.{layer.value}.responsibility",
            ),
            may_import=frozenset(
                _layer(name, where)
                for name in _text_tuple(
                    declared[layer].get("may_import"), f"{where}: layers.{layer.value}.may_import"
                )
            ),
            may_perform_io=_flag(
                declared[layer].get("may_perform_io"),
                f"{where}: layers.{layer.value}.may_perform_io",
            ),
        )
        for layer in LAYER_ORDER
    )


def _layer(name: str, where: str) -> Layer:
    try:
        return Layer(name)
    except ValueError:
        known = sorted(layer.value for layer in Layer)
        msg = f"{where}: {name!r} is not a known layer; expected one of {known}"
        raise ValueError(msg) from None


def _table(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{where} is missing or is not a table"
        raise ValueError(msg)
    return {str(key): item for key, item in value.items()}


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{where} is missing or is not a non-empty string"
        raise ValueError(msg)
    return value


def _flag(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        msg = f"{where} is missing or is not a boolean"
        raise ValueError(msg)
    return value


def _text_tuple(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        msg = f"{where} is missing or is not a list of strings"
        raise ValueError(msg)
    return tuple(str(item) for item in value)
