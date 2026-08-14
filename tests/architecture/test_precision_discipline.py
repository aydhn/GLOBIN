"""Where a decimal context may come from, enforced against the real source tree.

Phase 010's whole claim is that GLOBIN's arithmetic does not depend on
thread-local state. :mod:`globin.domain.precision` honours it by building a
:class:`decimal.Context` per call and using its methods, which touch nothing
ambient. This module is what makes the opposite fail.

**Why nothing else already covers this.** Three checks look as though they
might, and none does:

* The dependency contract forbids an inner layer importing an I/O-capable
  module. ``decimal`` is deliberately absent from that list — the domain must be
  able to name ``Decimal`` at all — so ``decimal.getcontext()`` in the domain
  layer imports cleanly.
* Ruff has no rule about the decimal context. Its ``DTZ`` family is the closest
  analogue and concerns timezones.
* The unit and property tests assert that a *hostile ambient context changes no
  answer*. That is the behaviour, and it is checked. But it is checked for the
  functions somebody remembered to test; a new module reaching for
  :func:`decimal.localcontext` next year would be caught by nothing.

So the rule enforced here is the one none of those can: no module under
``src/globin`` reads, sets or borrows the ambient decimal context, anywhere,
including inside a function body.

The second rule is ADR-0030's own stated risk turned into a gate. That record
predicts the characteristic failure of denominated values as "a helper appearing
that strips ``.amount`` so the rest can work in raw ``Decimal``", and names that
helper as the observable signal. Outside the domain layer there are no such
reads today, so this is a tripwire from its first commit — exactly what
``test_clock_discipline.py`` was when Phase 009 wrote it.

Both checks are proxies rather than proofs, in the sense
``docs/architecture/dependency-rules.toml`` already uses about I/O imports: they
match spellings, so an alias defeats them. They catch the way a boundary is
realistically eroded — somebody reaches for the convenient thing — and each has
its own failing case below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import module_name
from globin.runtime.composition import PACKAGE_RELATIVE_PATH, ROOT_PACKAGE

#: Call spellings that reach the ambient decimal context, as :func:`ast.unparse`
#: renders them. Matched on the **dotted** spelling, so a ``Context`` object's own
#: methods — ``context.add(...)``, ``self._context.divmod(...)`` — are spared.
#: Those are the permitted form: they read the object they are called on and
#: nothing else.
AMBIENT_CONTEXT_CALLS: Final[frozenset[str]] = frozenset(
    {
        "getcontext",
        "decimal.getcontext",
        "setcontext",
        "decimal.setcontext",
        "localcontext",
        "decimal.localcontext",
        "DefaultContext.copy",
        "decimal.DefaultContext.copy",
    }
)

#: The one package permitted to read ``.amount`` off a value type. Everything
#: else must work in :class:`~globin.domain.values.Quantity` and
#: :class:`~globin.domain.values.Price`, or the denomination is ceremony.
DENOMINATION_AWARE_PACKAGE: Final[str] = f"{ROOT_PACKAGE}.domain"


def _ambient_context_calls(tree: ast.AST) -> list[str]:
    """Every ambient-context call in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The spellings found, in the order :func:`ast.walk` reaches them.

    Walks the whole tree, so a call inside a function body counts exactly as
    much as one at module level. A module-level one would additionally be caught
    by the import-time-work rule; a nested one would be caught by nothing else.
    """
    return [
        spelling
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (spelling := ast.unparse(node.func)) in AMBIENT_CONTEXT_CALLS
    ]


def _amount_reads(tree: ast.AST) -> list[str]:
    """Every ``.amount`` attribute read in a parsed module.

    Args:
        tree: The parsed source.

    Returns:
        The full spellings, such as ``held.amount``.
    """
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "amount"
    ]


def _package_modules(repo_root: Path) -> list[Path]:
    """Every module in the package, sorted so two runs report identically.

    Args:
        repo_root: The repository root.

    Returns:
        The paths.
    """
    return sorted((repo_root / PACKAGE_RELATIVE_PATH).rglob("*.py"))


def test_no_module_reads_the_ambient_decimal_context(repo_root: Path) -> None:
    """The rule the whole phase rests on, asserted against the real tree.

    An answer that changes because a caller set `prec` is not an answer, and it
    is the hidden global state `ENGINEERING_CONTRACT.md` invariant 5 forbids.
    """
    offenders = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE): calls
        for path in _package_modules(repo_root)
        if (calls := _ambient_context_calls(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert not offenders, (
        "the ambient decimal context is read inside the package; build a Context "
        f"and call its methods instead: {offenders}"
    )


def test_only_the_domain_layer_reads_an_amount_off_a_value(repo_root: Path) -> None:
    """ADR-0030's predicted failure, made to fail here instead of in six phases.

    A helper that strips `.amount` so the rest of the system can work in raw
    `Decimal` would undo denomination without removing it, leaving the types in
    place as decoration. There are no such reads today.
    """
    offenders = {
        name: reads
        for path in _package_modules(repo_root)
        if not (
            name := module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        ).startswith(DENOMINATION_AWARE_PACKAGE)
        and (reads := _amount_reads(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert not offenders, (
        "a value's amount is read outside the domain layer; pass the Quantity or "
        f"Price itself, so the denomination keeps meaning something: {offenders}"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("x = getcontext()\n", ["getcontext"], id="bare"),
        pytest.param("x = decimal.getcontext()\n", ["decimal.getcontext"], id="dotted"),
        pytest.param(
            "def f():\n    with localcontext() as c:\n        return c\n",
            ["localcontext"],
            id="inside a function",
        ),
        pytest.param("class A:\n    B = setcontext(None)\n", ["setcontext"], id="in a class body"),
        pytest.param("def f(c):\n    return c.add(1, 2)\n", [], id="a context method is spared"),
        pytest.param(
            "def f(self):\n    return self._context.divmod(1, 2)\n",
            [],
            id="a held context is spared",
        ),
    ],
)
def test_the_context_check_notices_a_read_and_spares_a_context_method(
    source: str, expected: list[str]
) -> None:
    """The guard's own failing cases, in both directions.

    ``TESTING_STRATEGY.md`` requires every checker to be exercised by something
    it must catch and something it must not. The last two rows are the ones that
    matter: if this check matched ``.add`` it would refuse the correct code.
    """
    assert _ambient_context_calls(ast.parse(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("x = held.amount\n", ["held.amount"], id="a read"),
        pytest.param("def f(q):\n    return q.amount + 1\n", ["q.amount"], id="inside a function"),
        pytest.param("x = held.currency\n", [], id="another attribute is spared"),
        pytest.param("amount = 1\n", [], id="a local named amount is spared"),
    ],
)
def test_the_amount_check_notices_a_read_and_spares_everything_else(
    source: str, expected: list[str]
) -> None:
    """The second guard's own failing cases."""
    assert _amount_reads(ast.parse(source)) == expected
