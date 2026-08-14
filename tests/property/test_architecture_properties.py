"""Invariants of the architecture review, over generated graphs and module names.

The architecture suite reviews the real tree and a handful of synthetic
violations. Those tests answer *is this repository clean* and *would a breach be
noticed*. They cannot answer *is the reviewer correct on inputs nobody wrote by
hand*, which is what a generated graph is for.

Two of the properties below are stated in documents and were, until Phase 005,
never actually checked: that the review is order-independent
(``ENGINEERING_CONTRACT.md`` invariant 3) and that a shared cycle is reported
once however it is reached.
"""

import ast
import keyword
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from globin.adapters.architecture import extract_imports, module_name
from globin.domain.architecture import (
    LAYER_ORDER,
    Layer,
    ModuleImports,
    import_cycles,
    top_level_package,
)
from globin.errors import ValidationError
from tests.support import architecture_contract, layer_policy

ROOT = "globin"

#: A single dotted-name component: a valid Python identifier, never a keyword.
#:
#: The keyword filter is not defensiveness. Hypothesis generated ``as`` on the
#: first run, ``import as`` is a syntax error, and the test that builds source
#: text failed for a reason that had nothing to do with the code under test.
components = (
    st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8)
    .filter(str.isidentifier)
    .filter(lambda name: not keyword.iskeyword(name))
)

#: A dotted module name, one to four components long.
module_names = st.lists(components, min_size=1, max_size=4).map(".".join)

#: Names of the synthetic modules used to build graphs. Kept to a small alphabet
#: so that generated graphs actually share nodes and can therefore form cycles.
graph_nodes = st.sampled_from([f"{ROOT}.m{index}" for index in range(6)])


# --------------------------------------------------------------------------
# Name handling
# --------------------------------------------------------------------------


@given(module=module_names)
def test_the_top_level_package_is_a_stable_prefix(module: str) -> None:
    """Idempotent, dot-free, and always a prefix of what it was given.

    Every later phase that decides whether an import is standard library, third
    party or GLOBIN's own routes through this function, so "the answer does not
    change if you ask twice" is worth pinning rather than assuming.
    """
    top = top_level_package(module)

    assert "." not in top
    assert module.startswith(top)
    assert top_level_package(top) == top


@given(package=components, suffix=module_names)
def test_a_layer_owns_everything_beneath_it_and_nothing_merely_similar(
    package: str, suffix: str
) -> None:
    """``layer_of`` must match on a dotted boundary, not on a string prefix.

    ``globin.domainx`` is not inside ``globin.domain``, and a naive
    ``startswith`` would say it is. That mistake would grant an unrelated package
    a layer's permissions, which is a boundary hole rather than a cosmetic bug.
    """
    policy = layer_policy(Layer.DOMAIN)
    contract = architecture_contract(policies=[policy])
    owned = policy.package

    assert contract.layer_of(owned) is Layer.DOMAIN
    assert contract.layer_of(f"{owned}.{suffix}") is Layer.DOMAIN
    assert contract.layer_of(f"{owned}{package}") is None


@given(parts=st.lists(components, min_size=1, max_size=3), is_package=st.booleans())
def test_a_module_name_is_the_root_package_plus_its_path(
    parts: list[str], is_package: bool
) -> None:
    """Path to dotted name, with ``__init__.py`` resolving to its package.

    The ``__init__`` case is the one that matters: getting it wrong would name a
    package's own module ``globin.domain.__init__``, which belongs to no layer
    and would therefore be silently exempt from every rule.
    """
    root = Path("/repo/src/globin")
    if is_package:
        path = root.joinpath(*parts, "__init__.py")
    else:
        path = root.joinpath(*parts[:-1], f"{parts[-1]}.py")

    name = module_name(path, root, ROOT)

    assert name.startswith(f"{ROOT}.")
    assert "__init__" not in name
    # Both shapes describe the same name: `a/b/__init__.py` and `a/b.py` are both
    # `globin.a.b`, which is exactly the equivalence the function exists to
    # produce.
    #
    # Asserting the components rather than searching the string for `.py` is
    # deliberate. The first version of this test asserted `".py" not in name`,
    # and Hypothesis produced a module legitimately called `py` — for which
    # `globin.py` is the correct answer and the assertion was simply wrong.
    assert name.split(".") == [ROOT, *parts]


@given(parts=st.lists(components, min_size=1, max_size=3))
def test_a_path_outside_the_package_root_is_refused(parts: list[str]) -> None:
    """Pairing a file with the wrong root is a caller error, not a silent name."""
    root = Path("/repo/src/globin")
    outside = Path("/repo/elsewhere").joinpath(*parts).with_suffix(".py")

    with pytest.raises(ValidationError, match="not inside the package root") as refused:
        module_name(outside, root, ROOT)

    assert str(root) in str(refused.value)


# --------------------------------------------------------------------------
# Import extraction
# --------------------------------------------------------------------------


@given(imported=st.lists(module_names, min_size=0, max_size=6))
def test_extracted_imports_are_sorted_and_deduplicated(imported: list[str]) -> None:
    """The extractor's output shape is what makes the review's output stable.

    Duplicates would be reported twice and an unsorted result would make two runs
    over one tree differ, so this underpins the determinism property below.
    """
    source = "".join(f"import {name}\n" for name in imported)

    found = extract_imports(ast.parse(source), ROOT)

    assert list(found) == sorted(set(found))
    assert set(found) == set(imported)


@given(level=st.integers(min_value=1, max_value=3), name=components)
def test_any_relative_import_is_refused(level: int, name: str) -> None:
    """Relative imports are banned repository-wide, at every depth."""
    source = f"from {'.' * level}{name} import thing\n"

    with pytest.raises(ValidationError, match="relative import"):
        extract_imports(ast.parse(source), ROOT)


# --------------------------------------------------------------------------
# Graph analysis
# --------------------------------------------------------------------------


@st.composite
def import_graphs(draw: st.DrawFn) -> tuple[ModuleImports, ...]:
    """A small graph over a fixed node set, so cycles arise naturally."""
    nodes = draw(st.lists(graph_nodes, min_size=1, max_size=6, unique=True))
    return tuple(
        ModuleImports(
            module=node,
            imported=tuple(draw(st.lists(st.sampled_from(nodes), max_size=3, unique=True))),
        )
        for node in nodes
    )


@given(graph=import_graphs())
def test_cycle_detection_is_stable_and_canonical(graph: tuple[ModuleImports, ...]) -> None:
    """Sorted, deduplicated, and each cycle rotated to start at its own smallest member.

    The same loop is reachable from every module on it. Without a canonical
    rotation the set would hold one entry per entry point, and a single cycle
    would be reported as several.
    """
    cycles = import_cycles(graph, ROOT)

    assert list(cycles) == sorted(set(cycles))
    for cycle in cycles:
        assert cycle[0] == min(cycle)


@given(graph=import_graphs())
def test_cycle_detection_does_not_depend_on_module_order(
    graph: tuple[ModuleImports, ...],
) -> None:
    """Reversing the input must not change the answer.

    Dictionary and set iteration appear throughout the traversal, and
    ``ENGINEERING_CONTRACT.md`` invariant 3 forbids any of it reaching a reported
    result.
    """
    assert import_cycles(graph, ROOT) == import_cycles(tuple(reversed(graph)), ROOT)


@given(graph=import_graphs())
def test_a_self_import_is_reported_as_a_cycle(graph: tuple[ModuleImports, ...]) -> None:
    """A module importing itself is the shortest possible loop, and still a loop."""
    subject = graph[0].module
    with_self_edge = (
        ModuleImports(module=subject, imported=(*graph[0].imported, subject)),
        *graph[1:],
    )

    assert (subject,) in import_cycles(with_self_edge, ROOT)


@given(graph=import_graphs())
def test_the_review_is_independent_of_the_order_modules_are_given(
    graph: tuple[ModuleImports, ...],
) -> None:
    """Two runs over the same tree must report identically — invariant 3, checked.

    The document has said this since Phase 003. Nothing asserted it: the real
    tree is scanned in sorted order, so the one call site could never have
    noticed if it were false.
    """
    contract = architecture_contract(
        policies=[layer_policy(layer) for layer in LAYER_ORDER],
        io_capable_modules=["socket", "os"],
    )

    assert contract.review(graph) == contract.review(tuple(reversed(graph)))
