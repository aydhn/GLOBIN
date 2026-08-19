"""What the declared transport contract says, as values rather than as a document.

The value half of ``docs/engineering/rest-transport.toml``. The parsing half is
:mod:`globin.adapters.rest`, and the split is the one
:mod:`globin.domain.api_reality` already draws against Phase 033's registry: a
document is read by an adapter and *is* a set of domain values, so an application
use case can be handed the contract without being handed a file.

**The comparison against the package's own constants lives here**, in
:meth:`NegotiationDeclaration.disagreements`, rather than only in a test. A
contract that has drifted from the code is an operator's problem as much as a
contributor's, and ``globin rest selftest`` runs on machines where pytest never
will.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from globin.domain.api_reality import ProductFamily, SurfaceCapability
from globin.domain.rest import (
    ACCEPT_HEADER,
    MEDIA_TYPE_JSON,
    MEDIA_TYPE_SBE,
    ORDER_COUNT_PREFIX,
    RETRY_AFTER_HEADER,
    SBE_SCHEMA_HEADER,
    TIME_UNIT_HEADER,
    TIME_UNIT_MICROSECOND,
    USED_WEIGHT_PREFIX,
    HttpMethod,
)
from globin.errors import ValidationError


@dataclass(frozen=True, slots=True)
class ProbeDescriptor:
    """One credential-free request the transport is permitted to send.

    Raises:
        ValidationError: On an empty operation or path, or a weight below one.

    A descriptor rather than a hardcoded path per product, because *which public
    path answers* is a per-product fact and Phase 033's registry deliberately
    carries no per-operation paths — that is Phase 037's, and its inheritance row
    says so. Until then the paths live in one declared document with a citation
    each, which is the same bargain the registry struck for hosts.
    """

    family: ProductFamily
    operation: str
    method: HttpMethod
    path: str
    capability: SurfaceCapability
    weight: int
    security: str
    notes: str
    source: str

    def __post_init__(self) -> None:
        """Refuse a probe that could not be sent or costs an unknown amount."""
        if not self.operation:
            msg = "a probe descriptor names no operation"
            raise ValidationError(msg)
        if not self.path.startswith("/"):
            msg = f"probe {self.operation!r} declares path {self.path!r}, which is not rooted"
            raise ValidationError(msg)
        if self.weight < 1:
            msg = f"probe {self.operation!r} declares a weight of {self.weight}"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This descriptor as plain JSON-safe values."""
        return {
            "family": self.family.slug,
            "operation": self.operation,
            "method": self.method.value,
            "path": self.path,
            "capability": self.capability.value,
            "weight": self.weight,
            "security": self.security,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class StatusRule:
    """One HTTP status and whether it leaves a write's fate unknown.

    Read back from the contract so ``classify`` can be checked against a declared
    table rather than against itself.
    """

    code: int
    meaning: str
    ambiguous_when_mutating: bool
    reason: str
    source: str

    def as_record(self) -> dict[str, object]:
        """This rule as plain JSON-safe values."""
        return {
            "code": self.code,
            "ambiguous_when_mutating": self.ambiguous_when_mutating,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class NegotiationDeclaration:
    """The header names and media types the contract declares, with their citation.

    Compared field by field against the constants in
    :mod:`globin.domain.rest` by ``tests/contract/test_rest_contract.py``. A field
    here that the code does not carry fails; a negotiation constant in the code that
    is not declared here fails too.
    """

    accept_header: str
    media_type_json: str
    media_type_sbe: str
    sbe_schema_header: str
    sbe_schema_format: str
    time_unit_header: str
    time_unit_microsecond: str
    retry_after_header: str
    used_weight_prefix: str
    order_count_prefix: str
    source: str
    sbe_source: str

    def disagreements(self) -> tuple[str, ...]:
        """Every declared value the package does not actually use.

        Returns:
            One message per mismatch, sorted, empty when the two agree.

        The comparison lives here rather than only in the test so that
        ``globin rest selftest`` can report it on a machine nobody is running
        pytest on — a declaration that has drifted from the code is an operator's
        problem as much as a contributor's.
        """
        pairs: tuple[tuple[str, str, str], ...] = (
            ("accept_header", self.accept_header, ACCEPT_HEADER),
            ("media_type_json", self.media_type_json, MEDIA_TYPE_JSON),
            ("media_type_sbe", self.media_type_sbe, MEDIA_TYPE_SBE),
            ("sbe_schema_header", self.sbe_schema_header, SBE_SCHEMA_HEADER),
            ("time_unit_header", self.time_unit_header, TIME_UNIT_HEADER),
            ("time_unit_microsecond", self.time_unit_microsecond, TIME_UNIT_MICROSECOND),
            ("retry_after_header", self.retry_after_header, RETRY_AFTER_HEADER),
            ("used_weight_prefix", self.used_weight_prefix, USED_WEIGHT_PREFIX),
            ("order_count_prefix", self.order_count_prefix, ORDER_COUNT_PREFIX),
        )
        return tuple(
            sorted(
                f"{name}: the contract declares {declared!r} and the package uses {used!r}"
                for name, declared, used in pairs
                if declared != used
            )
        )

    def as_record(self) -> dict[str, object]:
        """This declaration as plain JSON-safe values."""
        return {
            "accept_header": self.accept_header,
            "media_type_json": self.media_type_json,
            "media_type_sbe": self.media_type_sbe,
            "sbe_schema_header": self.sbe_schema_header,
            "sbe_schema_format": self.sbe_schema_format,
            "time_unit_header": self.time_unit_header,
            "time_unit_microsecond": self.time_unit_microsecond,
            "retry_after_header": self.retry_after_header,
            "used_weight_prefix": self.used_weight_prefix,
            "order_count_prefix": self.order_count_prefix,
            "source": self.source,
            "sbe_source": self.sbe_source,
        }


@dataclass(frozen=True, slots=True)
class TransportContract:
    """Everything ``rest-transport.toml`` declares, parsed and checked.

    Raises:
        ValidationError: On a repeated probe operation or status code, or on a
            prohibition declared true — every entry in that table names something
            the transport does **not** do, so a ``true`` would be a contract
            asserting its own violation.
    """

    negotiation: NegotiationDeclaration
    probes: tuple[ProbeDescriptor, ...]
    statuses: tuple[StatusRule, ...]
    exchange_codes: tuple[StatusRule, ...]
    limits: Mapping[str, int]
    prohibitions: Mapping[str, bool]
    phase: int
    observed_on: str

    def __post_init__(self) -> None:
        """Refuse a contract that repeats itself or contradicts its own prohibitions."""
        operations = [item.operation for item in self.probes]
        if len(set(operations)) != len(operations):
            msg = f"a probe operation is declared more than once: {sorted(operations)}"
            raise ValidationError(msg)
        codes = [item.code for item in self.statuses]
        if len(set(codes)) != len(codes):
            msg = f"a status rule is declared more than once: {sorted(codes)}"
            raise ValidationError(msg)
        asserted = sorted(name for name, value in self.prohibitions.items() if value)
        if asserted:
            msg = (
                f"the contract declares {', '.join(asserted)} as permitted; every entry in "
                "[prohibitions] names something the transport does not do"
            )
            raise ValidationError(msg)

    def probe(self, family: ProductFamily, operation: str) -> ProbeDescriptor | None:
        """One probe descriptor, or nothing.

        Args:
            family: Which product family.
            operation: Which operation.

        Returns:
            The descriptor, or ``None`` when the contract declares none. ``None``
            means *no public probe is declared for this product*, which is the
            state every non-Spot family is in and is a refusal rather than a
            licence to guess a path.
        """
        return next(
            (item for item in self.probes if item.family == family and item.operation == operation),
            None,
        )

    def probes_for(self, family: ProductFamily) -> tuple[ProbeDescriptor, ...]:
        """Every probe declared for one product family.

        Args:
            family: Which family.

        Returns:
            The descriptors, in declaration order.
        """
        return tuple(item for item in self.probes if item.family == family)

    def ambiguous_statuses(self) -> frozenset[int]:
        """Every status the contract declares ambiguous for a write.

        Returns:
            The codes. Compared against
            :data:`globin.domain.rest.AMBIGUOUS_STATUSES` by the contract test, in
            both directions, so neither can move without the other.
        """
        return frozenset(item.code for item in self.statuses if item.ambiguous_when_mutating)

    def ambiguous_exchange_codes(self) -> frozenset[int]:
        """Every venue code the contract declares ambiguous for a write.

        Returns:
            The codes.
        """
        return frozenset(item.code for item in self.exchange_codes if item.ambiguous_when_mutating)

    def as_record(self) -> dict[str, object]:
        """This contract as plain JSON-safe values."""
        return {
            "phase": self.phase,
            "observed_on": self.observed_on,
            "negotiation": self.negotiation.as_record(),
            "probes": [item.as_record() for item in self.probes],
            "statuses": [item.as_record() for item in self.statuses],
            "exchange_codes": [item.as_record() for item in self.exchange_codes],
            "limits": dict(self.limits),
            "prohibitions": dict(self.prohibitions),
        }
