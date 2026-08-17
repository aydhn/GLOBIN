"""What the diagnostics surface needs from the rest of GLOBIN, as five contracts.

Each is one method, which is `ports/health.py`'s shape and is chosen for the same
reason: a protocol with one method is a contract a test double can satisfy by hand
in three lines, and `TESTING_STRATEGY.md` prefers a hand-written double to a mock.

**The split between them is what keeps `/health/live` honest.** Liveness must not
depend on anything a health probe reads — not `psutil`, not the filesystem, not a
lock — because a liveness endpoint that fails when a disk fills up would tell a
supervisor to restart a process that is running perfectly. Giving liveness its own
one-method contract is how that independence becomes structural rather than
remembered: :class:`LivenessProbe` has no way to reach a snapshot.

**None of these may raise for an expected condition**, which is the rule
`ports/health.py` states for its probes. A readiness probe that raised because the
process was still starting up would turn "not ready yet" into a 500, and the
difference between those two is the whole reason a supervisor asks.

None is ``@runtime_checkable``. Conformance is mypy's job; a runtime check would
verify method names and prove nothing about behaviour.
"""

from typing import Protocol

from globin.domain.diagnostics_http import ExpositionFormat, ReadinessReason


class LivenessProbe(Protocol):
    """Whether this process is running and has not begun to die."""

    def alive(self) -> bool:
        """Whether the process should be considered live.

        Returns:
            ``False`` only once shutdown has been requested. Anything else — a full
            disk, an absent library, an unhealthy check — is a *health* question and
            deliberately cannot reach this answer.
        """
        ...


class ReadinessProbe(Protocol):
    """Whether this process is ready to do the work it exists for."""

    def readiness(self) -> ReadinessReason:
        """Why the process is or is not ready.

        Returns:
            A bounded reason. :attr:`~globin.domain.diagnostics_http.ReadinessReason.READY`
            is the only one that means yes, so a caller branches on identity rather
            than on a string it has to know the vocabulary of.
        """
        ...


class HealthProjection(Protocol):
    """The runtime health document, already redacted and safe to publish."""

    def document(self) -> dict[str, object]:
        """The health snapshot as a document.

        Returns:
            Plain types only, ready for canonical JSON.

        **The implementation redacts; this port does not promise to.** That is worth
        stating because the direction of the guarantee matters: a projection handed to
        this surface must already be publishable, because there is no filter between
        here and the socket.
        """
        ...


class SnapshotProjection(Protocol):
    """The fuller diagnostic document, which an operator must opt into twice."""

    def document(self) -> dict[str, object]:
        """The diagnostics snapshot as a document.

        Returns:
            Plain types only, ready for canonical JSON.

        Separate from :class:`HealthProjection` because it says more: the health
        verdict *and* what telemetry has measured. Same shape, different contents,
        and a different switch — which is why it is a second protocol rather than a
        parameter on the first.
        """
        ...


class MetricsExposition(Protocol):
    """The current metrics, encoded in whichever format was negotiated."""

    def render(self, exposition: ExpositionFormat) -> str:
        """Encode the current measurements.

        Args:
            exposition: Which format the negotiation chose.

        Returns:
            The exposition text.

        **Nothing here reaches an exporter.** The implementation renders from the
        local registry, so a scrape keeps working when a remote collector is down —
        and a collector's timeout can never appear in a request's critical path.
        """
        ...
