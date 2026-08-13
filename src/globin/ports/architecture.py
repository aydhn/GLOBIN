"""Ports for reviewing GLOBIN's own architecture.

Two things must come from outside the core to review an import graph: the
contract, which lives in a TOML file, and the graph itself, which lives in
Python source. Both are filesystem reads, so both are expressed here as
contracts and implemented in :mod:`globin.adapters.architecture`.

The split is not ceremony. It is what lets
``tests/test_architecture_contract.py`` feed the review a synthetic graph
containing a deliberate violation and confirm the checker reports it. A checker
whose failing case is never exercised tends to quietly stop matching anything —
the repository already guards its Markdown link checker the same way.
"""

from typing import Protocol

from globin.domain.architecture import ArchitectureContract, ModuleImports


class ArchitectureContractSource(Protocol):
    """Supplies the rules that govern dependencies between layers."""

    def load(self) -> ArchitectureContract:
        """Return the current architecture contract.

        Returns:
            The parsed :class:`~globin.domain.architecture.ArchitectureContract`.
        """
        ...


class ModuleImportSource(Protocol):
    """Supplies the import graph of a body of Python source."""

    def modules(self) -> tuple[ModuleImports, ...]:
        """Return every module found, with the modules each one imports.

        Returns:
            One :class:`~globin.domain.architecture.ModuleImports` per module,
            ordered by module name so that a review is reproducible.
        """
        ...
