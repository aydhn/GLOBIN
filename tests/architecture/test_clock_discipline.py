"""Where a clock may be read, enforced against the real source tree.

``ENGINEERING_CONTRACT.md`` invariant 25 says wall-clock time is "an input to be
injected, never read ambiently by code that needs to be testable". Phase 009
delivered the seam that makes obeying it possible. This module is what makes
disobeying it fail.

**Why the existing checks do not already cover this.** Two of them look as
though they might, and neither does:

* The dependency contract forbids an inner layer importing an I/O-capable
  module. Phase 009 added ``time`` to that list, so ``import time`` in the
  domain layer is now caught there. But ``datetime`` is deliberately **not** on
  the list — invariant 25 presupposes that *aware* datetimes cross a domain
  boundary, so the domain must be able to name the type. That leaves
  ``datetime.now(UTC)`` in the domain importable and callable.
* Ruff's ``DTZ`` family refuses naive constructions repository-wide —
  ``datetime.now()`` without a timezone, ``utcnow()``, ``date.today()``. It
  enforces *awareness*. It says nothing about *where* an aware read may happen,
  and ``datetime.now(UTC)`` in the domain layer passes it cleanly.

So the rule this module enforces is the one neither of those can: a clock is
read in the adapters layer, and nowhere else.

The check is a proxy rather than a proof, in the same sense
``docs/architecture/dependency-rules.toml`` already uses about I/O imports: it
matches call spellings, so an alias defeats it. It catches the way the boundary
is realistically eroded — somebody reaches for ``datetime.now`` because it was
convenient — and its own failing case is exercised below.
"""

import ast
from pathlib import Path
from typing import Final

import pytest

from globin.adapters.architecture import TomlArchitectureContractSource, module_name
from globin.domain.architecture import Layer
from globin.runtime.composition import (
    CONTRACT_RELATIVE_PATH,
    PACKAGE_RELATIVE_PATH,
    ROOT_PACKAGE,
)

AMBIENT_CLOCK_CALLS: Final[frozenset[str]] = frozenset(
    {
        "date.today",
        "datetime.date.today",
        "datetime.datetime.fromtimestamp",
        "datetime.datetime.now",
        "datetime.datetime.today",
        "datetime.datetime.utcnow",
        "datetime.datetime.utcfromtimestamp",
        "datetime.fromtimestamp",
        "datetime.now",
        "datetime.today",
        "datetime.utcnow",
        "datetime.utcfromtimestamp",
        "time.gmtime",
        "time.localtime",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
        "time.time",
        "time.time_ns",
    }
)
"""Call spellings that read a clock, as :func:`ast.unparse` renders them.

Matched on the **dotted spelling**, never on the bare attribute name. A rule
that forbade ``.now`` anywhere would forbid ``self.clock.now()`` — the correct,
injected call this whole phase exists to make possible — and would therefore
punish the fix rather than the fault.

Both the module-qualified and the ``from``-imported spellings appear, because
``datetime.now(UTC)`` and ``datetime.datetime.now(UTC)`` are the same call
written after two different imports.
"""

CLOCK_READING_LAYERS: Final[frozenset[Layer]] = frozenset({Layer.ADAPTERS, Layer.RUNTIME})
"""The layers permitted to read a clock.

``adapters`` because reading the host is what an adapter is for. ``runtime``
because the composition root constructs the adapter, and constructing one is not
reading one — no call in :mod:`globin.runtime.composition` appears in
:data:`AMBIENT_CLOCK_CALLS`, so the permission is currently unused and the test
below would still pass if it were withdrawn. It is stated rather than discovered
so that a future composition-root change is an arguable edit rather than a
surprise.
"""


def _clock_calls(tree: ast.AST) -> list[str]:
    """Every ambient clock call in a parsed module, anywhere in it.

    Args:
        tree: A parsed module.

    Returns:
        The offending spellings, in traversal order.

    Unlike the import-time checker in ``test_architecture_contract.py``, this
    walks into function bodies. That checker asks what runs when a module is
    imported; this one asks what the module is capable of, and a clock read
    hidden inside a function is exactly the case worth catching.
    """
    return [
        spelling
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (spelling := ast.unparse(node.func)) in AMBIENT_CLOCK_CALLS
    ]


def _layer_modules(repo_root: Path, layer: Layer) -> list[Path]:
    """Every Python file in one layer package."""
    return sorted((repo_root / PACKAGE_RELATIVE_PATH / layer.value).rglob("*.py"))


@pytest.mark.parametrize(
    "layer",
    [layer for layer in Layer if layer not in CLOCK_READING_LAYERS],
)
def test_an_inner_layer_never_reads_a_clock(repo_root: Path, layer: Layer) -> None:
    """The domain, the ports and the application layer are handed the time."""
    offenders = [
        f"{module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)}: {call}()"
        for path in _layer_modules(repo_root, layer)
        for call in _clock_calls(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    ]
    assert not offenders, (
        f"a clock is read in the {layer.value} layer: {offenders}. "
        f"Take a globin.ports.clock.Clock as a dependency instead"
    )


def test_only_the_clock_adapter_reads_a_clock(repo_root: Path) -> None:
    """Even inside `adapters`, exactly one module reads the host clock.

    The permission is per-layer, but the *fact* is narrower, and pinning the
    fact is what proves the Phase 009 seam moved rather than merely being
    duplicated. Before this phase
    :mod:`globin.adapters.observability` called ``datetime.now(UTC)``; if it
    reappeared there, the layer rule above would still pass and this one would
    not.
    """
    readers = {
        module_name(path, repo_root / PACKAGE_RELATIVE_PATH, ROOT_PACKAGE)
        for path in _layer_modules(repo_root, Layer.ADAPTERS)
        if _clock_calls(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    }
    assert readers == {f"{ROOT_PACKAGE}.adapters.clock"}


def test_the_contract_treats_time_and_datetime_differently(
    repo_root: Path,
) -> None:
    """`time` is I/O-capable; `datetime` deliberately is not.

    The asymmetry is the arguable part, so it is asserted rather than left to be
    noticed. ``time`` is entirely a clock-and-sleep module: every reason to
    import it in an inner layer is a reason to read the host, so banning the
    import is exact. ``datetime`` is mostly a calendar-and-value module, and
    banning it would make invariant 25 unimplementable — "timezone-naive
    datetimes must not cross a domain boundary" presupposes that aware ones do.

    Deleting either half of this is then a visible edit with a test to answer,
    which is the point.
    """
    contract = TomlArchitectureContractSource(repo_root / CONTRACT_RELATIVE_PATH).load()
    assert "time" in contract.io_capable_modules
    assert "datetime" not in contract.io_capable_modules


def test_the_clock_check_notices_a_read_and_spares_an_injected_one() -> None:
    """Guard the checker: a validator whose negative case never runs rots."""
    assert _clock_calls(ast.parse("import time\nx = time.monotonic_ns()\n")) == [
        "time.monotonic_ns"
    ]
    assert _clock_calls(ast.parse("def f():\n    return datetime.now(UTC)\n")) == ["datetime.now"]
    assert _clock_calls(ast.parse("class A:\n    B = datetime.utcnow()\n")) == ["datetime.utcnow"]
    assert _clock_calls(ast.parse("def f(self):\n    return self.clock.now()\n")) == []
    assert _clock_calls(ast.parse("def f(c):\n    return c.reading()\n")) == []
