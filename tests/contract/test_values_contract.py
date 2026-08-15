"""The value types policy document and the value types say the same thing.

``docs/VALUE_TYPES_POLICY.md`` is where a contributor reads which types exist,
what each refuses and — the question they actually arrived with — whether two
values can be added together. The code is where the answer comes from. Two
statements of one rule diverge unless something compares them, and here the
dangerous direction is a documented *permission*: a table saying an operation
works, read by somebody who then writes code around it.

The comparison is bidirectional and, for the operation matrix, executable. A
documented outcome is not compared against a string; the attempt is **run**, and
what it actually does is compared against what the row claims. That is the same
strong form ``tests/contract/test_configuration_contract.py`` uses when it feeds
a documented default back through the binding, and it is why a third copy of the
matrix is legitimate here: the code adjudicates between the document and the
test, so no two of the three can drift apart quietly.

What this file does not do is restate the rules. Whether the types behave is
``tests/unit/test_values.py`` and ``tests/property/test_values_properties.py``;
whether the document exists and is well-formed is
``tests/contract/test_documentation_contract.py``.
"""

import re
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from globin.domain import values
from globin.domain.precision import Increment, Rounding, increment
from globin.domain.values import (
    Currency,
    Price,
    Quantity,
    Side,
    Symbol,
    align_price,
    align_quantity,
    currency,
    notional,
    price,
    quantity,
)
from globin.errors import ValidationError

POLICY_RELATIVE_PATH: Final[str] = "docs/VALUE_TYPES_POLICY.md"

#: A row of the types table: three cells, the first a backticked capitalised name.
#: The other tables in the document have two columns, so the trailing cell is what
#: keeps this from matching them.
TYPE_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<type>[A-Z]\w+)` \| (?P<carries>[^|]+) \| (?P<refuses>[^|]+) \|$",
    re.MULTILINE,
)

#: A row of the constants table: a backticked SCREAMING_SNAKE name and its value.
CONSTANT_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<name>[A-Z][A-Z0-9_]+)` \| `(?P<value>[^`]+)` \|$",
    re.MULTILINE,
)

#: A row of the operation matrix. The outcome cell is restricted to the three
#: words the document defines, which is what stops this matching a constants row.
MATRIX_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<attempt>[^`]+)` \| `(?P<outcome>answers|ValidationError|TypeError)` \|$",
    re.MULTILINE,
)

#: Anything written between backticks, for reading a cell that lists several names.
BACKTICKED_RE: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")

BTC_USDT: Final[Symbol] = Symbol(base=Currency(code="BTC"), quote=Currency(code="USDT"))
ETH_USDT: Final[Symbol] = Symbol(base=Currency(code="ETH"), quote=Currency(code="USDT"))

#: A grid to align onto, and a value that does not sit on it. Together they let
#: the matrix exercise both an alignment that answers and one that refuses.
A_TICK: Final[Increment] = increment("0.01")

#: Sample values, annotated `Any` on purpose. Every arithmetic attempt below is a
#: static error that mypy would refuse — which is half the guarantee, and not the
#: half this file is checking. Routing through `Any` lets the runtime answer for
#: itself. Named in lowercase because they are samples, not constants.
a_price: Any = price("1", BTC_USDT)
a_dearer_price: Any = price("2", BTC_USDT)
an_eth_price: Any = price("1", ETH_USDT)
a_quantity: Any = quantity("1", "BTC")
a_larger_quantity: Any = quantity("2", "BTC")
an_eth_quantity: Any = quantity("1", "ETH")
an_unaligned_price: Any = price("1.239", BTC_USDT)
btc: Any = currency("BTC")
eth: Any = currency("ETH")

#: Every documented row of the operation matrix, as something executable. A
#: mapping rather than `eval`, because `eval` is what ruff's S307 exists to stop
#: and because a callable can be type-checked.
ATTEMPTS: Final[dict[str, Callable[[], object]]] = {
    "Price < Price, same market": lambda: a_price < a_dearer_price,
    "Price < Price, different market": lambda: a_price < an_eth_price,
    "Price == Price, different market": lambda: a_price == an_eth_price,
    "Price < Quantity": lambda: a_price < a_quantity,
    "Price < Decimal": lambda: a_price < Decimal(1),
    "Price == Quantity": lambda: a_price == a_quantity,
    "Quantity < Quantity, same asset": lambda: a_quantity < a_larger_quantity,
    "Quantity < Quantity, different asset": lambda: a_quantity < an_eth_quantity,
    "hash of a Price": lambda: hash(a_price),
    "Quantity + Quantity, same asset": lambda: a_quantity + a_larger_quantity,
    "Quantity + Quantity, different asset": lambda: a_quantity + an_eth_quantity,
    "Quantity - Quantity, leaving a remainder": lambda: a_larger_quantity - a_quantity,
    "Quantity - Quantity, going below zero": lambda: a_quantity - a_larger_quantity,
    "notional of a Price and a Quantity of its base": lambda: notional(a_price, a_quantity),
    "notional of a Price and a Quantity of another asset": lambda: notional(
        a_price, an_eth_quantity
    ),
    "alignment of a Price onto a tick": lambda: align_price(
        a_price, tick=A_TICK, rounding=Rounding.FLOOR
    ),
    "alignment of a Quantity onto a step": lambda: align_quantity(
        a_quantity, step=A_TICK, rounding=Rounding.FLOOR
    ),
    "alignment with a rounding mode spelled as a string": lambda: align_price(
        a_price,
        tick=A_TICK,
        rounding="FLOOR",  # type: ignore[arg-type]
    ),
    "alignment of an unaligned value with EXACT": lambda: align_price(
        an_unaligned_price, tick=A_TICK, rounding=Rounding.EXACT
    ),
    "Price + Price": lambda: a_price + a_dearer_price,
    "Price - Price": lambda: a_dearer_price - a_price,
    "Price * Quantity": lambda: a_price * a_quantity,
    "negation of a Price": lambda: -a_price,
    "float of a Price": lambda: float(a_price),
    "int of a Quantity": lambda: int(a_quantity),
    "round of a Price": lambda: round(a_price),
    "sum of two Prices": lambda: sum([a_price, a_dearer_price]),
    "sum of two Quantities": lambda: sum([a_quantity, a_larger_quantity]),
    "Currency < Currency": lambda: btc < eth,
    "Symbol < Symbol": lambda: BTC_USDT < ETH_USDT,  # type: ignore[operator]
}

#: What each type carries, read off the code rather than the document.
CARRIED: Final[dict[str, tuple[str, ...]]] = {
    "Side": tuple(member.name for member in Side),
    "Currency": tuple(item.name for item in fields(Currency)),
    "Symbol": tuple(item.name for item in fields(Symbol)),
    "Quantity": tuple(item.name for item in fields(Quantity)),
    "Price": tuple(item.name for item in fields(Price)),
}


def outcome_of(attempt: Callable[[], object]) -> str:
    """Run an attempt and name what it did, in the document's vocabulary.

    Args:
        attempt: The expression, as a callable.

    Returns:
        ``"ValidationError"``, ``"TypeError"``, or ``"answers"`` when it returned
        a value instead of raising.

    The two exception classes cannot overlap: :exc:`~globin.errors.ValidationError`
    descends from :exc:`~globin.errors.GlobinError`, which inherits no builtin
    (ADR-0022), so the order of the handlers is not load-bearing.
    """
    try:
        attempt()
    except ValidationError:
        return "ValidationError"
    except TypeError:
        return "TypeError"
    return "answers"


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The value types policy document as written."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Guard the guards
# --------------------------------------------------------------------------


def test_the_type_row_reader_finds_its_own_failing_case() -> None:
    """Every comparison below is only as good as this parser.

    One that silently matched nothing would make each of them pass while
    comparing two empty sets against each other.
    """
    document = "\n".join(
        [
            "| Type | Carries | Refuses |",
            "|---|---|---|",
            "| `Alpha` | `one`, `two` | nothing at all |",
            "| `BETA_CONSTANT` | `4` |",
            "",
        ]
    )
    rows = TYPE_ROW_RE.findall(document)
    assert [row[0] for row in rows] == ["Alpha"]
    assert not TYPE_ROW_RE.findall("no table here")


def test_the_constant_row_reader_finds_its_own_failing_case() -> None:
    document = "\n".join(
        [
            "| Constant | Value |",
            "|---|---|",
            "| `SOME_BOUND` | `4` |",
            "| `Price < Price, same market` | `answers` |",
            "",
        ]
    )
    assert CONSTANT_ROW_RE.findall(document) == [("SOME_BOUND", "4")]
    assert not CONSTANT_ROW_RE.findall("no table here")


def test_the_matrix_row_reader_finds_its_own_failing_case() -> None:
    document = "\n".join(
        [
            "| Attempt | Outcome |",
            "|---|---|",
            "| `Alpha < Beta` | `TypeError` |",
            "| `SOME_BOUND` | `4` |",
            "",
        ]
    )
    assert MATRIX_ROW_RE.findall(document) == [("Alpha < Beta", "TypeError")]
    assert not MATRIX_ROW_RE.findall("no table here")


# --------------------------------------------------------------------------
# The types, and what they carry
# --------------------------------------------------------------------------


def test_the_documented_types_are_exactly_the_types_that_exist(policy: str) -> None:
    documented = {match.group("type") for match in TYPE_ROW_RE.finditer(policy)}
    assert documented == set(CARRIED)


def test_every_documented_type_carries_exactly_what_the_code_gives_it(policy: str) -> None:
    """Field names and enumeration members, compared in both directions."""
    for match in TYPE_ROW_RE.finditer(policy):
        name = match.group("type")
        documented = set(BACKTICKED_RE.findall(match.group("carries")))
        assert documented == set(CARRIED[name]), name


def test_every_documented_type_says_what_it_refuses(policy: str) -> None:
    """A blank refusal cell would make the table decorative."""
    for match in TYPE_ROW_RE.finditer(policy):
        assert match.group("refuses").strip(), match.group("type")


def test_the_four_value_classes_are_frozen_dataclasses() -> None:
    """The document calls them values; this is what the word has to mean."""
    for held in (Currency, Symbol, Quantity, Price):
        assert is_dataclass(held), held
        params = getattr(held, "__dataclass_params__", None)
        assert params is not None, held
        assert params.frozen, held


# --------------------------------------------------------------------------
# The constants
# --------------------------------------------------------------------------


def test_the_document_declares_at_least_one_constant(policy: str) -> None:
    """An empty table would make the comparison below vacuous."""
    assert CONSTANT_ROW_RE.findall(policy)


def test_every_documented_constant_holds_the_value_the_code_holds(policy: str) -> None:
    for match in CONSTANT_ROW_RE.finditer(policy):
        name = match.group("name")
        assert hasattr(values, name), f"documented constant does not exist: {name}"
        assert str(getattr(values, name)) == match.group("value"), name


def test_every_published_bound_is_documented(policy: str) -> None:
    """The other direction: a constant the module publishes and nobody wrote down."""
    documented = {match.group("name") for match in CONSTANT_ROW_RE.finditer(policy)}
    published = {
        name
        for name in dir(values)
        if name.isupper()
        and not name.startswith("_")
        and isinstance(getattr(values, name), str | int)
    }
    assert published == documented


# --------------------------------------------------------------------------
# The operation matrix, executed
# --------------------------------------------------------------------------


def test_every_documented_attempt_is_executable(policy: str) -> None:
    documented = {match.group("attempt") for match in MATRIX_ROW_RE.finditer(policy)}
    assert documented <= set(ATTEMPTS), (
        f"documented but not executable: {documented - set(ATTEMPTS)}"
    )


def test_every_executable_attempt_is_documented(policy: str) -> None:
    documented = {match.group("attempt") for match in MATRIX_ROW_RE.finditer(policy)}
    assert set(ATTEMPTS) <= documented, f"executable but undocumented: {set(ATTEMPTS) - documented}"


def test_each_documented_attempt_does_what_the_row_claims(policy: str) -> None:
    """The strong form: the row is run, not read.

    Comparing the outcome column against a list of expected strings would prove
    two spellings match. Executing the attempt proves the document describes the
    code, which is the only claim worth making.
    """
    for match in MATRIX_ROW_RE.finditer(policy):
        attempt = match.group("attempt")
        assert outcome_of(ATTEMPTS[attempt]) == match.group("outcome"), attempt


def test_the_outcome_reader_distinguishes_all_three_outcomes() -> None:
    """Guard the guard, again: a classifier collapsing two outcomes would pass everything."""
    assert outcome_of(lambda: a_price < an_eth_price) == "ValidationError"
    assert outcome_of(lambda: a_price + a_dearer_price) == "TypeError"
    assert outcome_of(lambda: a_price < a_dearer_price) == "answers"


def test_the_document_names_the_phases_it_defers_to(policy: str) -> None:
    """The register is small, and a reader's first question is what is missing.

    Naming the owning phase is what stops the answer being inferred from the
    absence of a rule — particularly for arithmetic, whose absence is otherwise
    indistinguishable from an oversight.
    """
    for phase in ("009", "010", "011", "012", "242"):
        assert phase in policy
