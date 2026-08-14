"""The fastest signal that the tree is not broken.

Nothing here is thorough, and it should not become thorough. The value of this
level is latency: it runs first in ``tools.quality fast`` and inside the
pre-commit hook, so a change that breaks the package fails in well under a
second instead of after the full suite.

The rule of thumb for adding something here: would it fail for a change that
makes the repository unusable? If it would only fail for a subtle logic error,
it belongs at a level that runs later.
"""

import importlib

import pytest

import globin

#: Every module that must import cleanly for the package to be usable at all.
#: The layer packages are included because an import error in one of them means
#: the composition root cannot be built.
IMPORTABLE_MODULES: tuple[str, ...] = (
    "globin",
    "globin.project_contract",
    "globin.roadmap",
    "globin.domain",
    "globin.domain.architecture",
    "globin.ports",
    "globin.ports.architecture",
    "globin.application",
    "globin.application.architecture_review",
    "globin.adapters",
    "globin.adapters.architecture",
    "globin.runtime",
    "globin.runtime.composition",
)


@pytest.mark.parametrize("name", IMPORTABLE_MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None


def test_the_package_declares_a_version() -> None:
    assert globin.__version__


def test_the_public_surface_matches_what_is_declared() -> None:
    """A name in ``__all__`` that is not present breaks a star import silently."""
    missing = [name for name in globin.__all__ if not hasattr(globin, name)]
    assert not missing, f"declared in __all__ but absent: {missing}"


def test_the_composition_root_is_reachable() -> None:
    """If this fails, nothing that wires the application together can run."""
    from globin.runtime.composition import build_architecture_review

    assert callable(build_architecture_review)


def test_the_package_still_exposes_no_trading_surface() -> None:
    """Cheap tripwire against scope leakage, checked at the fastest level.

    GLOBIN does not trade, and the phase that changes that is 305-320. A client
    or order function appearing on the package root is the earliest visible sign
    that something was built far ahead of its phase.
    """
    forbidden = {"Client", "connect", "place_order", "submit_order", "session"}
    exposed = forbidden & set(globin.__all__)
    assert not exposed, f"unexpected trading surface: {exposed}"
