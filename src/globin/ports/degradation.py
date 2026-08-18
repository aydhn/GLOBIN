"""The contract through which GLOBIN asks what this host is missing.

One protocol and one method, matching :class:`~globin.ports.environment.EnvironmentProbe`'s
shape because :class:`~globin.application.bootstrap.BootstrapPipeline` is built
entirely from ports and a probe that took arguments would make the pipeline decide
something.

**``None`` is an answer, not a failure.** It means the declaration itself could
not be read, which is the only route to
:attr:`~globin.domain.bootstrap.CheckStatus.UNMEASURED` for this check — the same
treatment an unreadable ``runtime-contract.toml`` already gets. A survey that ran
has an answer for every declared component, because every factory was called and
every one answered; that is what
:class:`~globin.domain.degradation.DegradationReport` refuses to be constructed
without.
"""

from typing import Protocol

from globin.domain.degradation import DegradationReport


class DegradationProbe(Protocol):
    """Surveys which declared components this host actually has."""

    def survey(self) -> DegradationReport | None:
        """Call every declared factory and record which arm it took.

        Returns:
            The report, or ``None`` where the declaration could not be read.

        Nothing here raises for an expected outcome. An absent library, a
        Windows release predating an API and a host with no device are all
        answers, and each arrives as a
        :class:`~globin.domain.degradation.ComponentObservation` — the form
        ADR-0045 requires of a platform capability.
        """
        ...
