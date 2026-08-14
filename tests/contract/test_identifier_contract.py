"""The identifier policy document and the registry say the same thing.

``docs/IDENTIFIER_POLICY.md`` is where a contributor reads what they may call a
thing. The registry is where the answer comes from. Two statements of one rule
diverge unless something compares them, and here the dangerous direction is a
documented *permission*: a table saying a form is acceptable, read by somebody
who then names forty things that way.

The comparison is bidirectional and, for the operation matrix, executable. A
documented outcome is not compared against a string; the attempt is **run**, and
what it actually does is compared against what the row claims — the same strong
form ``tests/contract/test_values_contract.py`` uses. A third copy of the matrix
is legitimate for that reason: the code adjudicates between the document and the
test, so no two of the three can drift apart quietly.

The kinds table is compared against the ``summary`` field of each specification
rather than against a list written here. That is what makes the document a
reader of the registry instead of a second author of it.

What this file does not do is restate the rules. Whether the types behave is
``tests/unit/test_identifiers.py`` and
``tests/property/test_identifier_properties.py``; whether the domain layer stays
free of instances is ``tests/architecture/test_identifier_discipline.py``.
"""

import re
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Final

import pytest

from globin.adapters.identifiers import new_run_id
from globin.domain import identifiers, values
from globin.domain.identifiers import (
    RUN_ID_LENGTH,
    EnvironmentId,
    IdentifierKind,
    ModelId,
    OrderId,
    ProductId,
    RunId,
    environment_id,
    product_id,
    run_id,
    satisfies,
    specification,
    specifications,
)
from globin.domain.values import Symbol, symbol
from globin.errors import InternalError, ValidationError

POLICY_RELATIVE_PATH: Final[str] = "docs/IDENTIFIER_POLICY.md"

#: A row of the kinds table: three cells, the first a backticked SCREAMING name
#: and the last a backticked type. The other tables have two columns, so the
#: trailing cell is what keeps this from matching them.
KIND_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<kind>[A-Z][A-Z_]+)` \| (?P<denotes>[^|]+?) \| `(?P<carrier>\w+)` \|$",
    re.MULTILINE,
)

#: A row of the constants table: a backticked SCREAMING_SNAKE name and its value.
CONSTANT_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<name>[A-Z][A-Z0-9_]+)` \| `(?P<value>[^`]+)` \|$",
    re.MULTILINE,
)

#: A row of the operation matrix. The outcome cell is restricted to the four
#: words the document defines, which is what stops this matching a constants row.
MATRIX_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\| `(?P<attempt>[^`]+)` \| "
    r"`(?P<outcome>answers|ValidationError|TypeError|InternalError)` \|$",
    re.MULTILINE,
)

#: The type carrying each kind, by the name the document uses. ``Symbol`` comes
#: from Phase 008 and is here because the registry describes it without owning
#: it — which is the arrangement most worth holding to.
CARRIERS: Final[dict[str, type]] = {
    "Symbol": Symbol,
    "ProductId": ProductId,
    "EnvironmentId": EnvironmentId,
    "RunId": RunId,
    "ModelId": ModelId,
    "OrderId": OrderId,
}

A_RUN: Final[str] = "0123456789abcdef" * 2

#: Sample values, annotated `Any` on purpose. Some attempts below are static
#: errors mypy would refuse — which is half the guarantee, and not the half this
#: file is checking. Routing through `Any` lets the runtime answer for itself.
a_product: Any = product_id("spot")
another_product: Any = product_id("spot")
an_environment: Any = environment_id("spot")

#: Every documented row of the operation matrix, as something executable. A
#: mapping rather than `eval`, because `eval` is what ruff's S307 exists to stop
#: and because a callable can be type-checked.
ATTEMPTS: Final[dict[str, Callable[[], object]]] = {
    "specification of every kind": lambda: [specification(kind) for kind in IdentifierKind],
    "specification of an unregistered kind": lambda: specification("NOT_A_KIND"),  # type: ignore[arg-type]
    "satisfies with text in the form": lambda: satisfies(
        "spot", specification(IdentifierKind.PRODUCT)
    ),
    "satisfies with a non-string": lambda: satisfies(7, specification(IdentifierKind.PRODUCT)),
    "ProductId == ProductId, same text": lambda: a_product == another_product,
    "ProductId == EnvironmentId, same text": lambda: a_product == an_environment,
    "ProductId < ProductId": lambda: a_product < another_product,
    "hash of a ProductId": lambda: hash(a_product),
    "str of a ProductId": lambda: str(a_product),
    "ProductId spelled with uppercase": lambda: product_id("SPOT"),
    "ProductId spelled with a hyphen": lambda: product_id("spot-margin"),
    "ProductId of one character": lambda: product_id("s"),
    "ProductId built from a non-string": lambda: ProductId(text=7),  # type: ignore[arg-type]
    "OrderId spelled with mixed case": lambda: OrderId(text="GLOBIN-a_1"),
    "OrderId spelled with a full stop": lambda: OrderId(text="globin.1"),
    "RunId of thirty-two lowercase hexadecimal characters": lambda: run_id(A_RUN),
    "RunId of the wrong length": lambda: run_id("abc"),
    "RunId spelled with uppercase hexadecimal": lambda: run_id("A" * RUN_ID_LENGTH),
    "a newly minted run identifier": new_run_id,
}


def _outcome(attempt: Callable[[], object]) -> str:
    """Run an attempt and name what it did.

    Args:
        attempt: The operation to perform.

    Returns:
        The exception category, or ``"answers"`` when it returned a value.

    The three exception classes cannot overlap:
    :exc:`~globin.errors.ValidationError` and :exc:`~globin.errors.InternalError`
    both descend from :exc:`~globin.errors.GlobinError`, which inherits no
    builtin (ADR-0022), and they are siblings — so the order of the handlers is
    not load-bearing.
    """
    try:
        attempt()
    except ValidationError:
        return "ValidationError"
    except InternalError:
        return "InternalError"
    except TypeError:
        return "TypeError"
    return "answers"


@pytest.fixture(scope="module")
def policy(repo_root: Path) -> str:
    """The identifier policy document as written."""
    return (repo_root / POLICY_RELATIVE_PATH).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Guard the guards
#
# Every comparison below is only as good as its parser. One that silently
# matched nothing would make each of them pass while comparing two empty sets
# against each other.
# --------------------------------------------------------------------------


def test_the_kind_row_reader_finds_its_own_failing_case() -> None:
    """A three-column reader must not also swallow the two-column tables."""
    document = "\n".join(
        [
            "| Kind | Denotes | Carried by |",
            "|---|---|---|",
            "| `ALPHA` | A thing. | `Alpha` |",
            "| `SOME_BOUND` | `4` |",
            "",
        ]
    )
    assert KIND_ROW_RE.findall(document) == [("ALPHA", "A thing.", "Alpha")]
    assert not KIND_ROW_RE.findall("no table here")


def test_the_constant_row_reader_finds_its_own_failing_case() -> None:
    """A two-column reader must not also swallow the matrix."""
    document = "\n".join(
        [
            "| Constant | Value |",
            "|---|---|",
            "| `SOME_BOUND` | `4` |",
            "| `ProductId < ProductId` | `TypeError` |",
            "",
        ]
    )
    assert CONSTANT_ROW_RE.findall(document) == [("SOME_BOUND", "4")]
    assert not CONSTANT_ROW_RE.findall("no table here")


def test_the_matrix_row_reader_finds_its_own_failing_case() -> None:
    """The outcome vocabulary is what separates the matrix from the constants."""
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
# The kinds table
# --------------------------------------------------------------------------


def test_the_document_lists_every_kind_and_no_other(policy: str) -> None:
    """Both directions. A kind absent from the document is one nobody can look up."""
    documented = {match.group("kind") for match in KIND_ROW_RE.finditer(policy)}
    assert documented == {kind.value for kind in IdentifierKind}


def test_the_documented_kinds_are_listed_in_registry_order(policy: str) -> None:
    """Order is what lets a reader hold the two side by side without sorting either."""
    documented = [match.group("kind") for match in KIND_ROW_RE.finditer(policy)]
    assert documented == [spec.kind.value for spec in specifications()]


def test_each_documented_description_is_the_specifications_own_summary(policy: str) -> None:
    """The tripwire that makes the document a reader of the registry, not a second author.

    A description written independently would be free to describe something the
    registry stopped meaning three phases ago.
    """
    documented = {
        match.group("kind"): match.group("denotes") for match in KIND_ROW_RE.finditer(policy)
    }
    assert documented == {spec.kind.value: spec.summary for spec in specifications()}


@pytest.mark.parametrize("name", sorted(CARRIERS))
def test_every_documented_carrier_is_a_frozen_dataclass_with_fields(name: str) -> None:
    """The shape Phases 003 to 010 established, held to for these too."""
    subject = CARRIERS[name]
    assert is_dataclass(subject)
    assert subject.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert fields(subject)


def test_the_document_names_the_type_that_actually_carries_each_kind(policy: str) -> None:
    """A table pointing at a type that does not exist sends a reader to the wrong file."""
    unknown = {
        match.group("carrier")
        for match in KIND_ROW_RE.finditer(policy)
        if match.group("carrier") not in CARRIERS
    }
    assert not unknown, f"the policy names carriers that are not importable types: {unknown}"


# --------------------------------------------------------------------------
# The constants table
# --------------------------------------------------------------------------


def _published_constants() -> dict[str, object]:
    """Every uppercase ``str | int`` name the identifier module defines itself.

    Returns:
        The constants, by name.

    Names imported from :mod:`globin.domain.values` are excluded by identity.
    This module imports four of them deliberately — deriving the ``SYMBOL``
    specification from Phase 008's bounds is the point — and they appear in
    ``dir()`` exactly as if they had been defined here.
    ``VALUE_TYPES_POLICY.md`` owns them, so documenting them again here would be
    the duplication ``SOURCE_OF_TRUTH.md`` refuses.
    """
    return {
        name: value
        for name in dir(identifiers)
        if name.isupper()
        and not name.startswith("_")
        and isinstance(value := getattr(identifiers, name), str | int)
        and getattr(values, name, None) is not value
    }


def test_the_document_publishes_every_rule_the_module_does(policy: str) -> None:
    """Both directions, against the module rather than against a list written here."""
    documented = {match.group("name") for match in CONSTANT_ROW_RE.finditer(policy)}
    assert documented == set(_published_constants())


def test_every_documented_constant_carries_its_real_value(policy: str) -> None:
    """A stated bound that is not the enforced one is worse than none stated."""
    published = _published_constants()
    mismatched = {
        name: (match.group("value"), str(published[name]))
        for match in CONSTANT_ROW_RE.finditer(policy)
        if str(published[name := match.group("name")]) != match.group("value")
    }
    assert not mismatched, f"documented value, real value: {mismatched}"


# --------------------------------------------------------------------------
# The operation matrix, executed
# --------------------------------------------------------------------------


def test_the_matrix_describes_every_attempt_and_no_other(policy: str) -> None:
    """Both directions, so neither an undocumented attempt nor an unrun row survives."""
    documented = {match.group("attempt") for match in MATRIX_ROW_RE.finditer(policy)}
    assert documented == set(ATTEMPTS)


def test_every_documented_outcome_is_what_actually_happens(policy: str) -> None:
    """The strong form: the row is run, not read.

    A documented permission read by somebody who then writes code around it is
    the failure worth catching, and only running the attempt catches it.
    """
    wrong = {
        attempt: (outcome, actual)
        for match in MATRIX_ROW_RE.finditer(policy)
        if (attempt := match.group("attempt"))
        and (outcome := match.group("outcome")) != (actual := _outcome(ATTEMPTS[attempt]))
    }
    assert not wrong, f"documented outcome, real outcome: {wrong}"


# --------------------------------------------------------------------------
# The seam Phase 008 left, and this phase had to cut
# --------------------------------------------------------------------------


def test_a_rendered_symbol_satisfies_the_symbol_specification() -> None:
    """The registry describes a type it does not own, so something must hold the two together.

    `Symbol` predates this module and does not import it, which is what keeps
    Phase 008's code unchanged. The cost of that is exactly this test: without
    it, the `SYMBOL` specification could describe a form no `Symbol` renders.
    """
    spec = specification(IdentifierKind.SYMBOL)
    assert satisfies(str(symbol("BTC", "USDT")), spec)


def test_the_symbol_specification_is_not_a_second_copy_of_phase_008s_bounds() -> None:
    """Derivation rather than restatement, asserted so a later edit cannot quietly restate it.

    The bounds must be arithmetic on `values`' own constants. If somebody
    replaces them with literals, widening a currency code stops widening this
    and the two drift with nothing to notice.
    """
    spec = specification(IdentifierKind.SYMBOL)
    assert set(spec.alphabet) == set(values.CURRENCY_ALPHABET) | {values.SYMBOL_SEPARATOR}
    assert spec.min_length == 2 * values.MIN_CURRENCY_CODE_LENGTH + len(values.SYMBOL_SEPARATOR)
    assert spec.max_length == 2 * values.MAX_CURRENCY_CODE_LENGTH + len(values.SYMBOL_SEPARATOR)
