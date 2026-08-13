"""The innermost architectural layer: pure concepts, values and rules.

**May import:** nothing else in ``globin`` except the shared policy modules
``globin.project_contract`` and ``globin.roadmap``.

**May not import:** :mod:`globin.ports`, :mod:`globin.application`,
:mod:`globin.adapters`, :mod:`globin.runtime`, or any I/O-capable standard
library module.

A domain module must be describable without mentioning Binance, HTTP, Windows,
a database or a file. If explaining one requires naming a technology, it
belongs in an outer layer. The permitted set is declared in
``docs/architecture/dependency-rules.toml`` and enforced by
``tests/test_architecture_contract.py``.

This package deliberately re-exports nothing. Importing
:mod:`globin.domain.architecture` directly keeps the dependency visible in the
importing module, which is what the boundary tests read.
"""
