"""The contracts through which the bootstrap learns about the machine.

Six protocols, one per question the pipeline asks. Each exists because the answer
comes from outside the process — the operating system, the interpreter, the
filesystem, the installed distributions — and
:mod:`globin.application.bootstrap` may touch none of those. Substituting a probe
is how a test proves that a wrong interpreter is refused without owning a wrong
interpreter.

The split is by *source of truth* rather than by convenience. Asking one object
for the host, the interpreter, the project root, the declared baseline, the
installed distributions and the secret store would make every test that needed
one of those build all six, and would leave no seam where Phases 026 to 030 can
substitute a real implementation for the honest placeholder this phase ships.

**No port here returns a secret value**, and :class:`SecretProbe` is named for
what it measures rather than for what it reads. That is
``docs/security/SECRET_STORE_CONTRACT.md`` §1 observed rather than restated: a
reference is not a value, the reference type itself belongs to Phase 028, and a
readiness answer needs neither.
"""

from typing import Protocol

from globin.domain.bootstrap import (
    DependencyReadiness,
    EntitlementReadiness,
    HostFacts,
    InterpreterFacts,
    ProjectIdentity,
    RecordedPath,
    RuntimeBaseline,
    RuntimePaths,
    SecretReadiness,
)
from globin.domain.environment import EnvironmentCapabilitySnapshot


class RuntimeBaselineSource(Protocol):
    """Supplies the contract this host is judged against."""

    def baseline(self) -> RuntimeBaseline:
        """Return the declared runtime baseline.

        Returns:
            The parsed contract.

        Raises:
            ConfigurationError: If the declaration is missing or malformed. A
                bootstrap that cannot read what it must enforce has not measured
                the host, and saying so is the only honest answer.
        """
        ...


class HostProbe(Protocol):
    """Observes the machine and the interpreter running on it."""

    def host(self) -> HostFacts:
        """Return what this machine is.

        Returns:
            The operating system, its release, the architecture and the pointer
            width.
        """
        ...

    def interpreter(self) -> InterpreterFacts:
        """Return what this Python is.

        Returns:
            The implementation, version, build and the three paths that decide
            which environment it belongs to — recorded rather than spelled out.
        """
        ...


class ProjectProbe(Protocol):
    """Locates the project and reads its identity."""

    def root(self) -> RecordedPath:
        """Return where the project root was found.

        Returns:
            The root, recorded. :attr:`~globin.domain.bootstrap.PathLocation.ABSENT`
            when the search found nothing, which is a refusal rather than a
            reason to guess.
        """
        ...

    def origin(self) -> str:
        """Describe how the search started, for a failure message.

        Returns:
            A phrase completing "no project root was found ...".
        """
        ...

    def identity(self) -> ProjectIdentity | None:
        """Return which GLOBIN this is.

        Returns:
            The distribution name, version and where the version came from, or
            ``None`` when neither installed metadata nor the imported package
            could supply one.
        """
        ...


class DependencyProbe(Protocol):
    """Reports what is declared, what is locked and what is installed."""

    def readiness(self) -> DependencyReadiness:
        """Return the state of the declared runtime dependencies.

        Returns:
            The declared set, whether a runtime lock accompanies it, and which
            declared distributions this interpreter cannot see.

        No resolver runs and no index is consulted. Start-up must work without a
        network, so the only question asked here is the local one.
        """
        ...


class EnvironmentProbe(Protocol):
    """Reports what this host is capable of, beyond what the contract declares."""

    def snapshot(self, baseline: RuntimeBaseline) -> EnvironmentCapabilitySnapshot:
        """Measure every declared capability.

        Args:
            baseline: The contract, for the architecture it requires.

        Returns:
            The snapshot, from which a verdict and a fingerprint follow.

        Takes the baseline rather than reading it, so that this probe and
        :class:`RuntimeBaselineSource` cannot disagree about what was declared —
        there is one read of ``runtime-contract.toml`` per run and every check
        judges against the same parse.
        """
        ...


class SecretProbe(Protocol):
    """Reports whether the secret references a start-up needs can be resolved."""

    def readiness(self) -> SecretReadiness:
        """Return the state of the required secret references.

        Returns:
            Which references are required and which of them are unavailable. No
            value is read, returned or held.
        """
        ...


class EntitlementProbe(Protocol):
    """Reports whether required credentials are permitted to do what is asked."""

    def readiness(self) -> EntitlementReadiness:
        """Return the state of every required credential entitlement.

        Returns:
            What was demanded and how each verdict came out. No value is read,
            returned or held -- the verdict is computed from declarations and
            requirements, and the store is never consulted.
        """
        ...


class RuntimeTree(Protocol):
    """Prepares the declared runtime tree and reports what is unusable."""

    def prepare(self, paths: RuntimePaths) -> tuple[str, ...]:
        """Create the permitted roots and check the rest.

        Args:
            paths: The declared tree, relative to the project root.

        Returns:
            One sentence per declared root that cannot be used. Empty when the
            tree is fit to write into.

        Only the roots in :data:`~globin.domain.bootstrap.CREATED_PATHS` may be
        brought into existence. An implementation that created the others would
        be making the claim ``REPOSITORY_LAYOUT.md`` refuses — that a capability
        nobody has built is being worked on.
        """
        ...
