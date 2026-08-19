"""Reading the declared component set, and asking each factory which arm it took.

Phase 031's titled half, on the adapter side. The declaration lives in
``docs/engineering/degradation-contract.toml`` and is parsed here; the judgement
is :mod:`globin.domain.degradation`'s and nothing in this module decides whether a
posture blocks.

**This module asks each factory and classifies its answer, rather than each
adapter reporting on itself, and that is a trade-off worth stating.** The
alternative was a ``component_state()`` on both arms of all six factories, which
keeps "am I the real thing" inside the module that already owns the absence. It
was declined for cost: six modules and their tests would move to add one
observation each, and the classification would still be one rule expressed six
times. What makes this safe is the tripwire rather than the discipline —
``tests/architecture/test_degradation_discipline.py`` asserts in **both**
directions that every ``reached_through`` names something real and that every
module defining an absent-safe stand-in appears in the contract, so a seventh
factory cannot arrive unsurveyed.

**The observable signal that this was the wrong call** is a factory whose two arms
stop being distinguishable by type — at which point the ``isinstance`` below
becomes a guess and the per-module function is owed.

**Nothing here reaches a network, and nothing probes a device.** The two
components that would need either are declared
:attr:`~globin.domain.environment.CapabilityStatus.NOT_APPLICABLE` with reason
:attr:`~globin.domain.environment.CapabilityReason.PROBE_UNAVAILABLE`, because the
question does not arise rather than because nobody could answer it. Adding a probe
would create a mechanism with no caller and, for the network, would remove a
guarantee the architecture tests currently prove.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from globin.domain.degradation import (
    ComponentKind,
    ComponentNecessity,
    ComponentObservation,
    ComponentSpec,
    DegradationReport,
)
from globin.domain.environment import CapabilityReason, CapabilityStatus
from globin.errors import ValidationError

CONTRACT_RELATIVE_PATH: Final[str] = "docs/engineering/degradation-contract.toml"
"""Where the declaration lives, relative to the repository root."""

SUPPORTED_SCHEMA: Final[int] = 1
"""Which contract shape this reader understands.

Fails closed in both directions, as every other schema version in this repository
does: a document announcing a later shape is refused rather than read anyway.
"""

VAULT_PROBE_SEGMENT: Final[str] = "."
"""Where the vault factory is pointed when only its availability is asked.

The factory creates nothing — the vault directory is made by the first write — so
any path answers the question "does this host have crypt32 and a deallocator".
Pointing it at the current directory rather than the real vault keeps the survey
from needing a runtime tree it does not otherwise use.
"""

UNREACHED: Final[str] = ""
"""What ``reached_through`` holds for a component nothing reaches yet.

An empty string rather than a null, so the field has one type everywhere and a
reader never has to ask which absence it is looking at.
"""


@dataclass(frozen=True, slots=True)
class ContractDegradationProbe:
    """Surveys the declared components against this host.

    Args:
        contract: Where the declaration is.
        arms: Which factory to call for each ``reached_through`` path, and how to
            read its answer. Injected so that every branch is reachable from a
            test on any host — the same seam
            :class:`~globin.adapters.bootstrap.SystemHostProbe` opens for
            :func:`shutil.disk_usage`.
    """

    contract: Path
    arms: dict[str, Callable[[], ComponentObservation]]

    def survey(self) -> DegradationReport | None:
        """Read the declaration and observe every component in it.

        Returns:
            The report, or ``None`` where the declaration could not be read.

        ``None`` rather than a raise, because an unreadable contract is a state
        the check reports as unmeasured rather than a fault that stops a
        start-up. Every other failure here — a malformed row, an unknown
        necessity — is a :class:`~globin.errors.ValidationError` from the domain,
        which is a defect in a committed file rather than a property of the host.
        """
        specs = read_contract(self.contract)
        if specs is None:
            return None
        observations = tuple(self._observe(spec) for spec in specs)
        return DegradationReport(components=specs, observations=observations)

    def _observe(self, spec: ComponentSpec) -> ComponentObservation:
        """Ask one component's factory what it found.

        Args:
            spec: What was declared.

        Returns:
            What was observed.

        A component with no ``reached_through`` is
        :attr:`~globin.domain.environment.CapabilityStatus.NOT_APPLICABLE`: GLOBIN
        has no caller for it, so there is nothing to ask and nothing that could
        have failed.
        """
        if spec.reached_through == UNREACHED:
            return ComponentObservation(
                identifier=spec.identifier,
                status=CapabilityStatus.NOT_APPLICABLE,
                reason=CapabilityReason.PROBE_UNAVAILABLE,
                detail="GLOBIN has no caller for this yet",
            )
        arm = self.arms.get(spec.reached_through)
        if arm is None:
            return ComponentObservation(
                identifier=spec.identifier,
                status=CapabilityStatus.UNKNOWN,
                reason=CapabilityReason.PROBE_UNAVAILABLE,
                detail="no factory was wired for this component",
            )
        return arm()


def read_contract(path: Path) -> tuple[ComponentSpec, ...] | None:
    """Parse the declared component set.

    Args:
        path: Where the declaration is.

    Returns:
        The declarations in document order, or ``None`` where the file is absent
        or unreadable.

    Raises:
        ValidationError: If the document parses and says something this reader
            cannot act on — an unsupported schema, an unknown kind or necessity.
            That is a defect in a committed file, which is a different thing from
            a host that has no file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        document = tomllib.loads(text)
    except ValueError:
        return None
    schema = document.get("schema")
    if schema != SUPPORTED_SCHEMA:
        msg = (
            f"the degradation contract announces schema {schema!r} and this GLOBIN "
            f"reads {SUPPORTED_SCHEMA}; it is refused rather than read anyway"
        )
        raise ValidationError(msg)
    rows = document.get("component", [])
    if not isinstance(rows, list):
        msg = "the degradation contract's component entries are not a list"
        raise ValidationError(msg)
    return tuple(_spec_from(row) for row in rows)


def _spec_from(row: Any) -> ComponentSpec:
    """Build one declaration from one parsed row.

    Args:
        row: What the document held.

    Returns:
        The declaration.

    Raises:
        ValidationError: If a field is missing or names something outside its
            enumeration.
    """
    if not isinstance(row, dict):
        msg = "a degradation contract entry is a table"
        raise ValidationError(msg)
    identifier = str(row.get("id", ""))
    try:
        kind = ComponentKind(str(row.get("kind", "")))
    except ValueError as fault:
        msg = f"{identifier or 'a component'} names an unknown kind: {fault}"
        raise ValidationError(msg) from fault
    try:
        necessity = ComponentNecessity(str(row.get("necessity", "")))
    except ValueError as fault:
        msg = f"{identifier or 'a component'} names an unknown necessity: {fault}"
        raise ValidationError(msg) from fault
    withdraws = row.get("withdraws", [])
    if not isinstance(withdraws, list):
        msg = f"{identifier}'s withdraws is not a list"
        raise ValidationError(msg)
    return ComponentSpec(
        identifier=identifier,
        kind=kind,
        necessity=necessity,
        withdraws=tuple(str(entry) for entry in withdraws),
        reached_through=str(row.get("reached_through", UNREACHED)),
        absence_means=" ".join(str(row.get("absence_means", "")).split()),
        owner_phase=int(row.get("owner_phase", 0)),
    )


def _present(identifier: str, detail: str = "") -> ComponentObservation:
    """A component that is here.

    Args:
        identifier: Which component.
        detail: An optional phrase.

    Returns:
        The observation.
    """
    return ComponentObservation(
        identifier=identifier,
        status=CapabilityStatus.SUPPORTED,
        reason=CapabilityReason.SATISFIED,
        detail=detail,
    )


def _absent(identifier: str, detail: str) -> ComponentObservation:
    """A component that was looked for and is not here.

    Args:
        identifier: Which component.
        detail: A phrase saying what was looked for.

    Returns:
        The observation.
    """
    return ComponentObservation(
        identifier=identifier,
        status=CapabilityStatus.UNSUPPORTED,
        reason=CapabilityReason.PROBE_UNAVAILABLE,
        detail=detail,
    )


def _not_applicable(identifier: str, detail: str) -> ComponentObservation:
    """A component whose question does not arise on this host.

    Args:
        identifier: Which component.
        detail: A phrase saying why.

    Returns:
        The observation.

    Distinct from :func:`_absent` and from an unknown, and the distinction
    carries the required tier: ``advapi32`` is declared required and observed
    like this while nothing needs a credential, so the tier is producible from
    literals today without refusing a start for a capability nothing uses.
    """
    return ComponentObservation(
        identifier=identifier,
        status=CapabilityStatus.NOT_APPLICABLE,
        reason=CapabilityReason.SATISFIED,
        detail=detail,
    )


def system_arms(
    *, credentials_required: bool = False
) -> dict[str, Callable[[], ComponentObservation]]:
    """The real factories, keyed by the path the contract names.

    Args:
        credentials_required: Whether anything yet needs a credential. While
            nothing does, ``advapi32`` is observed as not-applicable rather than
            absent, so its declared *required* tier does not refuse a start for a
            capability no caller uses.

    Returns:
        One callable per reachable component.

    Each entry calls the owning factory once and reads which arm it returned.
    That the two arms are distinguishable by type is the property this depends
    on, and the module docstring records what to do if it ever stops being true.
    """
    from globin.adapters.environment import UnavailableSystemApi, windows_system_api
    from globin.adapters.health import UnavailableProcessProbe, system_process_probe
    from globin.adapters.secret_vault import UnavailableSecretVault, secret_vault
    from globin.adapters.secrets import UnavailableSecretStore, windows_credential_store
    from globin.adapters.signing import UnavailableAsymmetricSigner, asymmetric_signers
    from globin.adapters.telemetry_otel import UnavailableOpenTelemetry, opentelemetry_bridge
    from globin.adapters.telemetry_prometheus import (
        UnavailablePrometheus,
        prometheus_publisher,
    )

    def psutil_arm() -> ComponentObservation:
        """Whether the process probe is the real one."""
        identifier = "component.library.psutil"
        if isinstance(system_process_probe(), UnavailableProcessProbe):
            return _absent(identifier, "psutil is not importable in this environment")
        return _present(identifier)

    def otel_arm() -> ComponentObservation:
        """Whether the OpenTelemetry bridge is the real one."""
        identifier = "component.library.opentelemetry"
        if isinstance(opentelemetry_bridge(), UnavailableOpenTelemetry):
            return _absent(identifier, "opentelemetry is not importable in this environment")
        return _present(identifier)

    def prometheus_arm() -> ComponentObservation:
        """Whether the Prometheus publisher is the real one."""
        identifier = "component.library.prometheus_client"
        if isinstance(prometheus_publisher(), UnavailablePrometheus):
            return _absent(identifier, "prometheus_client is not importable in this environment")
        return _present(identifier)

    def kernel32_arm() -> ComponentObservation:
        """Whether kernel32 loaded, and whether it carried the modern export.

        A library that loads *without* ``IsWow64Process2`` is DEGRADED rather
        than absent — a real distinction nothing reported before Phase 031, and
        the reason this arm reads a field rather than only a type.
        """
        identifier = "component.native.kernel32"
        api = windows_system_api()
        if isinstance(api, UnavailableSystemApi):
            return _absent(identifier, "kernel32 did not load on this host")
        if not api.has_wow64_process2:
            return ComponentObservation(
                identifier=identifier,
                status=CapabilityStatus.DEGRADED,
                reason=CapabilityReason.PROBE_UNAVAILABLE,
                detail="kernel32 loaded, IsWow64Process2 absent",
            )
        return _present(identifier)

    def advapi32_arm() -> ComponentObservation:
        """Whether the credential store is the real one.

        Observed not-applicable while nothing requires a credential, which is
        what keeps the required tier honest today. See the contract's own row.
        """
        identifier = "component.native.advapi32"
        absent = isinstance(windows_credential_store(), UnavailableSecretStore)
        if not absent:
            return _present(identifier)
        if not credentials_required:
            return _not_applicable(identifier, "no reference requires a credential yet")
        return _absent(identifier, "advapi32 did not load on this host")

    def crypt32_arm() -> ComponentObservation:
        """Whether the DPAPI vault is the real one."""
        identifier = "component.native.crypt32"
        if isinstance(secret_vault(Path(VAULT_PROBE_SEGMENT)), UnavailableSecretVault):
            return _absent(identifier, "crypt32 or its deallocator is unavailable")
        return _present(identifier)

    def cryptography_arm() -> ComponentObservation:
        """Whether the asymmetric signers are the real ones.

        Both arms of that factory move together — one library supplies both
        algorithms, so a host has both or neither — which is why this reads one of
        the pair rather than checking each and reconciling two answers that cannot
        legitimately differ.
        """
        identifier = "component.library.cryptography"
        rsa_signer, _ = asymmetric_signers()
        if isinstance(rsa_signer, UnavailableAsymmetricSigner):
            return _absent(identifier, "cryptography is not importable in this environment")
        return _present(identifier)

    return {
        "globin.adapters.health.system_process_probe": psutil_arm,
        "globin.adapters.telemetry_otel.opentelemetry_bridge": otel_arm,
        "globin.adapters.telemetry_prometheus.prometheus_publisher": prometheus_arm,
        "globin.adapters.environment.windows_system_api": kernel32_arm,
        "globin.adapters.secrets.windows_credential_store": advapi32_arm,
        "globin.adapters.secret_vault.secret_vault": crypt32_arm,
        "globin.adapters.signing.asymmetric_signers": cryptography_arm,
    }
