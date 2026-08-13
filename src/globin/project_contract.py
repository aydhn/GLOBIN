"""Immutable project identity and policy constants for GLOBIN.

This module is deliberately the smallest possible executable surface for
Phase 1. Its purpose is to make the project's binding rules *testable* rather
than merely *documented*: every constant here is asserted by
``tests/test_project_contract.py``.

Nothing in this module performs I/O, networking, trading, or computation. It
must stay that way. Behavioural code belongs to the phases that own it (see
``ROADMAP.md``).

Why the values live in a frozen dataclass as well as module-level constants:

* The frozen, slotted :class:`ProjectContract` instance is the canonical
  record. Attempting to mutate it raises at runtime, so a later phase cannot
  quietly relax a policy by assignment.
* The module-level ``Final`` aliases exist because these names are referenced
  by the engineering contract itself and are the ergonomic import target for
  the rest of the codebase.

The two representations can never drift: the aliases are *derived* from the
instance, and a test asserts the correspondence.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ExchangeScope(StrEnum):
    """Exchanges GLOBIN is permitted to integrate with.

    Deliberately a single-member enumeration. GLOBIN targets Binance Global
    only (ADR-0002). The enum exists rather than a bare string so that adding
    a second venue becomes a visible, reviewable change to this type instead
    of an unnoticed string literal somewhere in a later phase.
    """

    BINANCE_GLOBAL = "BINANCE_GLOBAL"


@dataclass(frozen=True, slots=True)
class ProjectContract:
    """The non-negotiable facts about this project.

    Args:
        project_name: Human-facing project name.
        package_name: Python import namespace.
        required_git_branch: The only branch GLOBIN development may target.
        roadmap_total_phases: Total number of phases in the fixed roadmap.
        exchange_scope: The exchange GLOBIN is permitted to integrate with.
        paid_runtime_services_allowed: Whether the *runtime* may depend on paid
            services. Always ``False``; development tooling used by human or
            agent contributors is out of scope for this flag (ADR-0003).
        web_scraping_allowed: Whether GLOBIN may obtain data by scraping.
            Always ``False`` (ADR-0004).
    """

    project_name: str
    package_name: str
    required_git_branch: str
    roadmap_total_phases: int
    exchange_scope: ExchangeScope
    paid_runtime_services_allowed: bool
    web_scraping_allowed: bool


CONTRACT: Final[ProjectContract] = ProjectContract(
    project_name="GLOBIN",
    package_name="globin",
    required_git_branch="master",
    roadmap_total_phases=320,
    exchange_scope=ExchangeScope.BINANCE_GLOBAL,
    paid_runtime_services_allowed=False,
    web_scraping_allowed=False,
)

PROJECT_NAME: Final[str] = CONTRACT.project_name
PACKAGE_NAME: Final[str] = CONTRACT.package_name
REQUIRED_GIT_BRANCH: Final[str] = CONTRACT.required_git_branch
ROADMAP_TOTAL_PHASES: Final[int] = CONTRACT.roadmap_total_phases
EXCHANGE_SCOPE: Final[ExchangeScope] = CONTRACT.exchange_scope
PAID_RUNTIME_SERVICES_ALLOWED: Final[bool] = CONTRACT.paid_runtime_services_allowed
WEB_SCRAPING_ALLOWED: Final[bool] = CONTRACT.web_scraping_allowed
