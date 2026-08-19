"""How old the record of a venue document is, and when that stops being acceptable.

Phase 033 recorded *when* each official document was read. Nothing consumed that
date, so a registry read once and never again looked exactly like one re-checked
yesterday. This module is what turns an access date into a decision.

**The decision it feeds is a refusal, not a warning.** A REST endpoint resting on
a source past its re-check interval cannot be resolved —
:func:`globin.domain.rest_endpoint.resolve` returns
:attr:`~globin.domain.rest_endpoint.ResolutionStatus.SOURCE_STALE` and no socket
opens. That is the join between Phase 034's two halves: the transport's fail-closed
rule names ``stale`` among the states it must refuse, and nothing in this
repository could answer whether a source *was* stale until the cadence existed.

**Today is an argument, never a reading.** Every function here takes ``as_of`` as
an ISO date. A domain module may not read a clock — ``docs/architecture/dependency-rules.toml``
declares ``time`` I/O-capable — and the constraint is the better design anyway: a
test can ask what the registry looks like in two years without waiting.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from globin.domain.api_reality import ApiRealitySnapshot, SourceObservation
from globin.errors import ValidationError

SCHEMA_VERSION: int = 1
"""The version of the policy document this module reads."""

PHASE: int = 34
"""The phase that built this."""

MIN_RECHECK_DAYS: int = 1
"""The shortest interval a cadence rule may declare.

Zero would mean *stale the moment it is written*, which is not a cadence but a
refusal to trust anything. A rule that wants that should remove the source.
"""

MAX_RECHECK_DAYS: int = 3650
"""The longest interval a cadence rule may declare.

Ten years. Not a limit anybody will reach — it exists so the field is bounded, and
so a typo that adds a digit is refused rather than silently disabling the cadence
for a decade longer than intended.
"""


def _require_whole(value: object, *, field: str) -> None:
    """Refuse an interval that is not a whole number of days.

    Args:
        value: What was supplied. Typed as :class:`object` so the check is a real
            one rather than one mypy has already proved redundant — the same
            distinction ``domain/values.py`` draws for the same reason.
        field: How to name it in a message.

    Raises:
        ValidationError: If it is not an :class:`int`, or is a :class:`bool`.

    ``bool`` is refused explicitly because it is a subclass of ``int``, so ``True``
    would otherwise be accepted as a one-day cadence.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{field} declares a re-check interval of {value!r}, which is not a whole number"
        raise ValidationError(msg)


class Freshness(StrEnum):
    """Whether the record of one source is still within its declared cadence.

    Three members, and the third is not an error state. A machine whose clock is
    behind the date a document was read produces a negative age, which says
    something true about the *machine* rather than about the source — so it is
    reported rather than folded into either of the other two.
    """

    FRESH = "fresh"
    """Read within its cadence. May be relied on."""

    STALE = "stale"
    """Past its cadence. Everything resting on it fails closed until it is re-read."""

    AHEAD_OF_CLOCK = "ahead_of_clock"
    """Recorded as read later than the date being compared against.

    Never treated as stale — a record cannot be too old to trust because this
    machine's clock is wrong — and never silently called fresh either, because an
    operator whose clock is days out wants to know that before they debug anything
    else.
    """

    @property
    def blocks(self) -> bool:
        """Whether this freshness prevents an endpoint being resolved."""
        return self is Freshness.STALE


@dataclass(frozen=True, slots=True)
class CadenceRule:
    """How often one regime of source must be re-read.

    Raises:
        ValidationError: On an empty regime, an interval outside
            :data:`MIN_RECHECK_DAYS` to :data:`MAX_RECHECK_DAYS`, or a rule that
            states no reason.

    ``reason`` is required rather than optional. A cadence is GLOBIN's own
    judgement rather than a venue fact, so it carries an argument where every row
    in the registry carries a citation.
    """

    regime: str
    recheck_days: int
    reason: str

    def __post_init__(self) -> None:
        """Refuse a rule that would not bound anything, or that argues nothing."""
        if not self.regime:
            msg = "a cadence rule names no regime"
            raise ValidationError(msg)
        _require_whole(self.recheck_days, field=f"regime {self.regime!r}")
        if not MIN_RECHECK_DAYS <= self.recheck_days <= MAX_RECHECK_DAYS:
            msg = (
                f"regime {self.regime!r} declares a re-check interval of "
                f"{self.recheck_days} days, outside {MIN_RECHECK_DAYS}-{MAX_RECHECK_DAYS}"
            )
            raise ValidationError(msg)
        if not self.reason:
            msg = f"regime {self.regime!r} declares a cadence and no reason for it"
            raise ValidationError(msg)

    def as_record(self) -> dict[str, object]:
        """This rule as plain JSON-safe values."""
        return {"regime": self.regime, "recheck_days": self.recheck_days}


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    """Every cadence rule, and what applies to a regime none of them names.

    Raises:
        ValidationError: On a repeated regime, or a default outside the permitted
            interval range.

    **The policy document's ``[review]`` table is deliberately absent from this
    type.** It declares which gate findings need a written acknowledgement, which
    is a repository-maintenance rule with no bearing on whether a request may be
    sent — so the package does not parse it and the gate under ``tools/`` does.
    Two readers of one document, each taking the half it acts on.
    """

    rules: tuple[CadenceRule, ...]
    default_days: int
    default_reason: str

    def __post_init__(self) -> None:
        """Refuse a policy that contradicts itself."""
        regimes = [item.regime for item in self.rules]
        if len(set(regimes)) != len(regimes):
            msg = f"a regime declares a cadence more than once: {sorted(regimes)}"
            raise ValidationError(msg)
        if not MIN_RECHECK_DAYS <= self.default_days <= MAX_RECHECK_DAYS:
            msg = (
                f"the default re-check interval is {self.default_days} days, outside "
                f"{MIN_RECHECK_DAYS}-{MAX_RECHECK_DAYS}"
            )
            raise ValidationError(msg)

    def days_for(self, regime: str) -> int:
        """How long a source of one regime may go un-re-read.

        Args:
            regime: The regime's spelling.

        Returns:
            The declared interval, or the default when no rule names the regime.

        A regime with no rule gets the default rather than an exception, so a
        regime added to the registry later is bounded from the moment it appears
        instead of on the day somebody remembers to add a row here.
        """
        return next(
            (item.recheck_days for item in self.rules if item.regime == regime),
            self.default_days,
        )

    def as_record(self) -> dict[str, object]:
        """This policy as plain JSON-safe values."""
        return {
            "rules": [item.as_record() for item in self.rules],
            "default_days": self.default_days,
        }


@dataclass(frozen=True, slots=True)
class SourceAge:
    """One source, how old its record is, and whether that is still acceptable."""

    identifier: str
    regime: str
    accessed: str
    age_days: int
    allowed_days: int
    freshness: Freshness
    refreshable: bool

    def as_record(self) -> dict[str, object]:
        """This age as plain JSON-safe values."""
        return {
            "identifier": self.identifier,
            "regime": self.regime,
            "accessed": self.accessed,
            "age_days": self.age_days,
            "allowed_days": self.allowed_days,
            "freshness": self.freshness.value,
            "refreshable": self.refreshable,
        }


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    """How old every recorded source is, as of one date."""

    as_of: str
    ages: tuple[SourceAge, ...]

    @property
    def stale(self) -> tuple[str, ...]:
        """Every source past its cadence, by identifier.

        Returns:
            The identifiers, sorted. This is what
            :func:`globin.domain.rest_endpoint.resolve` is handed, and an endpoint
            citing one of them cannot be resolved.
        """
        return tuple(sorted(item.identifier for item in self.ages if item.freshness.blocks))

    @property
    def ahead_of_clock(self) -> tuple[str, ...]:
        """Every source recorded as read after :attr:`as_of`, by identifier.

        Returns:
            The identifiers, sorted. Non-empty means this machine's clock is behind
            the dates in the registry, which is worth saying out loud before an
            operator concludes anything else from a freshness report.
        """
        return tuple(
            sorted(
                item.identifier for item in self.ages if item.freshness is Freshness.AHEAD_OF_CLOCK
            )
        )

    def counts(self) -> dict[str, int]:
        """How many sources carry each freshness.

        Returns:
            Every :class:`Freshness` value mapped to its count, zeroes included —
            an absent key would read as an absent question.
        """
        return {
            value.value: sum(1 for item in self.ages if item.freshness is value)
            for value in Freshness
        }

    def as_record(self) -> dict[str, object]:
        """This report as plain JSON-safe values."""
        return {
            "as_of": self.as_of,
            "counts": self.counts(),
            "stale": list(self.stale),
            "ahead_of_clock": list(self.ahead_of_clock),
            "ages": [item.as_record() for item in self.ages],
        }


def _age_days(accessed: str, as_of: str) -> int:
    """How many days lie between two ISO dates.

    Args:
        accessed: When the source was read.
        as_of: The date being compared against.

    Returns:
        The difference in whole days, negative when ``accessed`` is later.

    Raises:
        ValidationError: If either date is not an ISO calendar date. The registry
            already refuses a malformed access date at construction, so this bites
            on ``as_of`` — a caller passing a timestamp where a date belongs.
    """
    try:
        return (date.fromisoformat(as_of) - date.fromisoformat(accessed)).days
    except ValueError as fault:
        msg = f"an ingestion date is not an ISO calendar date: {fault}"
        raise ValidationError(msg) from fault


def age_of(source: SourceObservation, policy: IngestionPolicy, *, as_of: str) -> SourceAge:
    """How old one source's record is, and whether it is still acceptable.

    Args:
        source: The recorded source.
        policy: The declared cadence.
        as_of: The date to compare against, as an ISO date.

    Returns:
        The age.
    """
    allowed = policy.days_for(source.regime.value)
    days = _age_days(source.accessed, as_of)
    if days < 0:
        freshness = Freshness.AHEAD_OF_CLOCK
    elif days > allowed:
        freshness = Freshness.STALE
    else:
        freshness = Freshness.FRESH
    return SourceAge(
        identifier=source.identifier,
        regime=source.regime.value,
        accessed=source.accessed,
        age_days=days,
        allowed_days=allowed,
        freshness=freshness,
        refreshable=source.refreshable,
    )


def assess(snapshot: ApiRealitySnapshot, policy: IngestionPolicy, *, as_of: str) -> FreshnessReport:
    """How old every source in the registry is, as of one date.

    Args:
        snapshot: Phase 033's registry.
        policy: The declared cadence.
        as_of: The date to compare against, as an ISO date.

    Returns:
        The report, with sources in identifier order so two runs agree.

    **Strictly greater than, not greater or equal.** A source read exactly
    ``recheck_days`` ago is still fresh; it goes stale the following day. The
    alternative makes an interval of one day mean "stale after zero days", which is
    not what anybody writing ``recheck_days = 1`` intends.
    """
    return FreshnessReport(
        as_of=as_of,
        ages=tuple(
            age_of(item, policy, as_of=as_of)
            for item in sorted(snapshot.sources, key=lambda source: source.identifier)
        ),
    )
