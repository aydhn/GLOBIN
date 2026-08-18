"""The use case that judges whether a long-running process may start.

Thin, and the same shape as
:class:`~globin.application.configuration.ConfigurationResolution`: it runs
machinery that already exists and hands the result to the domain to judge. There
is no second pipeline here, no second registry, and no check this module knows
about that :func:`~globin.domain.bootstrap.checks` does not.

**Preflight is the third combination of two switches that already existed, not a
fourth pipeline.** ``bootstrap check`` stops at the first refusal and gates;
``doctor`` runs everything and reports. Preflight runs everything *and* gates,
because the two halves serve different readers and a launcher needs both: an
operator preparing to start a long-running process wants every fault in one pass
rather than one restart per fault, and the launcher still must not start.

What it adds beyond that combination is the only thing a suite can add over a
registry — :meth:`~globin.domain.preflight.PreflightOutcome.shelf_life_millis`,
which says how long the verdict it just produced stays true.
"""

from dataclasses import dataclass

from globin.application.bootstrap import BootstrapPipeline
from globin.domain.preflight import PreflightOutcome, PreflightSuite


@dataclass(frozen=True, slots=True)
class PreflightRun:
    """Runs every registered check and judges the result against the suite.

    Args:
        pipeline: The assembled bootstrap pipeline. Built by
            :func:`~globin.runtime.composition.build_bootstrap`, so this service
            constructs nothing and reaches nothing.
        suite: The classification and re-take schedule to judge under.
    """

    pipeline: BootstrapPipeline
    suite: PreflightSuite

    def run(self) -> PreflightOutcome:
        """Perform every check and pair the report with the suite.

        Returns:
            A :class:`~globin.domain.preflight.PreflightOutcome`.

        Raises:
            GlobinError: As the pipeline. Nothing is caught here that the
                pipeline does not already catch, because a preflight that
                swallowed a fault would be reporting a verdict about a run that
                did not happen.

        **Every check runs, including the ones after a refusal.** That is the one
        decision this method owns, and it is deliberately not the gating
        behaviour: refusal is
        :attr:`~globin.domain.preflight.PreflightOutcome.may_start`'s answer,
        which a partial report fails anyway because
        :attr:`~globin.domain.bootstrap.BootstrapReport.ready` counts as well as
        inspects. Stopping early would make the two coincide and lose the
        completeness for nothing.
        """
        outcome = self.pipeline.run(stop_at_first_refusal=False)
        return PreflightOutcome(report=outcome.report, suite=self.suite)
