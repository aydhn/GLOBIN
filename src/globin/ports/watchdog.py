"""The seams the watchdog reaches the outside world through.

Four protocols, split by **audience** rather than by implementation, on the
precedent ``globin.ports.health`` sets. One adapter satisfies the first two, and
they are still two: what a monitored component is handed must not be able to read
the registry, and what the watchdog loop is handed must not be able to beat.
Narrowing at the seam is what stops a component from accidentally reporting
progress on another's behalf.

**Registration is deliberately not here.** It happens once, in the composition
root, on the concrete registry. A port for it would invite a component to register
itself at the moment it first beats, which is exactly how a monitored set becomes
whatever happened to run rather than what was designed.
"""

from typing import Protocol

from globin.domain.watchdog import HeartbeatSnapshot, StallEvidence


class Heartbeat(Protocol):
    """What a monitored component is handed, and all it is handed."""

    def beat(self, component: str) -> None:
        """Report that this component has made progress.

        Args:
            component: Which component made it.

        Raises:
            ValidationError: If nothing registered under that name. A silent no-op
                would mean a mistyped name is monitored by nothing and nothing says
                so, which is the failure the whole subsystem exists to prevent.

        Advances a counter rather than rewriting a timestamp. A component looping
        inside a wedged call can rewrite a timestamp forever; advancing a sequence
        is a claim that something actually happened.
        """
        ...


class HeartbeatSource(Protocol):
    """What the watchdog loop is handed, and all it is handed."""

    def snapshot(self) -> HeartbeatSnapshot:
        """Every monitored component, frozen at one reading.

        Returns:
            The snapshot, already immutable and already ordered.
        """
        ...


class StallEvidenceCollector(Protocol):
    """The post-mortem, gathered once per confirmed stall."""

    def capture(self, incident_id: str) -> StallEvidence:
        """Gather what can be gathered.

        Args:
            incident_id: What the incident is filed under, so a native dump written
                to a separate file can be matched to it.

        Returns:
            What was gathered, including one sentence per collector that failed.

        **Never raises.** A collector that failed reports itself in
        :attr:`~globin.domain.watchdog.StallEvidence.problems`, for the reason no
        health probe raises: the caller is already handling a failure, and an
        exception here would replace the incident with the story of its own capture.
        """
        ...


class ProcessTerminator(Protocol):
    """Ending the process when it would not end itself."""

    def terminate(self, code: int) -> None:
        """Stop this process now.

        Args:
            code: The exit status to leave behind.

        Does not return in production. It is annotated ``None`` rather than
        ``NoReturn`` so that a test double may record the call and return — a
        ``NoReturn`` double would have to raise, and a raising double tests the
        watchdog's exception handling instead of its escalation.
        """
        ...
