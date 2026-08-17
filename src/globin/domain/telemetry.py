"""What GLOBIN measures about itself, as values a provider never sees.

[`observability.py`](observability.py) answers *what happened*; [`health.py`](health.py)
answers *is it well now*; this answers *what has it done over time*. The three are
deliberately separate, and the separation is load-bearing rather than tidy: a log
line is an event with a message, a health check is an instantaneous verdict, and a
metric is a number that only means anything when aggregated. Collapsing any pair
produces the thing everybody regrets — a log field used as a metric label.

**No provider type reaches this module, and none ever will.** OpenTelemetry and
Prometheus are mapped to at the adapter boundary, from a declared table.
`globin.*` is GLOBIN's own namespace and its spelling is not negotiable by an
exporter's grammar; where a provider needs a different spelling, that spelling is
*declared beside* the canonical one rather than derived from it.

**Every value here is an integer.** `JsonCodec` refuses a `float` at any depth of a
persisted document, so a duration is integer nanoseconds and a ratio is integer
parts per million. That is not a workaround: `MonotonicReading.since` already
returns integer nanoseconds, so the recording path performs *no arithmetic at
all*, and the one conversion a provider needs happens at the edge that needs it.

**Cardinality is refused at construction, not policed at runtime.** Every attribute
key a descriptor declares must carry a bounded set of permitted values, so the
number of series a metric family can produce is a product computable when the
descriptor is built. A descriptor that could exceed its own budget cannot be
constructed, which turns "we hope this stays bounded" into an arithmetic fact.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from globin.domain.observability import is_sensitive
from globin.errors import InternalError, ValidationError

#: The namespace every GLOBIN metric name begins with.
#:
#: What makes "provider-neutral" concrete rather than aspirational: an exporter
#: maps `globin.*` onto whatever a provider calls things, and nothing else may
#: claim the namespace.
METRIC_NAMESPACE: Final[str] = "globin."

#: Every character a metric name may contain.
#:
#: Spelled rather than compiled, for `EVENT_NAME_ALPHABET`'s reason: a layer
#: package performs no call at import, so `re.compile` is unavailable.
METRIC_NAME_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789._"

#: Every character an attribute key may contain.
#:
#: No dot, deliberately: a dotted key would read as a metric name, and the two
#: appear side by side in every exporter's output.
ATTRIBUTE_KEY_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_"

#: Every character an attribute value may contain.
#:
#: Excludes `=`, `,` and whitespace, which is what makes :meth:`MetricAttributes.series_key`
#: injective — two distinct attribute sets can never render the same key.
ATTRIBUTE_VALUE_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz0123456789_-."

#: The shortest a metric name may be, being the namespace plus one character.
MINIMUM_NAME_LENGTH: Final[int] = 8

#: The longest a metric name may be.
MAXIMUM_NAME_LENGTH: Final[int] = 80

#: The fewest dot-separated segments a metric name may have.
MINIMUM_NAME_SEGMENTS: Final[int] = 3

#: The most dot-separated segments a metric name may have.
MAXIMUM_NAME_SEGMENTS: Final[int] = 6

#: The longest one segment of a metric name may be.
MAXIMUM_SEGMENT_LENGTH: Final[int] = 20

#: The shortest an attribute key may be.
MINIMUM_ATTRIBUTE_KEY_LENGTH: Final[int] = 2

#: The longest an attribute key may be.
MAXIMUM_ATTRIBUTE_KEY_LENGTH: Final[int] = 24

#: The longest an attribute value may be.
MAXIMUM_ATTRIBUTE_VALUE_LENGTH: Final[int] = 32

#: The most attribute keys one metric may declare.
#:
#: Six, because the series count is the product of the domains and a seventh
#: dimension multiplies it again. A metric needing more is two metrics.
MAXIMUM_ATTRIBUTE_KEYS: Final[int] = 6

#: The most permitted values one attribute key may declare.
MAXIMUM_PERMITTED_VALUES: Final[int] = 12

#: The scale a ratio is stored at.
PARTS_PER_MILLION: Final[int] = 1_000_000

#: The largest value any metric may carry, and the reason is not Python's.
#:
#: ``2**53 - 1``. GLOBIN writes an integer exactly and reads it back exactly, so
#: nothing here would break at any width. Every JSON consumer that is *not* Python
#: holds numbers as IEEE-754 doubles and silently drops low bits past this point —
#: which is the same corruption `JsonCodec` refuses floats to prevent, arriving
#: through the integer door. Beyond this a value is refused and counted rather
#: than wrapped. In nanoseconds it is 104 days of accumulated duration, so it binds
#: only on a histogram total, and it binds loudly.
MAXIMUM_METRIC_VALUE: Final[int] = 9_007_199_254_740_991

#: Key fragments whose values would be unbounded rather than secret.
#:
#: **Deliberately disjoint from `SENSITIVE_KEY_FRAGMENTS`**, and a contract test
#: asserts the disjointness. `is_sensitive` answers *would this value be a
#: secret*; this answers *would this value be unbounded*. They are different
#: questions with different answers — an order id is not a secret and is fatal as
#: a label — so this is a second list rather than a duplicate of the first, and
#: `is_sensitive` is imported rather than restated.
HIGH_CARDINALITY_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "address",
    "email",
    "hostname",
    "identifier",
    "message",
    "order",
    "path",
    "symbol",
    "thread",
    "timestamp",
    "trace",
    "url",
    "user",
    "uuid",
)

#: Key suffixes that name an instant, which is unbounded by construction.
TIMESTAMP_KEY_SUFFIXES: Final[tuple[str, ...]] = ("_at", "_ms", "_ns", "_time")

#: The reason an attribute set was refused. One per rule, and the set is closed.
PROBLEM_KEY_NOT_DECLARED: Final[str] = "TELEMETRY_KEY_NOT_DECLARED"
PROBLEM_KEY_MISSING: Final[str] = "TELEMETRY_KEY_MISSING"
PROBLEM_KEY_MALFORMED: Final[str] = "TELEMETRY_KEY_MALFORMED"
PROBLEM_KEY_SENSITIVE: Final[str] = "TELEMETRY_KEY_SENSITIVE"
PROBLEM_KEY_UNBOUNDED: Final[str] = "TELEMETRY_KEY_UNBOUNDED"
PROBLEM_VALUE_NOT_PERMITTED: Final[str] = "TELEMETRY_VALUE_NOT_PERMITTED"
PROBLEM_VALUE_MALFORMED: Final[str] = "TELEMETRY_VALUE_MALFORMED"
PROBLEM_VALUE_OVERFLOW: Final[str] = "TELEMETRY_VALUE_OVERFLOW"
PROBLEM_TOO_MANY_KEYS: Final[str] = "TELEMETRY_TOO_MANY_KEYS"
PROBLEM_BUDGET_SPENT: Final[str] = "TELEMETRY_BUDGET_SPENT"


def attribute_problem_codes() -> tuple[str, ...]:
    """Every reason an observation can be refused.

    Returns:
        The codes, in declaration order.

    A function rather than a constant because a layer performs no call at import.
    Closed so a contract test can compare it against what the recorder actually
    emits **in both directions**: a code produced and not named here is a hole,
    and a name here nothing produces is a claim about a check that does not exist.
    """
    return (
        PROBLEM_KEY_NOT_DECLARED,
        PROBLEM_KEY_MISSING,
        PROBLEM_KEY_MALFORMED,
        PROBLEM_KEY_SENSITIVE,
        PROBLEM_KEY_UNBOUNDED,
        PROBLEM_VALUE_NOT_PERMITTED,
        PROBLEM_VALUE_MALFORMED,
        PROBLEM_VALUE_OVERFLOW,
        PROBLEM_TOO_MANY_KEYS,
        PROBLEM_BUDGET_SPENT,
    )


class MetricKind(StrEnum):
    """The three instrument kinds, and only three.

    No `SUMMARY`: provider-computed quantiles do not aggregate, which is the whole
    thing histograms replace. No `UP_DOWN_COUNTER`: it is a gauge with worse
    ergonomics, and :func:`gauge_adjusted` covers it.
    """

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricUnit(StrEnum):
    """The four base units a metric may be denominated in.

    A type rather than free text because the unit selects the stored scale, the
    permitted range and the name suffix, and a free-text unit makes all three
    unenforceable.
    """

    COUNT = "count"
    BYTES = "bytes"
    SECONDS = "seconds"
    RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class UnitSpec:
    """How one unit is stored, exported and bounded.

    Args:
        unit: Which unit this describes.
        exporter_name: The UCUM spelling a provider expects.
        scale_exponent: The power of ten between the stored integer and the base
            unit. ``-9`` means the integer is nanoseconds of a second.
        suffix: The metric-name segment that declares this unit.
        minimum: The smallest storable value.
        maximum: The largest, or ``None`` where only the global ceiling applies.
    """

    unit: MetricUnit
    exporter_name: str
    scale_exponent: int
    suffix: str
    minimum: int
    maximum: int | None


def unit_specifications() -> tuple[UnitSpec, ...]:
    """How every unit is stored.

    Returns:
        One specification per :class:`MetricUnit` member.

    **Nanoseconds for a second, and that choice is what removes arithmetic from
    the hot path.** `MonotonicReading.since` already returns integer nanoseconds,
    `encode_duration` already writes that integer, and `time.monotonic_ns` already
    reports it; any other scale would introduce a division per observation and a
    rounding decision nobody asked for.

    **Parts per million for a ratio.** Basis points cannot express one error in a
    hundred thousand. Parts per billion would claim nine digits of a quantity that,
    computed from a few thousand samples, has four real ones — the same falsehood
    `Reading` refuses when it insists a number that was not measured is never zero.
    """
    return (
        UnitSpec(MetricUnit.COUNT, "1", 0, "total", 0, None),
        UnitSpec(MetricUnit.BYTES, "By", 0, "bytes", 0, None),
        UnitSpec(MetricUnit.SECONDS, "s", -9, "nanoseconds", 0, None),
        UnitSpec(MetricUnit.RATIO, "1", -6, "ratio", 0, PARTS_PER_MILLION),
    )


def unit_specification(unit: MetricUnit) -> UnitSpec:
    """How one unit is stored.

    Args:
        unit: Which unit.

    Returns:
        Its specification.

    Raises:
        InternalError: If the unit has no entry, which means this module was
            edited in half — `identifiers.specification`'s rule and its wording.
    """
    for spec in unit_specifications():
        if spec.unit is unit:
            return spec
    msg = (
        f"metric unit {unit!r} has no specification; every member of MetricUnit "
        f"must be registered in unit_specifications()"
    )
    raise InternalError(msg)


def name_problems(name: str) -> tuple[str, ...]:
    """Judge whether a string is a canonical metric name.

    Args:
        name: The candidate.

    Returns:
        One sentence per reason it is not, empty when it is canonical.

    Problems rather than an exception, so a contract test can hold a whole
    registry against the rules without catching anything — the shape
    `member_problems` and `segment_problems` already have.
    """
    problems: list[str] = []
    if not name:
        return ("the metric name is empty",)
    if not name.startswith(METRIC_NAMESPACE):
        problems.append(f"the metric name {name!r} does not begin with {METRIC_NAMESPACE!r}")
    if len(name) < MINIMUM_NAME_LENGTH or len(name) > MAXIMUM_NAME_LENGTH:
        problems.append(
            f"the metric name {name!r} is outside "
            f"{MINIMUM_NAME_LENGTH}..{MAXIMUM_NAME_LENGTH} characters"
        )
    outside = sorted({character for character in name if character not in METRIC_NAME_ALPHABET})
    if outside:
        problems.append(
            f"the metric name {name!r} contains {''.join(outside)!r}, "
            f"which is outside the metric name alphabet"
        )
    segments = name.split(".")
    if len(segments) < MINIMUM_NAME_SEGMENTS or len(segments) > MAXIMUM_NAME_SEGMENTS:
        problems.append(
            f"the metric name {name!r} has {len(segments)} segments, outside "
            f"{MINIMUM_NAME_SEGMENTS}..{MAXIMUM_NAME_SEGMENTS}"
        )
    problems.extend(_segment_problems(name, segments))
    return tuple(problems)


def _segment_problems(name: str, segments: Sequence[str]) -> list[str]:
    """Judge every segment of an already-split metric name.

    Args:
        name: The whole name, for the messages.
        segments: Its dot-separated parts.

    Returns:
        One sentence per problem.

    Split out because an empty segment and a bad character are different
    complaints about the same string, and both spellings pass a whole-name
    alphabet check while naming an empty namespace level.
    """
    problems: list[str] = []
    for segment in segments:
        if not segment:
            problems.append(f"the metric name {name!r} has an empty segment")
            continue
        if len(segment) > MAXIMUM_SEGMENT_LENGTH:
            problems.append(f"the segment {segment!r} is longer than {MAXIMUM_SEGMENT_LENGTH}")
        if not segment[0].isalpha():
            problems.append(f"the segment {segment!r} does not begin with a letter")
        if segment.endswith("_") or "__" in segment:
            problems.append(f"the segment {segment!r} has a trailing or doubled underscore")
    return problems


def is_high_cardinality(key: str) -> bool:
    """Whether an attribute key names something unbounded.

    Args:
        key: The candidate key, in any case.

    Returns:
        Whether it would produce an unbounded set of values.

    Three rules rather than an enumeration of spellings. A fragment match catches
    the nouns; ``id``/``_id`` catches every identifier suffix at once, which is
    what makes `user_id`, `order_id`, `request_id` and `span_id` a single rule
    rather than four; and a timestamp suffix catches every spelling of an instant.
    """
    folded = key.casefold()
    if folded == "id" or folded.endswith("_id"):
        return True
    if any(folded.endswith(suffix) for suffix in TIMESTAMP_KEY_SUFFIXES):
        return True
    return any(fragment in folded for fragment in HIGH_CARDINALITY_KEY_FRAGMENTS)


@dataclass(frozen=True, slots=True)
class AttributeDomain:
    """One attribute key, and the whole set of values it may take.

    Args:
        key: The attribute key.
        permitted: Every value it may take, which is what bounds the series count.

    Raises:
        ValidationError: If the key is malformed, secret-shaped or unbounded, or
            if the permitted set is empty, oversized or malformed.

    **A key with no bounded value set cannot be declared**, and that single rule is
    what makes a metric family's series count computable at construction rather
    than observable only in production.
    """

    key: str
    permitted: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse a dimension that could not be bounded, or should not be recorded."""
        problems = list(_key_problems(self.key))
        if is_sensitive(self.key):
            problems.append(f"the attribute key {self.key!r} names a credential")
        if is_high_cardinality(self.key):
            problems.append(f"the attribute key {self.key!r} names an unbounded value")
        if not self.permitted:
            problems.append(f"the attribute key {self.key!r} declares no permitted value")
        if len(self.permitted) > MAXIMUM_PERMITTED_VALUES:
            problems.append(
                f"the attribute key {self.key!r} declares more than "
                f"{MAXIMUM_PERMITTED_VALUES} permitted values"
            )
        if len(set(self.permitted)) != len(self.permitted):
            problems.append(f"the attribute key {self.key!r} repeats a permitted value")
        for value in self.permitted:
            problems.extend(_value_problems(value))
        if problems:
            raise ValidationError("; ".join(problems))
        object.__setattr__(self, "permitted", tuple(sorted(self.permitted)))


def _key_problems(key: str) -> tuple[str, ...]:
    """Judge an attribute key's spelling.

    Args:
        key: The candidate.

    Returns:
        One sentence per problem.
    """
    problems: list[str] = []
    if len(key) < MINIMUM_ATTRIBUTE_KEY_LENGTH or len(key) > MAXIMUM_ATTRIBUTE_KEY_LENGTH:
        problems.append(
            f"the attribute key {key!r} is outside "
            f"{MINIMUM_ATTRIBUTE_KEY_LENGTH}..{MAXIMUM_ATTRIBUTE_KEY_LENGTH} characters"
        )
    outside = sorted({character for character in key if character not in ATTRIBUTE_KEY_ALPHABET})
    if outside:
        problems.append(f"the attribute key {key!r} contains {''.join(outside)!r}")
    return tuple(problems)


def _value_problems(value: str) -> tuple[str, ...]:
    """Judge an attribute value's spelling.

    Args:
        value: The candidate.

    Returns:
        One sentence per problem.
    """
    problems: list[str] = []
    if not value or len(value) > MAXIMUM_ATTRIBUTE_VALUE_LENGTH:
        problems.append(
            f"the attribute value {value!r} is empty or longer than "
            f"{MAXIMUM_ATTRIBUTE_VALUE_LENGTH}"
        )
    outside = sorted(
        {character for character in value if character not in ATTRIBUTE_VALUE_ALPHABET}
    )
    if outside:
        problems.append(f"the attribute value {value!r} contains {''.join(outside)!r}")
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class MetricAttributes:
    """The dimensions one measurement carries, canonically ordered.

    Args:
        pairs: Key/value pairs, sorted on construction.

    Raises:
        ValidationError: If any key or value is malformed, if a key repeats, if
            there are too many, or if any key names a credential.

    **Values are `str`, never `object`**, which is the deliberate divergence from
    `LogEvent.fields`. An arbitrary object has unbounded rendering, and unbounded
    rendering is unbounded cardinality.

    **A credential-shaped key is refused rather than redacted**, which is the
    second divergence and the one worth a reviewer's attention. `LogEvent`
    substitutes, and for a log field that is right: a field is a leaf, and
    substituting loses one datum. An attribute is a *dimension*, and substituting
    it merges two series under a name that means nothing — a real series with a
    fake identity, which is worse than no series at all.
    """

    pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Refuse an unrecordable dimension set, then canonicalise the order."""
        problems: list[str] = []
        if len(self.pairs) > MAXIMUM_ATTRIBUTE_KEYS:
            problems.append(f"more than {MAXIMUM_ATTRIBUTE_KEYS} attribute keys")
        keys = [key for key, _ in self.pairs]
        if len(set(keys)) != len(keys):
            problems.append("an attribute key is repeated")
        for key, value in self.pairs:
            problems.extend(_key_problems(key))
            problems.extend(_value_problems(value))
            if is_sensitive(key):
                problems.append(f"the attribute key {key!r} names a credential")
        if problems:
            raise ValidationError("; ".join(problems))
        object.__setattr__(self, "pairs", tuple(sorted(self.pairs)))

    def series_key(self) -> str:
        """A stable, injective identity for this dimension set.

        Returns:
            The pairs rendered as ``key=value`` joined by commas.

        Injective because the value alphabet excludes both separators, so no two
        distinct attribute sets can render the same key.
        """
        return ",".join(f"{key}={value}" for key, value in self.pairs)


def attribute_problems(
    domains: Sequence[AttributeDomain], supplied: Mapping[str, object]
) -> tuple[str, ...]:
    """Judge a supplied attribute set against what a descriptor declares.

    Args:
        domains: The declared dimensions.
        supplied: What the caller passed, which may be anything at all.

    Returns:
        Zero or more codes from :func:`attribute_problem_codes`, deduplicated and
        in declaration order.

    **Total, and it never raises.** A telemetry call must not be able to take down
    the code it is measuring, so this screens and the caller drops.

    **Codes, not sentences, and never the value.** `member_problems` quotes the
    offending member because GLOBIN chose that filename; here the offending token
    is arbitrary caller data that could be a credential, so the value is never
    named under any circumstance and the key is named nowhere in this return type
    at all.

    **Every declared key must be supplied.** A point carrying a subset would give
    one family two series shapes, which breaks aggregation silently. The cost is
    that optional attributes are impossible; the sanctioned answers are a bounded
    domain with an explicit member such as ``"none"``, or two metric families.
    """
    found: list[str] = []
    declared = {domain.key: domain for domain in domains}
    if len(supplied) > MAXIMUM_ATTRIBUTE_KEYS:
        found.append(PROBLEM_TOO_MANY_KEYS)
    for key in declared:
        if key not in supplied:
            found.append(PROBLEM_KEY_MISSING)
            break
    for key, value in supplied.items():
        found.extend(_supplied_problems(key, value, declared))
    ordered = [code for code in attribute_problem_codes() if code in found]
    return tuple(ordered)


def _supplied_problems(
    key: object, value: object, declared: Mapping[str, AttributeDomain]
) -> list[str]:
    """Judge one supplied pair against the declared dimensions.

    Args:
        key: The supplied key, which may not even be a string.
        value: The supplied value, likewise.
        declared: The declared dimensions by key.

    Returns:
        The codes this pair earns.
    """
    if not isinstance(key, str) or _key_problems(key):
        return [PROBLEM_KEY_MALFORMED]
    if is_sensitive(key):
        return [PROBLEM_KEY_SENSITIVE]
    if is_high_cardinality(key):
        return [PROBLEM_KEY_UNBOUNDED]
    domain = declared.get(key)
    if domain is None:
        return [PROBLEM_KEY_NOT_DECLARED]
    if not isinstance(value, str) or _value_problems(value):
        return [PROBLEM_VALUE_MALFORMED]
    if value not in domain.permitted:
        return [PROBLEM_VALUE_NOT_PERMITTED]
    return []


def ratio_parts_per_million(numerator: int, denominator: int) -> int:
    """Express a ratio as an integer, flooring rather than rounding.

    Args:
        numerator: The part.
        denominator: The whole.

    Returns:
        The ratio in parts per million.

    Raises:
        ValidationError: If the denominator is not positive, if the numerator is
            negative or exceeds it, or if either is a ``bool``.

    Floors, and says so in the name, because there is no default rounding mode
    anywhere in GLOBIN and a function that silently picked one would be making a
    decision `precision.py` requires every call site to make.

    **Prefer two counters to a ratio.** A ratio GLOBIN computes is a derived
    quantity, and a derived quantity stored as fixed point is a rounding somebody
    owns for ever. This exists for a quantity a *source* reports as a fraction — a
    queue fill level, a cache occupancy — not for one GLOBIN divides.
    """
    for name, number in (("numerator", numerator), ("denominator", denominator)):
        if isinstance(number, bool) or not isinstance(number, int):
            msg = f"the {name} must be a plain int"
            raise ValidationError(msg)
    if denominator <= 0:
        msg = f"the denominator {denominator} is not positive"
        raise ValidationError(msg)
    if numerator < 0 or numerator > denominator:
        msg = f"the ratio {numerator}/{denominator} is outside 0..1"
        raise ValidationError(msg)
    return numerator * PARTS_PER_MILLION // denominator
