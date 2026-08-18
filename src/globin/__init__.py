"""GLOBIN — engineering foundation for a local autonomous Binance Global system.

**Maturity: Phase 32 of 320. This package does not trade.**

There is no networking, no authentication, no market-data ingestion, no
strategy, no backtesting and no machine learning in this package. The phases
completed so far establish the repository, the engineering contract and the
verification backbone that every later phase is built on. Anything that talks
to an exchange belongs to Phase 33 and beyond (see ``ROADMAP.md``).

What this package *does* provide is the project's binding rules in executable
form, so that automated checks can enforce them:

* :mod:`globin.project_contract` — identity and policy invariants.
* :mod:`globin.roadmap` — the immutable 320-phase band structure.
* :mod:`globin.errors` — the error taxonomy every layer raises through.
"""

from globin.errors import (
    ConfigurationError,
    ExchangeError,
    FaultDomain,
    GlobinError,
    InternalError,
    TransportError,
    ValidationError,
)
from globin.project_contract import (
    CONTRACT,
    EXCHANGE_SCOPE,
    PACKAGE_NAME,
    PAID_RUNTIME_SERVICES_ALLOWED,
    PROJECT_NAME,
    REQUIRED_GIT_BRANCH,
    ROADMAP_TOTAL_PHASES,
    WEB_SCRAPING_ALLOWED,
    ExchangeScope,
    ProjectContract,
)
from globin.roadmap import PHASE_BAND_WIDTH, PHASE_BANDS, PhaseBand, band_for_phase

__version__ = "0.2.0"

__all__ = [
    "CONTRACT",
    "EXCHANGE_SCOPE",
    "PACKAGE_NAME",
    "PAID_RUNTIME_SERVICES_ALLOWED",
    "PHASE_BANDS",
    "PHASE_BAND_WIDTH",
    "PROJECT_NAME",
    "REQUIRED_GIT_BRANCH",
    "ROADMAP_TOTAL_PHASES",
    "WEB_SCRAPING_ALLOWED",
    "ConfigurationError",
    "ExchangeError",
    "ExchangeScope",
    "FaultDomain",
    "GlobinError",
    "InternalError",
    "PhaseBand",
    "ProjectContract",
    "TransportError",
    "ValidationError",
    "__version__",
    "band_for_phase",
]
