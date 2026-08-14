"""The use case that reviews GLOBIN's own layering.

This is a deliberately small service, and its size is the point. It fetches the
contract, fetches the import graph, and asks the domain model to judge them.
There is no parsing here, no file access, and no knowledge of TOML or of
Python's abstract syntax tree — those live in adapters, behind the ports this
service is given.

Read it as the worked example of the layering rule rather than as a feature:
every later use case in GLOBIN, from placing an order to promoting a model, has
this same shape.
"""

from dataclasses import dataclass

from globin.domain.architecture import ArchitectureReport
from globin.ports.architecture import ArchitectureContractSource, ModuleImportSource


@dataclass(frozen=True, slots=True)
class ArchitectureReview:
    """Checks an import graph against the declared architecture contract.

    Args:
        contract_source: Where the rules come from.
        module_source: Where the import graph comes from.

    Both are ports. Neither names a file, and swapping either for a fake
    requires no change here — which is what
    ``tests/architecture/test_architecture_contract.py`` relies on to prove the review can
    actually fail.
    """

    contract_source: ArchitectureContractSource
    module_source: ModuleImportSource

    def run(self) -> ArchitectureReport:
        """Review the import graph and report every breach of the contract.

        Returns:
            An :class:`~globin.domain.architecture.ArchitectureReport` listing
            forbidden imports and import cycles. An empty report means the
            source tree satisfies the contract.
        """
        contract = self.contract_source.load()
        return contract.review(self.module_source.modules())
