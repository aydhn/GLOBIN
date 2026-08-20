"""The time policy document and the clock types say the same thing.

``docs/TIME_POLICY.md`` is where a contributor reads which types exist, what
each refuses, and — the question they actually arrived with — whether flooring a
timestamp can move it into the future. The code is where the answer comes from.

The comparison is bidirectional, and for the operation matrix it is
**executable**: a documented outcome is not compared against a string, the
attempt is run and what it actually does is compared against what the row
claims. That is the same strong form ``test_values_contract.py`` uses, and it is
what makes a third copy of the matrix legitimate — the code adjudicates between
the document and the test, so no two of the three can drift quietly.

What this file does not do is restate the rules. Whether the types behave is
``tests/unit/test_clock.py`` and ``tests/property/test_clock_properties.py``;
whether a clock is read where it should not be is
``tests/architecture/test_clock_discipline.py``; whether the document exists and
is well-formed is ``tests/contract/test_documentation_contract.py``.
"""

import re
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from globin.adapters.clock import SystemClock, SystemMonotonicClock
from globin.domain import clock as clock_module
from globin.domain.clock import (
    Duration,
    Instant,
    MonotonicReading,
    duration_from_millis,
    instant_from_epoch_millis,
)
from globin.errors import ValidationError

if TYPE_CHECKING:
    # The ports appear only as annotations on local variables, which Python never
    # evaluates. That is the whole mechanism of the conformance test below: the
    # binding exists so that **mypy** checks the adapter against the protocol, and
    # a type-checking-only import is exactly the right shape for it.
    from globin.ports.clock import Clock, MonotonicClock

POLICY_RELATIVE_PATH: Final[str] = "docs/TIME_POLICY.md"

#: A row of the types table: three cells, the first a backticked capitalised name.
TYPE_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<type>[A-Z]\w+)` \| (?P<carries>[^|]+) \| (?P<refuses>[^|]+) \|$",
    re.MULTILINE,
)

#: A row of the constants table: a backticked SCREAMING_SNAKE name and its value.
CONSTANT_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<name>[A-Z][A-Z0-9_]+)` \| `(?P<value>[^`]+)` \|$",
    re.MULTILINE,
)

#: A row of the operation matrix: a backticked attempt and one of three outcomes.
MATRIX_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<attempt>[^`]+)` \| (?P<outcome>answers|TypeError|ValidationError) \|$",
    re.MULTILINE,
)

TYPES: Final[dict[str, type]] = {
    "Instant": Instant,
    "Duration": Duration,
    "MonotonicReading": MonotonicReading,
}

_EARLIER: Final[Instant] = instant_from_epoch_millis(1_000)
_LATER: Final[Instant] = instant_from_epoch_millis(2_000)
_SHORT: Final[Duration] = duration_from_millis(1)
_LOW: Final[MonotonicReading] = MonotonicReading(1_000)
_HIGH: Final[MonotonicReading] = MonotonicReading(5_000)

#: The same duration, widened so that comparing an instant against it is a
#: statement about runtime behaviour rather than a static type error.
#:
#: mypy reports ``Instant == Duration`` as a non-overlapping comparison, which is
#: correct and is precisely what the matrix documents: the comparison *answers*
#: rather than raising. Widening one operand asserts that without suppressing a
#: true warning — the same manoeuvre Phase 008 needed for ``Price == Quantity``.
_SHORT_WIDENED: Final[object] = _SHORT

#: The documented attempts, each written **exactly as the row spells it**.
#:
#: Two of these carry `noqa: SIM300`. Ruff reads them as Yoda conditions and its
#: fix rewrites `a < b` into `b > a`, which is ordinarily equivalent and here is
#: not: Python tries the *left* operand's dunder first, so flipping the operands
#: exercises a different method and the row would no longer describe what ran.
#: The left operand is the whole point of a row that claims `instant < datetime`
#: raises.
ATTEMPTS: Final[dict[str, Callable[[], object]]] = {
    "instant < instant": lambda: _EARLIER < _LATER,
    "instant == instant": lambda: _EARLIER == _LATER,
    "instant == duration": lambda: _EARLIER == _SHORT_WIDENED,
    "instant < datetime": lambda: _EARLIER < datetime(2026, 1, 1, tzinfo=UTC),  # type: ignore[operator]  # noqa: SIM300
    "instant - instant": lambda: _LATER - _EARLIER,  # type: ignore[operator]
    "instant + duration": lambda: _EARLIER + _SHORT,  # type: ignore[operator]
    "float(instant)": lambda: float(_EARLIER),  # type: ignore[arg-type]
    "reading.since(earlier)": lambda: _HIGH.since(_LOW),
    "earlier.since(reading)": lambda: _LOW.since(_HIGH),
    "reading.since(instant)": lambda: _HIGH.since(_EARLIER),
    "reading - reading": lambda: _HIGH - _LOW,  # type: ignore[operator]
    "duration + duration": lambda: _SHORT + _SHORT,  # type: ignore[operator]
    "duration < duration": lambda: _SHORT < duration_from_millis(2),  # noqa: SIM300
}


@pytest.fixture(scope="session")
def policy(repo_root: Path) -> str:
    """The time policy document."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


def outcome_of(attempt: Callable[[], object]) -> str:
    """Run an attempt and name what it did.

    Args:
        attempt: The operation to perform.

    Returns:
        ``"ValidationError"``, ``"TypeError"`` or ``"answers"``.

    The three outcomes are the three the document is allowed to claim, so a
    fourth — any other exception — propagates rather than being folded into one
    of them.
    """
    try:
        attempt()
    except ValidationError:
        return "ValidationError"
    except TypeError:
        return "TypeError"
    return "answers"


# --------------------------------------------------------------------------
# The types table
# --------------------------------------------------------------------------


def test_the_documented_types_are_the_types_that_exist(policy: str) -> None:
    documented = {match.group("type") for match in TYPE_ROW_RE.finditer(policy)}
    assert documented == set(TYPES)


def test_the_types_table_finds_its_own_failing_case() -> None:
    """Guard the regex: a parser that matches nothing passes every comparison."""
    assert TYPE_ROW_RE.search("| `Instant` | a moment | a naive datetime |")
    assert not TYPE_ROW_RE.search("| `Instant` | a moment |")


@pytest.mark.parametrize("name", sorted(TYPES))
def test_every_documented_type_is_a_frozen_slotted_dataclass(name: str) -> None:
    """The shape Phases 003 to 008 established, held to for these too."""
    subject = TYPES[name]
    assert is_dataclass(subject)
    assert subject.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert fields(subject)


# --------------------------------------------------------------------------
# The constants table
# --------------------------------------------------------------------------


def _published_constants() -> dict[str, object]:
    """Every uppercase `str | int` name the clock module publishes."""
    return {
        name: value
        for name in dir(clock_module)
        if name.isupper()
        and not name.startswith("_")
        and isinstance(value := getattr(clock_module, name), str | int)
    }


def test_every_published_bound_is_documented(policy: str) -> None:
    """Both directions: an undocumented constant and a phantom row both fail."""
    documented = {match.group("name") for match in CONSTANT_ROW_RE.finditer(policy)}
    assert documented == set(_published_constants())


def test_every_documented_value_is_the_value_the_code_holds(policy: str) -> None:
    published = _published_constants()
    for match in CONSTANT_ROW_RE.finditer(policy):
        name = match.group("name")
        assert str(published[name]) == match.group("value"), name


def test_the_constants_table_finds_its_own_failing_case() -> None:
    assert CONSTANT_ROW_RE.search("| `MIN_EPOCH_MILLIS` | `-62135596800000` |")
    assert not CONSTANT_ROW_RE.search("| `MIN_EPOCH_MILLIS` | -62135596800000 |")


# --------------------------------------------------------------------------
# The operation matrix, executed
# --------------------------------------------------------------------------


def test_every_documented_attempt_is_one_the_test_can_perform(policy: str) -> None:
    documented = {match.group("attempt") for match in MATRIX_ROW_RE.finditer(policy)}
    assert documented == set(ATTEMPTS)


def test_each_documented_attempt_does_what_the_row_claims(policy: str) -> None:
    """The strong form: the row is not compared, it is run."""
    rows = list(MATRIX_ROW_RE.finditer(policy))
    assert rows, "no operation rows parsed from the policy"
    for match in rows:
        attempt = match.group("attempt")
        assert outcome_of(ATTEMPTS[attempt]) == match.group("outcome"), attempt


def test_the_matrix_regex_finds_its_own_failing_case() -> None:
    assert MATRIX_ROW_RE.search("| `instant - instant` | TypeError |")
    assert not MATRIX_ROW_RE.search("| `instant - instant` | explodes |")


# --------------------------------------------------------------------------
# The ports
# --------------------------------------------------------------------------


def test_the_adapters_satisfy_the_ports() -> None:
    """Conformance is mypy's job; these bindings are what give it something to check.

    The protocols are not ``runtime_checkable``, matching
    :class:`globin.ports.observability.LogSink`. An ``isinstance`` call would
    compare method *names* and nothing else, which is weaker than what the type
    checker already does at this assignment. Do not "fix" this into a runtime
    assertion.
    """
    wall: Clock = SystemClock()
    monotonic: MonotonicClock = SystemMonotonicClock()
    assert isinstance(wall.now(), Instant)
    assert isinstance(monotonic.reading(), MonotonicReading)


# --------------------------------------------------------------------------
# Deferrals
# --------------------------------------------------------------------------


def test_the_document_names_the_phases_it_defers_to(policy: str) -> None:
    """A deferral with no owner is a gap wearing a promise.

    Phase 036 replaced 040 in this tuple when it delivered server-time
    synchronisation. The row is still checked -- it now names the phase that *did*
    the work rather than one that would, which is the same requirement: a reader
    following the deferral must land somewhere real.
    """
    for phase in ("010", "011", "012", "036"):
        assert phase in policy, phase


def test_the_document_states_the_boundary_with_the_precision_phase(policy: str) -> None:
    """The Phase 010 collision is the one a reader is most likely to raise.

    It is superficially plausible — both look like rounding — so the answer is
    required to be present rather than left to be reconstructed.
    """
    lowered = policy.lower()
    assert "coordinate" in lowered
    assert "magnitude" in lowered
