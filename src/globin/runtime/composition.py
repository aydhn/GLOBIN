"""Composition root: where GLOBIN's objects are built and wired together.

The worked example of GLOBIN's wiring convention — plain functions that take what
they cannot know and return fully constructed objects. Nothing is cached, nothing
is global, and nothing runs until a function is called.

The ``repo_root`` argument is not decoration. The architecture review reviews
*this* repository's source tree, so it needs a location, and guessing one by
walking up from ``__file__`` would make the result depend on where the package
happens to be installed. Passing it in keeps the dependency visible and lets a
test point the review at a fixture tree instead. Configuration sources are given
the same way, for the same reason.

These functions build; they do not choose. Which configuration sources exist and
in what order they are consulted is Phase 027's decision, and a composition root
that grew branching logic about *what* to construct would be the failure
ADR-0015 names in its own risk section.
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, TextIO

from globin.adapters.architecture import AstModuleImportSource, TomlArchitectureContractSource
from globin.adapters.clock import SystemClock, SystemMonotonicClock
from globin.adapters.observability import StreamLogSink, ThresholdLogSink, new_correlation_id
from globin.adapters.serialization import JsonCodec
from globin.application.architecture_review import ArchitectureReview
from globin.application.configuration import ConfigurationResolution
from globin.application.observability import Logger
from globin.domain.configuration import GlobinConfig, default_config
from globin.ports.clock import Clock, MonotonicClock
from globin.ports.configuration import ConfigurationSource
from globin.ports.serialization import Codec

CONTRACT_RELATIVE_PATH: Final[str] = "docs/architecture/dependency-rules.toml"
"""Where the declared contract lives, relative to the repository root."""

PACKAGE_RELATIVE_PATH: Final[str] = "src/globin"
"""Where the package source lives, relative to the repository root."""

ROOT_PACKAGE: Final[str] = "globin"
"""The import namespace the review is scoped to."""


def build_architecture_review(repo_root: Path) -> ArchitectureReview:
    """Wire the architecture review against a repository checkout.

    Args:
        repo_root: Absolute path to the repository root — the directory holding
            ``pyproject.toml``.

    Returns:
        An :class:`~globin.application.architecture_review.ArchitectureReview`
        reading the declared contract and this repository's own source tree.

    No file is opened here. Both adapters record their paths and read them when
    the review runs, so constructing the graph stays free of I/O even though
    the objects it contains will perform some.
    """
    return ArchitectureReview(
        contract_source=TomlArchitectureContractSource(repo_root / CONTRACT_RELATIVE_PATH),
        module_source=AstModuleImportSource(repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE),
    )


def build_configuration(sources: Sequence[ConfigurationSource] | None = None) -> GlobinConfig:
    """Resolve GLOBIN's configuration from the declared defaults plus ``sources``.

    Args:
        sources: Weakest first, strongest last. Defaults to none at all, which
            resolves to the declared defaults — the configuration GLOBIN uses
            when an operator has said nothing.

    Returns:
        The validated :class:`~globin.domain.configuration.GlobinConfig`.

    Raises:
        ConfigurationError: If a source supplied an unknown key or an unreadable
            value.

    No file is opened here. A source records its path and reads it when the
    resolution runs, so building the graph stays free of I/O even though the
    objects in it will perform some — the same property
    :func:`build_architecture_review` has.
    """
    return ConfigurationResolution(sources=() if sources is None else tuple(sources)).run()


def build_clock() -> Clock:
    """The host's wall clock, as the port.

    Returns:
        A :class:`~globin.adapters.clock.SystemClock`.

    The return type is the **port**, not the adapter, so this function stays the
    only place in the tree that names the concrete clock. That is ADR-0014 and
    ADR-0015 made concrete rather than restated.
    """
    return SystemClock()


def build_monotonic_clock() -> MonotonicClock:
    """The host's monotonic clock, as the port.

    Returns:
        A :class:`~globin.adapters.clock.SystemMonotonicClock`.

    Nothing in GLOBIN measures an elapsed interval yet. This exists because
    ``ROADMAP.md`` gives Phase 009 "monotonic clocks" by name, and because the
    decision worth fixing now is *which* guarantee an elapsed measurement rests
    on — not the first call site, which arrives with the code that needs it.
    """
    return SystemMonotonicClock()


def build_codec() -> Codec:
    """The representation GLOBIN persists records in, as the port.

    Returns:
        A :class:`~globin.adapters.serialization.JsonCodec`.

    The return type is the **port**, so this function stays the only place in the
    tree that names the concrete representation — the same property
    :func:`build_clock` has, and for the same reason.

    Nothing in GLOBIN persists a record yet. This exists because ``ROADMAP.md``
    gives Phase 012 the serialization and persistence contracts, and the decision
    worth fixing now is *which* representation a stored record is in — not the
    first caller, which arrives with the phase that has somewhere to put one.
    """
    return JsonCodec()


def build_logger(
    stream: TextIO | None = None,
    correlation_id: str | None = None,
    config: GlobinConfig | None = None,
    clock: Clock | None = None,
) -> Logger:
    """Wire a logger writing JSON Lines to a stream.

    Args:
        stream: Where records go. Defaults to :data:`sys.stderr`, so that log
            output does not contaminate whatever a program writes to standard
            output.
        correlation_id: Ties every record this logger produces to one unit of
            work. Defaults to a fresh one. A test passes its own, and so does a
            caller continuing work that already has an id.
        config: Supplies the severity threshold. Defaults to
            :func:`~globin.domain.configuration.default_config`, whose threshold
            is ``DEBUG`` and therefore discards nothing.
        clock: Stamps each record. Defaults to :func:`build_clock`. A test
            passes a fixed or manually advanced clock and can then assert the
            exact timestamps written.

    Returns:
        A :class:`~globin.application.observability.Logger`.

    Every argument defaults to ``None`` rather than to the value it resolves to.
    ``sys.stderr`` as a default argument would be captured when this module is
    imported, which is both work at import time and the wrong stream if anything
    later replaces it — and reading it here keeps this function the only place
    that knows which stream GLOBIN logs to. The clock is the same argument with
    a stronger reason: a clock captured at import would be ambient time, which
    is what Phase 009 exists to remove.

    The threshold sink is applied unconditionally rather than only when a
    threshold has been configured. ``DEBUG`` is the lowest severity, so at the
    default the wrapper provably changes nothing; wrapping only sometimes would
    give this function a decision to make about *what* to build, and leave one
    arm of it exercised by nobody.
    """
    settings = default_config() if config is None else config
    return Logger(
        sink=ThresholdLogSink(
            inner=StreamLogSink(
                stream=sys.stderr if stream is None else stream,
                clock=build_clock() if clock is None else clock,
            ),
            minimum=settings.logging.min_severity,
        ),
        correlation_id=new_correlation_id() if correlation_id is None else correlation_id,
    )
