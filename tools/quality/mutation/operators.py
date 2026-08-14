"""Finding the places a module could be wrong, and writing one of them wrong.

Mutation testing asks a question coverage cannot: not "did this line run" but
"would anything have noticed if it were different". This module answers the first
half — where a subtle change could be made — and applies exactly one of them at a
time.

Every operator here is chosen to be *subtle*. A mutant that makes the module
explode teaches nothing, because any test that touches it fails and the mutant
counts as killed without a single assertion having been read. Turning ``>=`` into
``>`` is different: it changes behaviour on one input, so it survives unless
somebody tested the boundary.

Deliberately excluded, each for a reason:

*String literals.* Almost every string in this repository is a docstring or an
error message, and error messages are matched loosely by design. Mutating them
produces equivalent mutants in bulk, which inflates the score while measuring
nothing.

*Statement deletion and return-value replacement.* Too fatal to be informative,
for the reason above.

*Inserting ``not`` into a condition.* ``not (a < b)`` is ``a >= b``, which the
comparison operator already generates. Two mutant identities for one semantic
change would corrupt the score.

*Integer members of an enumeration.* ``Severity.DEBUG = 10`` becoming ``11``
changes nothing GLOBIN depends on — the module says in as many words that only
the ordering matters — so it is a guaranteed survivor, and a guaranteed survivor
is noise in a report meant to be read.
"""

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

#: Comparison swaps. Each is one step from correct, which is exactly what an
#: untested boundary tolerates.
COMPARISONS: Final[dict[type[ast.cmpop], type[ast.cmpop]]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}

#: Short-circuit swaps. In the happy path both operands usually agree, so only a
#: mixed input distinguishes `and` from `or`.
BOOLEANS: Final[dict[type[ast.boolop], type[ast.boolop]]] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}

#: Arithmetic swaps, restricted to the two that appear in counters and offsets.
#: `*`, `/`, `//` and `%` are absent because no site for them exists in this
#: repository, and an operator with no site is code no test can reach.
ARITHMETIC: Final[dict[type[ast.operator], type[ast.operator]]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
}

#: Base-class name endings that mark a class body as an enumeration, whose
#: integer members are excluded.
ENUM_BASE_SUFFIXES: Final[tuple[str, ...]] = ("Enum", "Flag")


@dataclass(frozen=True, slots=True)
class MutationSite:
    """One place a module could be written differently, and how.

    Args:
        qualname: The enclosing class and function names, dotted. ``"<module>"``
            for a site at module level.
        operator: Which family of change this is.
        variant: The change itself, as ``before->after``.
        ordinal: Which one this is among the sites sharing the three fields
            above. Present so that two identical changes in one function are
            still separately identifiable.
        lineno: The line in the **original** source. Captured before any
            unparsing, because :func:`ast.unparse` reflows the module and every
            line number after the first mutation would otherwise be wrong.
        col_offset: The column in the original source, as a UTF-8 byte offset.

    ``lineno`` and ``col_offset`` are for the report only and deliberately not
    part of :attr:`identity`. A baseline keyed on line numbers would churn
    whenever anything above a target function moved; keyed on scope, it churns
    only when the mutated function itself changes, which is when a reviewer
    should be looking anyway.
    """

    qualname: str
    operator: str
    variant: str
    ordinal: int
    lineno: int
    col_offset: int

    @property
    def identity(self) -> str:
        """The stable name of this site, as it appears in a baseline."""
        return f"{self.qualname}::{self.operator}::{self.variant}::{self.ordinal}"


#: A site together with the change that produces it. The callable mutates the
#: tree it was built from, in place, and is used once.
Candidate = tuple[MutationSite, Callable[[], None]]


def sites(source: str) -> tuple[MutationSite, ...]:
    """Every place ``source`` could be mutated, in a deterministic order.

    Args:
        source: The module's text.

    Returns:
        The sites, sorted by position and then by what the change is, with
        ordinals assigned. The sort is explicit rather than inherited from the
        traversal, so the result cannot depend on how :mod:`ast` happens to
        order children in a future version.

    Raises:
        SyntaxError: If ``source`` does not parse.
    """
    return tuple(site for site, _mutate in _candidates(ast.parse(source)))


def apply(source: str, identity: str) -> str:
    """Return ``source`` with exactly one site changed.

    Args:
        source: The module's text.
        identity: Which site, as :attr:`MutationSite.identity`.

    Returns:
        The mutated module, unparsed. Comments and formatting are lost, which
        does not matter: the result is executed once and thrown away, never
        written back into the repository.

    Raises:
        KeyError: If no site has that identity.
        SyntaxError: If ``source`` does not parse.

    The tree is parsed again here rather than shared with :func:`sites`, so that
    enumerating cannot be affected by a previous mutation. Both functions read
    the same enumeration, which is what guarantees an identity means the same
    place in both.
    """
    tree = ast.parse(source)
    for site, mutate in _candidates(tree):
        if site.identity == identity:
            mutate()
            return ast.unparse(tree)
    msg = f"no mutation site called {identity!r}"
    raise KeyError(msg)


def _candidates(tree: ast.Module) -> tuple[Candidate, ...]:
    """Enumerate every candidate in a parsed module, ordered and numbered."""
    found = list(_walk(tree, scope=(), inside_enum=False))
    found.sort(
        key=lambda item: (
            item[0].lineno,
            item[0].col_offset,
            item[0].operator,
            item[0].variant,
        )
    )

    counts: dict[tuple[str, str, str], int] = {}
    numbered: list[Candidate] = []
    for site, mutate in found:
        key = (site.qualname, site.operator, site.variant)
        ordinal = counts.get(key, 0)
        counts[key] = ordinal + 1
        numbered.append((_renumbered(site, ordinal), mutate))
    return tuple(numbered)


def _renumbered(site: MutationSite, ordinal: int) -> MutationSite:
    """Return ``site`` with its ordinal set."""
    return MutationSite(
        qualname=site.qualname,
        operator=site.operator,
        variant=site.variant,
        ordinal=ordinal,
        lineno=site.lineno,
        col_offset=site.col_offset,
    )


def _walk(
    node: ast.AST,
    *,
    scope: tuple[str, ...],
    inside_enum: bool,
    parent: ast.AST | None = None,
    field: str = "",
    index: int | None = None,
) -> Iterator[Candidate]:
    """Yield every candidate at or below ``node``.

    Args:
        node: Where to look.
        scope: The enclosing class and function names.
        inside_enum: Whether ``node`` sits directly in an enumeration's body.
        parent: The node holding this one, needed by the changes that replace a
            node rather than edit it.
        field: Which of ``parent``'s fields holds ``node``.
        index: Which position, when that field is a list.
    """
    if isinstance(node, ast.ClassDef):
        scope = (*scope, node.name)
        inside_enum = _is_enumeration(node)
    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        scope = (*scope, node.name)
        inside_enum = False

    yield from _candidates_at(
        node, scope=scope, inside_enum=inside_enum, parent=parent, field=field, index=index
    )

    for name, value in ast.iter_fields(node):
        if isinstance(value, list):
            for position, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _walk(
                        item,
                        scope=scope,
                        inside_enum=inside_enum,
                        parent=node,
                        field=name,
                        index=position,
                    )
        elif isinstance(value, ast.AST):
            yield from _walk(
                value, scope=scope, inside_enum=inside_enum, parent=node, field=name, index=None
            )


def _candidates_at(
    node: ast.AST,
    *,
    scope: tuple[str, ...],
    inside_enum: bool,
    parent: ast.AST | None,
    field: str,
    index: int | None,
) -> Iterator[Candidate]:
    """Yield the candidates this one node offers, without descending."""
    qualname = ".".join(scope) if scope else "<module>"

    if isinstance(node, ast.Compare):
        yield from _comparison_candidates(node, qualname)
    elif isinstance(node, ast.BoolOp):
        yield from _swap_candidates(node, qualname, "boolean", BOOLEANS)
    elif isinstance(node, ast.BinOp):
        yield from _swap_candidates(node, qualname, "arithmetic", ARITHMETIC)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and parent is not None:
        yield from _not_removal_candidates(node, qualname, parent, field, index)
    elif isinstance(node, ast.Constant):
        yield from _constant_candidates(node, qualname, inside_enum=inside_enum)


def _comparison_candidates(node: ast.Compare, qualname: str) -> Iterator[Candidate]:
    """One candidate per comparison operator in a chain."""
    for position, op in enumerate(node.ops):
        # Indexed rather than looked up with a default, because the table covers
        # every subclass of `ast.cmpop` that exists — a test asserts it — and a
        # `.get` with a `continue` would be a silent skip nothing could reach.
        # If a future Python adds a comparison operator, this should fail loudly
        # rather than quietly stop finding sites.
        replacement = COMPARISONS[type(op)]
        site = MutationSite(
            qualname=qualname,
            operator="comparison",
            variant=f"{type(op).__name__}->{replacement.__name__}",
            ordinal=0,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        yield site, _set_comparison(node, position, replacement)


def _set_comparison(
    node: ast.Compare, position: int, replacement: type[ast.cmpop]
) -> Callable[[], None]:
    """Build the change that swaps one operator of a comparison chain."""

    def mutate() -> None:
        node.ops[position] = replacement()

    return mutate


def _swap_candidates(
    node: ast.BoolOp | ast.BinOp,
    qualname: str,
    operator: str,
    table: dict[type[ast.boolop], type[ast.boolop]] | dict[type[ast.operator], type[ast.operator]],
) -> Iterator[Candidate]:
    """One candidate for a node whose single ``op`` attribute can be swapped."""
    replacement = table.get(type(node.op))  # type: ignore[arg-type]
    if replacement is None:
        return
    site = MutationSite(
        qualname=qualname,
        operator=operator,
        variant=f"{type(node.op).__name__}->{replacement.__name__}",
        ordinal=0,
        lineno=node.lineno,
        col_offset=node.col_offset,
    )

    def mutate() -> None:
        node.op = replacement()

    yield site, mutate


def _not_removal_candidates(
    node: ast.UnaryOp, qualname: str, parent: ast.AST, field: str, index: int | None
) -> Iterator[Candidate]:
    """One candidate that drops a ``not``, inverting a guard.

    The change replaces the node inside its parent rather than editing it, which
    is why the walk carries the parent and the field it arrived through.
    """
    site = MutationSite(
        qualname=qualname,
        operator="not-removal",
        variant="remove",
        ordinal=0,
        lineno=node.lineno,
        col_offset=node.col_offset,
    )

    def mutate() -> None:
        if index is None:
            setattr(parent, field, node.operand)
        else:
            getattr(parent, field)[index] = node.operand

    yield site, mutate


def _constant_candidates(
    node: ast.Constant, qualname: str, *, inside_enum: bool
) -> Iterator[Candidate]:
    """One candidate for a boolean or an integer literal.

    ``bool`` is tested before ``int`` because ``isinstance(True, int)`` is true —
    the same ordering trap :mod:`globin.domain.values` documents.
    """
    if isinstance(node.value, bool):
        # Annotated `int` because that is what `ast.Constant.value` accepts and
        # `bool` is one. The runtime value stays a `bool`, so the variant reads
        # `True->False` rather than `1->0`.
        replacement: int = not node.value
        variant = f"{node.value}->{replacement}"
        operator = "boolean-constant"
    elif isinstance(node.value, int) and not inside_enum:
        replacement = node.value + 1
        variant = f"{node.value}->{replacement}"
        operator = "integer"
    else:
        return

    site = MutationSite(
        qualname=qualname,
        operator=operator,
        variant=variant,
        ordinal=0,
        lineno=node.lineno,
        col_offset=node.col_offset,
    )

    def mutate() -> None:
        node.value = replacement

    yield site, mutate


def _is_enumeration(node: ast.ClassDef) -> bool:
    """Whether a class body is an enumeration's, by the spelling of its bases."""
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if name.endswith(ENUM_BASE_SUFFIXES):
            return True
    return False
