"""Verify the executable project identity and policy invariants.

Every assertion here corresponds to a rule stated in ``docs/PROJECT_CHARTER.md``
and the ADRs. If a later phase wants to change one of these values, the change
must be deliberate enough to also edit this file — which is the point.
"""

import re
from dataclasses import FrozenInstanceError

import pytest

import globin
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
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-]?(a|b|rc|dev|post)\d+)?$")


def test_package_imports() -> None:
    """The `globin` package must import cleanly with no side effects."""
    assert globin is not None


def test_version_is_declared_and_well_formed() -> None:
    assert VERSION_RE.match(globin.__version__), (
        f"__version__ {globin.__version__!r} is not a recognisable version string"
    )


def test_project_name_is_globin() -> None:
    assert PROJECT_NAME == "GLOBIN"


def test_package_name_is_globin() -> None:
    assert PACKAGE_NAME == "globin"
    assert globin.__name__ == PACKAGE_NAME


def test_required_git_branch_is_master() -> None:
    """Master-only workflow (ADR-0005). No other branch is a valid target."""
    assert REQUIRED_GIT_BRANCH == "master"


def test_roadmap_total_phases_is_320() -> None:
    assert ROADMAP_TOTAL_PHASES == 320


def test_exchange_scope_is_binance_global() -> None:
    """Binance Global only (ADR-0002)."""
    assert EXCHANGE_SCOPE is ExchangeScope.BINANCE_GLOBAL
    assert EXCHANGE_SCOPE == "BINANCE_GLOBAL"


def test_exactly_one_exchange_is_in_scope() -> None:
    """Adding a venue must be a visible change to the enum, not a stray string."""
    assert len(ExchangeScope) == 1


def test_paid_runtime_services_are_prohibited() -> None:
    """Zero-budget runtime (ADR-0003)."""
    assert PAID_RUNTIME_SERVICES_ALLOWED is False


def test_web_scraping_is_prohibited() -> None:
    """Official documented interfaces only (ADR-0004)."""
    assert WEB_SCRAPING_ALLOWED is False


def test_contract_instance_is_immutable() -> None:
    """A later phase must not be able to relax policy by assignment."""
    with pytest.raises(FrozenInstanceError):
        CONTRACT.paid_runtime_services_allowed = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        CONTRACT.required_git_branch = "main"  # type: ignore[misc]


def test_module_aliases_match_the_contract_instance() -> None:
    """The two representations are derived, so they can never drift."""
    assert CONTRACT.project_name == PROJECT_NAME
    assert CONTRACT.package_name == PACKAGE_NAME
    assert CONTRACT.required_git_branch == REQUIRED_GIT_BRANCH
    assert CONTRACT.roadmap_total_phases == ROADMAP_TOTAL_PHASES
    assert CONTRACT.exchange_scope == EXCHANGE_SCOPE
    assert CONTRACT.paid_runtime_services_allowed == PAID_RUNTIME_SERVICES_ALLOWED
    assert CONTRACT.web_scraping_allowed == WEB_SCRAPING_ALLOWED


def test_contract_names_are_re_exported_from_the_package_root() -> None:
    for name in (
        "CONTRACT",
        "EXCHANGE_SCOPE",
        "PACKAGE_NAME",
        "PAID_RUNTIME_SERVICES_ALLOWED",
        "PROJECT_NAME",
        "REQUIRED_GIT_BRANCH",
        "ROADMAP_TOTAL_PHASES",
        "WEB_SCRAPING_ALLOWED",
    ):
        assert name in globin.__all__, f"{name} missing from globin.__all__"
        assert hasattr(globin, name)


def test_phase_one_package_has_no_trading_surface() -> None:
    """Guard against scope leakage: Phase 1 must expose no execution surface.

    This is a coarse check, not a proof. It exists so that a future phase
    cannot casually attach a client or order function to the package root
    without the omission of a corresponding roadmap phase becoming visible.
    """
    forbidden = {"Client", "connect", "place_order", "submit_order", "session"}
    exposed = set(globin.__all__)
    assert not (forbidden & exposed), f"unexpected trading surface: {forbidden & exposed}"
